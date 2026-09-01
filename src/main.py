import time
import uuid
import logging
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

logger = logging.getLogger(__name__)

app = FastAPI(title="Cozy Finance Agents")
app.include_router(approval_router)
app.include_router(chat_router)

approval_gateway = ApprovalGatewayAgent()
controller = ControllerAgent()


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


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=3000)
