import json
import logging
import re
from langchain_core.messages import HumanMessage
from src.llm import invoke_with_fallback
from src.db import job_billing as jb
from src.db import change_orders as co_db
from src.db.change_orders import ChangeOrderStatus
from src.agents.approval_gateway_agent import ApprovalGatewayAgent
from src.agents.job_costing_agent import JobCostingAgent

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict:
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(text)
    except Exception:
        return {}


class ChangeOrderAgent:
    """Scope change intake, margin impact analysis, and customer approval workflow."""

    def __init__(self):
        self.approval_gateway = ApprovalGatewayAgent()
        self.job_costing = JobCostingAgent()

    def create_change_order(
        self,
        job_id: str,
        title: str,
        description: str,
        additional_revenue: float,
        additional_cost: float,
        submit_approval: bool = True,
    ) -> dict:
        job = jb.get_job(job_id)
        if not job:
            return {"error": "Job not found"}

        co = co_db.create_change_order(
            job_id=job_id,
            title=title,
            description=description,
            additional_revenue=additional_revenue,
            additional_cost=additional_cost,
        )

        impact = self._analyze_margin_impact(job, co)
        result = {**co, "margin_analysis": impact}

        if submit_approval:
            approval = self.approval_gateway.submit(
                approval_type="change_order",
                title=f"Change Order: {title} — {job['name']}",
                description=(
                    f"Additional revenue: ${additional_revenue:,.2f}\n"
                    f"Additional cost: ${additional_cost:,.2f}\n"
                    f"Margin impact: ${co['margin_impact']:,.2f} ({co['margin_percent']}%)"
                ),
                amount=additional_revenue,
                payload={
                    "change_order_id": co["id"],
                    "job_id": job_id,
                    "additional_revenue": additional_revenue,
                    "additional_cost": additional_cost,
                    "action": "approve_change_order",
                },
                agent_name="change_order_agent",
            )
            co_db.update_status(co["id"], ChangeOrderStatus.PENDING_APPROVAL.value)
            result["approval"] = approval
            result["status"] = ChangeOrderStatus.PENDING_APPROVAL.value

        return result

    def extract_from_text(self, text: str, job_id: str = None) -> dict:
        """Use Grok to extract change order details from email or field report."""
        prompt = f"""
        Extract change order details from the following text.
        Return a JSON object with:
        {{
            "title": "Brief title of the change",
            "description": "Full description of scope change",
            "additional_revenue": 0.00,
            "additional_cost": 0.00,
            "job_reference": "Job name or number if mentioned"
        }}

        Text:
        {text}
        """
        try:
            response = invoke_with_fallback([HumanMessage(content=prompt)], tier="fast")
            data = _extract_json(response.content)
            if job_id and data.get("additional_revenue"):
                return self.create_change_order(
                    job_id=job_id,
                    title=data.get("title", "Change Order"),
                    description=data.get("description", ""),
                    additional_revenue=float(data["additional_revenue"]),
                    additional_cost=float(data.get("additional_cost", 0)),
                )
            return data
        except Exception as e:
            logger.error(f"Change order extraction failed: {e}")
            return {"error": str(e)}

    def intake_from_email(self, email: dict, job_id: str = None) -> dict:
        text = f"Subject: {email.get('subject', '')}\n\n{email.get('body', '')}"
        return self.extract_from_text(text, job_id)

    def approve(self, co_id: str, approved_by: str = "internal") -> dict:
        co = co_db.get_change_order(co_id)
        if not co:
            return {"error": "Change order not found"}

        co_db.update_status(co_id, ChangeOrderStatus.APPROVED.value)
        applied = co_db.apply_approved_change_order(co_id)
        return {
            "status": "approved",
            "change_order": applied,
            "approved_by": approved_by,
            "message": "Change order applied to job contract and budget",
        }

    def reject(self, co_id: str) -> dict:
        result = co_db.update_status(co_id, ChangeOrderStatus.REJECTED.value)
        if not result:
            return {"error": "Change order not found"}
        return {"status": "rejected", "change_order": result}

    def mark_customer_approved(self, co_id: str) -> dict:
        result = co_db.update_status(co_id, ChangeOrderStatus.APPROVED.value, customer_approved=True)
        if not result:
            return {"error": "Change order not found"}
        applied = co_db.apply_approved_change_order(co_id)
        return {"status": "customer_approved", "change_order": applied}

    def get_change_order(self, co_id: str) -> dict | None:
        co = co_db.get_change_order(co_id)
        if not co:
            return None
        job = jb.get_job(co["job_id"])
        impact = self._analyze_margin_impact(job, co) if job else {}
        return {**co, "margin_analysis": impact}

    def list_for_job(self, job_id: str) -> list[dict]:
        return co_db.list_change_orders(job_id=job_id)

    def list_unsigned(self, job_id: str = None) -> list[dict]:
        return co_db.list_unsigned(job_id)

    def get_risk_report(self) -> dict:
        """Unsigned change orders that are eroding job margins."""
        unsigned = co_db.list_unsigned()
        total_at_risk_revenue = sum(co["additional_revenue"] for co in unsigned)
        total_at_risk_cost = sum(co["additional_cost"] for co in unsigned)
        low_margin = [co for co in unsigned if co.get("margin_percent", 100) < 20]

        return {
            "unsigned_count": len(unsigned),
            "low_margin_count": len(low_margin),
            "total_at_risk_revenue": total_at_risk_revenue,
            "total_at_risk_cost": total_at_risk_cost,
            "unsigned_orders": unsigned,
            "low_margin_orders": low_margin,
        }

    def draft_customer_email(self, co_id: str) -> dict:
        """Draft change order approval email for customer (never auto-send)."""
        co = co_db.get_change_order(co_id)
        if not co:
            return {"error": "Change order not found"}
        job = jb.get_job(co["job_id"])
        customer = job["customer_name"] if job else "Valued Customer"

        body = (
            f"Dear {customer},\n\n"
            f"We are writing regarding a change to the scope of work on {job['name'] if job else 'your project'}.\n\n"
            f"**Change Order: {co['title']}**\n"
            f"{co['description']}\n\n"
            f"Additional cost: ${co['additional_revenue']:,.2f}\n"
            f"This includes all labor and materials for the described work.\n\n"
            f"Please reply to approve this change order before we proceed with the additional work.\n\n"
            f"Thank you,\n"
            f"Project Team"
        )
        return {
            "to": job.get("customer_email") if job else None,
            "subject": f"Change Order Approval Required — {co['title']}",
            "body": body,
            "change_order_id": co_id,
            "status": "draft_ready",
        }

    def _analyze_margin_impact(self, job: dict, co: dict) -> dict:
        if not job:
            return {}
        pnl = self.job_costing.get_job_pnl(job["id"])
        current_margin = pnl["margin_percent"] if pnl else 0

        new_revenue = job["contract_amount"] + co["additional_revenue"]
        current_costs = pnl["actuals"]["total"] if pnl else 0
        new_costs = current_costs + co["additional_cost"]
        new_margin = ((new_revenue - new_costs) / new_revenue * 100) if new_revenue > 0 else 0

        return {
            "current_margin_percent": current_margin,
            "projected_margin_percent": round(new_margin, 1),
            "margin_change": round(new_margin - current_margin, 1),
            "current_contract": job["contract_amount"],
            "new_contract": new_revenue,
            "acceptable": new_margin >= 15,
        }
