import time
import uuid
import logging
from typing import Optional
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from src.db.sqlite import init_db, is_email_processed, mark_email_processed
from src.tools.gmail_tools import list_unread_emails, get_email_details
from src.graph import app as workflow_app
from src.tools.rag import add_to_vector_store
from src.routes.approval_page import router as approval_router
from src.routes.chat_webhook import router as chat_router
from src.agents.approval_gateway_agent import ApprovalGatewayAgent
from src.agents.controller_agent import ControllerAgent
from src.agents.ar_agent import ARAgent
from src.agents.progress_billing_agent import ProgressBillingAgent

logger = logging.getLogger(__name__)

app = FastAPI(title="Cozy Finance Agents")
app.include_router(approval_router)
app.include_router(chat_router)

approval_gateway = ApprovalGatewayAgent()
controller = ControllerAgent()
ar_agent = ARAgent()
progress_billing = ProgressBillingAgent()


class VoiceNote(BaseModel):
    text: str


class ApprovalRequest(BaseModel):
    approval_type: str
    title: str
    description: str = None
    amount: float = None
    currency: str = "USD"
    payload: dict = {}
    approver_email: str = None
    agent_name: str = None


class CreateJobRequest(BaseModel):
    name: str
    customer_name: str
    contract_amount: float
    customer_email: Optional[str] = None
    deposit_percent: Optional[float] = None
    retainage_percent: Optional[float] = None
    qbo_customer_id: Optional[str] = None


class UpdateCompletionRequest(BaseModel):
    completion_percent: float


@app.on_event("startup")
def startup_event():
    init_db()


def process_email(email_details):
    if not is_email_processed(email_details['id']):
        logger.info(f"Processing email: {email_details['id']}")
        try:
            workflow_app.invoke({"email": email_details})
            mark_email_processed(email_details['id'])
        except Exception as e:
            logger.error(f"Error processing email {email_details['id']}: {e}")


@app.get("/sync")
def sync_emails(background_tasks: BackgroundTasks):
    emails = list_unread_emails()
    for email in emails:
        details = get_email_details(email['id'])
        if details:
            background_tasks.add_task(process_email, details)
    return {"status": "sync started", "emails_queued": len(emails)}


@app.post("/voice-note")
def receive_voice_note(note: VoiceNote, background_tasks: BackgroundTasks):
    mock_email = {
        'id': f"voice-{uuid.uuid4()}",
        'subject': "Voice Note Ingestion",
        'sender': "Voice Assistant",
        'body': note.text,
        'attachments': [],
        'threadId': None
    }
    background_tasks.add_task(workflow_app.invoke, {"email": mock_email})
    return {"status": "voice note received and being processed"}


@app.post("/ingest-knowledge")
def ingest_knowledge(content: str, metadata: dict = {}):
    doc_id = str(uuid.uuid4())
    add_to_vector_store("personal_knowledge", [content], [metadata], [doc_id])
    return {"status": "knowledge ingested", "id": doc_id}


# --- Finance Agent Endpoints ---

@app.post("/finance/approvals")
def create_approval(request: ApprovalRequest):
    result = approval_gateway.submit(
        approval_type=request.approval_type,
        title=request.title,
        description=request.description,
        amount=request.amount,
        currency=request.currency,
        payload=request.payload,
        approver_email=request.approver_email,
        agent_name=request.agent_name,
    )
    return result


@app.get("/finance/approvals/pending")
def list_pending_approvals(approver_email: str = None):
    return approval_gateway.get_pending(approver_email)


@app.get("/finance/reconciliation")
def run_reconciliation():
    return controller.run_reconciliation_check()


@app.get("/finance/close-checklist")
def get_close_checklist():
    return controller.get_close_checklist()


@app.get("/finance/data-quality")
def check_data_quality():
    return controller.find_data_quality_issues()


# --- AR Agent Endpoints ---

@app.get("/finance/ar/summary")
def ar_summary():
    return ar_agent.get_summary()


@app.get("/finance/ar/aging")
def ar_aging():
    return ar_agent.get_ar_aging()


@app.get("/finance/ar/overdue")
def ar_overdue():
    return ar_agent.get_overdue_invoices()


@app.get("/finance/ar/payments/match")
def ar_match_payments(since_date: str = None):
    return ar_agent.match_payments(since_date)


@app.post("/finance/ar/collections")
def ar_run_collections():
    return ar_agent.run_collections_cycle()


@app.get("/finance/ar/lien-rights")
def ar_lien_rights(job_completion_date: str):
    return ar_agent.get_lien_rights_alert(job_completion_date)


# --- Progress Billing Endpoints ---

@app.post("/finance/jobs")
def create_job(request: CreateJobRequest):
    return progress_billing.create_job(
        name=request.name,
        customer_name=request.customer_name,
        contract_amount=request.contract_amount,
        customer_email=request.customer_email,
        deposit_percent=request.deposit_percent,
        retainage_percent=request.retainage_percent,
        qbo_customer_id=request.qbo_customer_id,
    )


@app.get("/finance/jobs")
def list_jobs(status: str = None):
    return progress_billing.list_jobs(status)


@app.get("/finance/jobs/alerts")
def billing_alerts():
    return progress_billing.check_billing_alerts()


@app.get("/finance/jobs/{job_id}")
def get_job(job_id: str):
    job = progress_billing.get_job(job_id)
    if not job:
        return {"error": "Job not found"}
    return job


@app.get("/finance/jobs/{job_id}/schedule")
def get_billing_schedule(job_id: str):
    schedule = progress_billing.get_billing_schedule(job_id)
    if not schedule:
        return {"error": "Job not found"}
    return schedule


@app.patch("/finance/jobs/{job_id}/completion")
def update_job_completion(job_id: str, request: UpdateCompletionRequest):
    job = progress_billing.update_completion(job_id, request.completion_percent)
    if not job:
        return {"error": "Job not found"}
    return job


@app.post("/finance/jobs/{job_id}/invoice/deposit")
def invoice_deposit(job_id: str):
    return progress_billing.invoice_deposit(job_id)


@app.post("/finance/jobs/{job_id}/invoice/milestone/{milestone_name}")
def invoice_milestone(job_id: str, milestone_name: str):
    return progress_billing.invoice_milestone(job_id, milestone_name)


@app.post("/finance/jobs/{job_id}/invoice/final")
def invoice_final(job_id: str):
    return progress_billing.invoice_final(job_id)


@app.post("/finance/jobs/{job_id}/invoice/retainage")
def invoice_retainage(job_id: str):
    return progress_billing.invoice_retainage(job_id)


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=3000)
