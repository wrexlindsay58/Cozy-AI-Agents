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
from src.agents.ap_agent import APAgent
from src.agents.sub_compliance_agent import SubComplianceAgent
from src.agents.job_costing_agent import JobCostingAgent
from src.agents.change_order_agent import ChangeOrderAgent
from src.agents.commission_agent import CommissionAgent
from src.agents.payroll_agent import PayrollAgent
from src.agents.profitability_agent import ProfitabilityAgent
from src.agents.cash_flow_agent import CashFlowAgent

logger = logging.getLogger(__name__)

app = FastAPI(title="Cozy Finance Agents")
app.include_router(approval_router)
app.include_router(chat_router)

approval_gateway = ApprovalGatewayAgent()
controller = ControllerAgent()
ar_agent = ARAgent()
progress_billing = ProgressBillingAgent()
ap_agent = APAgent()
sub_compliance = SubComplianceAgent()
job_costing = JobCostingAgent()
change_order = ChangeOrderAgent()
commission = CommissionAgent()
payroll = PayrollAgent()
profitability = ProfitabilityAgent()
cash_flow = CashFlowAgent()


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


class CreateBillRequest(BaseModel):
    vendor_name: str
    amount: float
    invoice_number: str
    invoice_date: str
    due_date: Optional[str] = None
    description: str = ""
    job_reference: Optional[str] = None
    is_subcontractor: bool = False


class RegisterVendorRequest(BaseModel):
    vendor_name: str
    is_subcontractor: bool = False
    billcom_vendor_id: Optional[str] = None
    coi_expiration: Optional[str] = None
    w9_on_file: bool = False
    lien_waiver_required: bool = True
    notes: Optional[str] = None


class UpdateCOIRequest(BaseModel):
    coi_expiration: str
    document_url: Optional[str] = None


class SetBudgetRequest(BaseModel):
    labor: Optional[float] = 0
    materials: Optional[float] = 0
    subcontractor: Optional[float] = 0
    permits: Optional[float] = 0
    overhead: Optional[float] = 0
    other: Optional[float] = 0


class AddCostRequest(BaseModel):
    category: str
    amount: float
    description: str = ""
    source: str = "manual"


class CreateChangeOrderRequest(BaseModel):
    title: str
    description: str
    additional_revenue: float
    additional_cost: float
    submit_approval: bool = True


class SetAttributionRequest(BaseModel):
    sales_rep_id: Optional[str] = None
    sales_rep_name: Optional[str] = None
    lead_setter_id: Optional[str] = None
    lead_setter_name: Optional[str] = None
    sales_rep_split: Optional[float] = 80.0
    lead_setter_split: Optional[float] = 20.0


class AccrueCommissionRequest(BaseModel):
    trigger: str  # signing, milestone, completion


class ProposePayoutRequest(BaseModel):
    commission_ids: Optional[list[str]] = None
    period: Optional[str] = None


class ProposePayrollRequest(BaseModel):
    period: Optional[str] = None


class JobAffordabilityRequest(BaseModel):
    contract_amount: float
    estimated_costs: float
    deposit_percent: Optional[float] = 40
    duration_weeks: Optional[int] = 8


class CashScenarioRequest(BaseModel):
    accelerate_ar_days: Optional[int] = 0
    defer_ap_days: Optional[int] = 0


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


@app.get("/finance/jobs/portfolio")
def job_portfolio_summary():
    return job_costing.get_portfolio_summary()


@app.get("/finance/jobs/wip")
def job_wip_report():
    return job_costing.get_wip_report()


@app.get("/finance/jobs/variance-alerts")
def job_variance_alerts():
    return job_costing.get_variance_alerts()


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


# --- AP Agent Endpoints ---

@app.get("/finance/ap/summary")
def ap_summary():
    return ap_agent.get_ap_summary()


@app.get("/finance/ap/bills/unpaid")
def ap_unpaid_bills():
    return ap_agent.list_unpaid_bills()


@app.get("/finance/ap/sync-status")
def ap_sync_status():
    return ap_agent.check_sync_status()


@app.post("/finance/ap/bills")
def ap_create_bill(request: CreateBillRequest):
    return ap_agent.create_bill(
        vendor_name=request.vendor_name,
        amount=request.amount,
        invoice_number=request.invoice_number,
        invoice_date=request.invoice_date,
        due_date=request.due_date,
        description=request.description,
        job_reference=request.job_reference,
        is_subcontractor=request.is_subcontractor,
    )


@app.post("/finance/ap/bills/extract")
def ap_extract_bill(text: str):
    return ap_agent.extract_bill_from_text(text)


@app.post("/finance/ap/payments/propose")
def ap_propose_payment_batch(bill_ids: list[str] = None):
    return ap_agent.propose_payment_batch(bill_ids)


# --- Subcontractor Compliance Endpoints ---

@app.get("/finance/compliance/dashboard")
def compliance_dashboard():
    return sub_compliance.get_dashboard()


@app.get("/finance/compliance/vendors")
def compliance_list_vendors(is_subcontractor: bool = None):
    return sub_compliance.list_vendors(is_subcontractor)


@app.post("/finance/compliance/vendors")
def compliance_register_vendor(request: RegisterVendorRequest):
    return sub_compliance.register_vendor(**request.model_dump())


@app.get("/finance/compliance/vendors/{vendor_name}")
def compliance_check_vendor(vendor_name: str):
    return sub_compliance.check_compliance(vendor_name)


@app.patch("/finance/compliance/vendors/{vendor_name}/coi")
def compliance_update_coi(vendor_name: str, request: UpdateCOIRequest):
    return sub_compliance.update_coi(vendor_name, request.coi_expiration, request.document_url)


@app.get("/finance/compliance/expiring")
def compliance_expiring_coi(within_days: int = 30):
    return sub_compliance.list_expiring_coi(within_days)


@app.get("/finance/compliance/non-compliant")
def compliance_non_compliant():
    return sub_compliance.list_non_compliant()


# --- Job Costing Endpoints (job-specific) ---

@app.get("/finance/jobs/{job_id}/pnl")
def job_pnl(job_id: str):
    pnl = job_costing.get_job_pnl(job_id)
    if not pnl:
        return {"error": "Job not found"}
    return pnl


@app.put("/finance/jobs/{job_id}/budget")
def set_job_budget(job_id: str, request: SetBudgetRequest):
    return job_costing.set_budget(job_id, request.model_dump(exclude_none=True))


@app.post("/finance/jobs/{job_id}/costs")
def add_job_cost(job_id: str, request: AddCostRequest):
    return job_costing.add_cost(
        job_id, request.category, request.amount,
        request.description, request.source,
    )


# --- Change Order Endpoints ---

@app.post("/finance/change-orders/extract")
def extract_change_order(text: str, job_id: str = None):
    return change_order.extract_from_text(text, job_id)


@app.get("/finance/change-orders/risks")
def change_order_risks():
    return change_order.get_risk_report()


@app.get("/finance/change-orders/unsigned")
def change_orders_unsigned(job_id: str = None):
    return change_order.list_unsigned(job_id)


@app.get("/finance/jobs/{job_id}/change-orders")
def list_job_change_orders(job_id: str):
    return change_order.list_for_job(job_id)


@app.post("/finance/jobs/{job_id}/change-orders")
def create_change_order(job_id: str, request: CreateChangeOrderRequest):
    return change_order.create_change_order(
        job_id=job_id,
        title=request.title,
        description=request.description,
        additional_revenue=request.additional_revenue,
        additional_cost=request.additional_cost,
        submit_approval=request.submit_approval,
    )


@app.get("/finance/change-orders/{co_id}")
def get_change_order(co_id: str):
    co = change_order.get_change_order(co_id)
    if not co:
        return {"error": "Change order not found"}
    return co


@app.post("/finance/change-orders/{co_id}/approve")
def approve_change_order(co_id: str):
    return change_order.approve(co_id)


@app.post("/finance/change-orders/{co_id}/reject")
def reject_change_order(co_id: str):
    return change_order.reject(co_id)


@app.post("/finance/change-orders/{co_id}/customer-approved")
def customer_approve_change_order(co_id: str):
    return change_order.mark_customer_approved(co_id)


@app.get("/finance/change-orders/{co_id}/draft-email")
def draft_change_order_email(co_id: str):
    return change_order.draft_customer_email(co_id)


# --- Commission Agent Endpoints ---

@app.get("/finance/commissions/summary")
def commission_summary():
    return commission.get_summary()


@app.get("/finance/commissions/rules")
def commission_rules():
    return commission.get_rules()


@app.get("/finance/commissions")
def list_commissions(job_id: str = None, period: str = None, status: str = None):
    return commission.list_commissions(job_id=job_id, period=period, status=status)


@app.put("/finance/jobs/{job_id}/attribution")
def set_job_attribution(job_id: str, request: SetAttributionRequest):
    return commission.set_attribution(job_id, **request.model_dump(exclude_none=True))


@app.get("/finance/jobs/{job_id}/attribution")
def get_job_attribution(job_id: str):
    from src.db import commissions as comm_db
    attr = comm_db.get_attribution(job_id)
    if not attr:
        return {"error": "No attribution set for this job"}
    return attr


@app.post("/finance/jobs/{job_id}/commissions/calculate")
def calculate_job_commissions(job_id: str, trigger: str = None):
    records = commission.calculate_for_job(job_id, trigger=trigger)
    return {"job_id": job_id, "commissions": records, "count": len(records)}


@app.post("/finance/jobs/{job_id}/commissions/accrue")
def accrue_job_commissions(job_id: str, request: AccrueCommissionRequest):
    return commission.accrue_at_trigger(job_id, request.trigger)


@app.post("/finance/jobs/{job_id}/commissions/clawback")
def clawback_job_commissions(job_id: str, reason: str = "Job cancelled"):
    return commission.clawback(job_id, reason)


@app.get("/finance/commissions/statement/{rep_name}")
def commission_statement(rep_name: str, period: str = None):
    return commission.get_monthly_statement(rep_name, period)


@app.post("/finance/commissions/propose-payout")
def propose_commission_payout(request: ProposePayoutRequest):
    return commission.propose_payout(
        commission_ids=request.commission_ids,
        period=request.period,
    )


# --- Payroll Agent Endpoints ---

@app.get("/finance/payroll/summary")
def payroll_summary():
    return payroll.get_summary()


@app.get("/finance/payroll/employees")
def payroll_employees():
    return payroll.get_employee_roster()


@app.get("/finance/payroll/validate")
def payroll_validate(period: str = None):
    return payroll.pre_validate_payroll(period)


@app.get("/finance/payroll/runs")
def list_payroll_runs(period: str = None, status: str = None):
    from src.db import payroll as payroll_db
    return payroll_db.list_payroll_runs(period=period, status=status)


@app.get("/finance/payroll/runs/{run_id}")
def get_payroll_run(run_id: str):
    from src.db import payroll as payroll_db
    run = payroll_db.get_payroll_run(run_id)
    if not run:
        return {"error": "Payroll run not found"}
    return run


@app.post("/finance/payroll/propose")
def propose_payroll_run(request: ProposePayrollRequest):
    return payroll.propose_payroll_run(request.period)


@app.post("/finance/payroll/allocate")
def allocate_payroll_labor(period: str):
    allocations = payroll.allocate_labor_costs(period)
    return {"period": period, "allocations": allocations, "count": len(allocations)}


@app.get("/finance/payroll/reconcile")
def reconcile_payroll(period: str = None):
    return payroll.reconcile_payroll_jes(period)


# --- Profitability Agent Endpoints ---

@app.get("/finance/profitability/pnl")
def company_pnl(start_date: str = None, end_date: str = None):
    return profitability.get_company_pnl(start_date, end_date)


@app.get("/finance/profitability/balance-sheet")
def balance_sheet(as_of_date: str = None):
    return profitability.get_balance_sheet(as_of_date)


@app.get("/finance/profitability/margins-by-type")
def margins_by_job_type():
    return profitability.get_margins_by_job_type()


@app.get("/finance/profitability/rep-rankings")
def rep_rankings():
    return profitability.get_rep_rankings()


@app.get("/finance/profitability/seasonal-trends")
def seasonal_trends(months: int = 12):
    return profitability.get_seasonal_trends(months)


@app.get("/finance/profitability/variance")
def estimate_to_actual_variance():
    return profitability.get_estimate_to_actual_variance()


@app.get("/finance/profitability/monthly-package")
def monthly_financial_package(period: str = None):
    return profitability.get_monthly_package(period)


@app.post("/finance/profitability/dashboard")
def push_profitability_dashboard(frequency: str = "daily"):
    return profitability.push_dashboard_to_chat(frequency)


# --- Cash Flow Agent Endpoints ---

@app.get("/finance/cash-flow/summary")
def cash_flow_summary():
    return cash_flow.get_summary()


@app.get("/finance/cash-flow/position")
def cash_position():
    return cash_flow.get_current_cash_position()


@app.get("/finance/cash-flow/forecast")
def cash_flow_forecast():
    return cash_flow.get_13_week_forecast()


@app.post("/finance/cash-flow/affordability")
def analyze_affordability(request: JobAffordabilityRequest):
    return cash_flow.analyze_job_affordability(**request.model_dump())


@app.get("/finance/cash-flow/affordability/{job_id}")
def analyze_job_affordability(job_id: str):
    return cash_flow.analyze_job_affordability_by_id(job_id)


@app.get("/finance/cash-flow/seasonal")
def seasonal_cash_plan():
    return cash_flow.get_seasonal_plan()


@app.post("/finance/cash-flow/scenario")
def cash_flow_scenario(request: CashScenarioRequest):
    return cash_flow.model_collection_scenario(
        accelerate_ar_days=request.accelerate_ar_days,
        defer_ap_days=request.defer_ap_days,
    )


@app.post("/finance/cash-flow/alert")
def push_cash_alert():
    return cash_flow.push_cash_alert_to_chat()


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=3000)
