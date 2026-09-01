import logging
from datetime import datetime, timedelta
from src.tools import quickbooks_tools as qbo
from src.db import job_billing as jb
from src.db.job_billing import MilestoneStatus
from src.agents.approval_gateway_agent import ApprovalGatewayAgent

logger = logging.getLogger(__name__)


class ProgressBillingAgent:
    """Milestone-based billing for home improvement jobs — deposits, draws, retainage."""

    def __init__(self):
        self.approval_gateway = ApprovalGatewayAgent()

    def create_job(
        self,
        name: str,
        customer_name: str,
        contract_amount: float,
        customer_email: str = None,
        deposit_percent: float = None,
        retainage_percent: float = None,
        qbo_customer_id: str = None,
    ) -> dict:
        if not qbo_customer_id:
            customer = qbo.get_customer_by_name(customer_name)
            if customer:
                qbo_customer_id = customer.get("Id")

        job = jb.create_job(
            name=name,
            customer_name=customer_name,
            contract_amount=contract_amount,
            customer_email=customer_email,
            deposit_percent=deposit_percent,
            retainage_percent=retainage_percent,
            qbo_customer_id=qbo_customer_id,
        )
        logger.info(f"Created job {job['id']}: {name} (${contract_amount:,.2f})")
        return job

    def get_job(self, job_id: str) -> dict | None:
        return jb.get_job(job_id)

    def list_jobs(self, status: str = None) -> list[dict]:
        return jb.list_jobs(status)

    def update_completion(self, job_id: str, completion_percent: float) -> dict | None:
        job = jb.update_job_completion(job_id, completion_percent)
        if job and job.get("billing_behind"):
            logger.warning(
                f"Job {job_id} billing behind: {job['completion_percent']}% complete "
                f"but only {job['billed_percent']}% billed"
            )
        return job

    def invoice_deposit(self, job_id: str, submit_approval: bool = True) -> dict:
        job = jb.get_job(job_id)
        if not job:
            return {"error": "Job not found"}

        deposit = job.get("deposit")
        if not deposit:
            return {"error": "No deposit configured for this job"}
        if deposit["status"] != MilestoneStatus.PENDING.value:
            return {"error": f"Deposit already {deposit['status']}"}

        if not job.get("qbo_customer_id"):
            return self._submit_invoice_approval(
                job, "deposit", deposit["amount"],
                f"Deposit — {job['name']} ({deposit['percentage']}%)",
                submit_approval,
            )

        invoice = qbo.create_invoice(
            customer_id=job["qbo_customer_id"],
            line_items=[{
                "description": f"Deposit — {job['name']} ({deposit['percentage']}%)",
                "amount": deposit["amount"],
            }],
            due_date=(datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
            memo=f"Job deposit for {job['name']}",
        )

        if invoice:
            jb.mark_deposit_invoiced(job_id, invoice.get("Id"))
            return {"status": "invoiced", "qbo_invoice_id": invoice.get("Id"), "amount": deposit["amount"]}

        return self._submit_invoice_approval(
            job, "deposit", deposit["amount"],
            f"Deposit — {job['name']} ({deposit['percentage']}%)",
            submit_approval,
        )

    def invoice_milestone(self, job_id: str, milestone_name: str, submit_approval: bool = True) -> dict:
        job = jb.get_job(job_id)
        if not job:
            return {"error": "Job not found"}

        milestone = next((m for m in job["milestones"] if m["name"] == milestone_name), None)
        if not milestone:
            return {"error": f"Milestone '{milestone_name}' not found"}
        if milestone["status"] != MilestoneStatus.PENDING.value:
            return {"error": f"Milestone already {milestone['status']}"}

        if not job.get("qbo_customer_id"):
            return self._submit_invoice_approval(
                job, milestone_name, milestone["amount"],
                f"{milestone['label']} — {job['name']}",
                submit_approval,
            )

        invoice = qbo.create_invoice(
            customer_id=job["qbo_customer_id"],
            line_items=[{
                "description": f"{milestone['label']} — {job['name']}",
                "amount": milestone["amount"],
            }],
            due_date=(datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
            memo=f"Milestone billing: {milestone['label']}",
        )

        if invoice:
            jb.mark_milestone_invoiced(milestone["id"], invoice.get("Id"))
            return {"status": "invoiced", "qbo_invoice_id": invoice.get("Id"), "amount": milestone["amount"]}

        return self._submit_invoice_approval(
            job, milestone_name, milestone["amount"],
            f"{milestone['label']} — {job['name']}",
            submit_approval,
        )

    def invoice_final(self, job_id: str, submit_approval: bool = True) -> dict:
        """Final invoice = contract - deposits paid - milestones paid - retainage."""
        job = jb.get_job(job_id)
        if not job:
            return {"error": "Job not found"}

        contract = job["contract_amount"]
        retainage_pct = job["retainage_percent"]
        retainage_amount = contract * (retainage_pct / 100)

        paid_amount = 0.0
        deposit = job.get("deposit")
        if deposit and deposit["status"] == MilestoneStatus.PAID.value:
            paid_amount += deposit["amount"]
        for m in job["milestones"]:
            if m["status"] == MilestoneStatus.PAID.value:
                paid_amount += m["amount"]

        final_amount = contract - paid_amount - retainage_amount
        if final_amount <= 0:
            return {"error": "Nothing remaining to bill on final invoice"}

        description = (
            f"Final Invoice — {job['name']} "
            f"(less ${paid_amount:,.2f} previously billed, "
            f"${retainage_amount:,.2f} retainage held)"
        )

        if not job.get("qbo_customer_id"):
            return self._submit_invoice_approval(job, "final", final_amount, description, submit_approval)

        invoice = qbo.create_invoice(
            customer_id=job["qbo_customer_id"],
            line_items=[{"description": description, "amount": final_amount}],
            due_date=(datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
            memo=f"Final invoice for {job['name']}. Retainage: ${retainage_amount:,.2f}",
        )

        if invoice:
            return {
                "status": "invoiced",
                "qbo_invoice_id": invoice.get("Id"),
                "amount": final_amount,
                "retainage_held": retainage_amount,
            }

        return self._submit_invoice_approval(job, "final", final_amount, description, submit_approval)

    def invoice_retainage(self, job_id: str, submit_approval: bool = True) -> dict:
        job = jb.get_job(job_id)
        if not job:
            return {"error": "Job not found"}

        retainage_amount = job["contract_amount"] * (job["retainage_percent"] / 100)
        description = f"Retainage Release — {job['name']} (punch list complete)"

        if not job.get("qbo_customer_id"):
            return self._submit_invoice_approval(job, "retainage", retainage_amount, description, submit_approval)

        invoice = qbo.create_invoice(
            customer_id=job["qbo_customer_id"],
            line_items=[{"description": description, "amount": retainage_amount}],
            due_date=(datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
            memo=f"Retainage release for {job['name']}",
        )

        if invoice:
            return {"status": "invoiced", "qbo_invoice_id": invoice.get("Id"), "amount": retainage_amount}

        return self._submit_invoice_approval(job, "retainage", retainage_amount, description, submit_approval)

    def check_billing_alerts(self) -> list[dict]:
        """Find jobs where work completion is ahead of billing."""
        jobs = jb.list_jobs(status="active")
        alerts = []
        for job in jobs:
            if job.get("billing_behind"):
                alerts.append({
                    "job_id": job["id"],
                    "job_name": job["name"],
                    "customer": job["customer_name"],
                    "completion_percent": job["completion_percent"],
                    "billed_percent": job["billed_percent"],
                    "gap": job["completion_percent"] - job["billed_percent"],
                    "message": (
                        f"{job['name']}: {job['completion_percent']}% complete "
                        f"but only {job['billed_percent']}% billed"
                    ),
                })
        return alerts

    def get_billing_schedule(self, job_id: str) -> dict | None:
        job = jb.get_job(job_id)
        if not job:
            return None

        retainage = job["contract_amount"] * (job["retainage_percent"] / 100)
        return {
            "job": job,
            "schedule": [
                {"type": "deposit", "label": "Contract Deposit", **job["deposit"]},
                *[{"type": "milestone", **m} for m in job["milestones"]],
                {"type": "final", "label": "Final Invoice (less retainage)", "amount": "calculated_at_close"},
                {"type": "retainage", "label": "Retainage Release", "amount": retainage},
            ],
        }

    def _submit_invoice_approval(
        self, job: dict, billing_type: str, amount: float,
        description: str, submit_approval: bool,
    ) -> dict:
        if not submit_approval:
            return {"status": "pending_qbo", "amount": amount, "description": description}

        result = self.approval_gateway.submit(
            approval_type="invoice",
            title=description,
            description=f"Create QBO invoice for {job['customer_name']}",
            amount=amount,
            payload={
                "job_id": job["id"],
                "billing_type": billing_type,
                "customer_name": job["customer_name"],
                "qbo_customer_id": job.get("qbo_customer_id"),
            },
            agent_name="progress_billing_agent",
        )
        return {"status": "approval_submitted", "approval": result, "amount": amount}
