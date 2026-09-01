import json
import logging
import re
from datetime import datetime, timedelta
from langchain_core.messages import HumanMessage
from src.llm import invoke_with_fallback
from src.tools import billcom_tools as billcom
from src.tools import quickbooks_tools as qbo
from src.agents.approval_gateway_agent import ApprovalGatewayAgent
from src.agents.sub_compliance_agent import SubComplianceAgent
from src.config import AP_AUTO_APPROVE_THRESHOLD, AP_MANAGER_THRESHOLD

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict:
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(text)
    except Exception:
        return {}


class APAgent:
    """Accounts Payable — Bill.com powered bill intake, coding, and payment proposals."""

    def __init__(self):
        self.approval_gateway = ApprovalGatewayAgent()
        self.compliance = SubComplianceAgent()

    def extract_bill_from_text(self, text: str) -> dict:
        """Use Grok to extract bill details from email or document text."""
        prompt = f"""
        Extract vendor bill details from the following text.
        Return a JSON object with:
        {{
            "vendor": "Vendor/company name",
            "amount": 0.00,
            "invoice_number": "Invoice or reference number",
            "invoice_date": "YYYY-MM-DD",
            "due_date": "YYYY-MM-DD or null",
            "description": "Brief description of goods/services",
            "is_subcontractor": false,
            "job_reference": "Job name or number if mentioned, else null"
        }}

        Text:
        {text}
        """
        try:
            response = invoke_with_fallback([HumanMessage(content=prompt)], tier="fast")
            return _extract_json(response.content)
        except Exception as e:
            logger.error(f"Bill extraction failed: {e}")
            return {}

    def process_bill_from_email(self, email: dict) -> dict:
        """Full pipeline: extract bill from email, check compliance, create in Bill.com or submit approval."""
        text = f"Subject: {email.get('subject', '')}\nFrom: {email.get('sender', '')}\n\n{email.get('body', '')}"
        bill_data = self.extract_bill_from_text(text)
        if not bill_data.get("vendor") or not bill_data.get("amount"):
            return {
                "status": "extraction_failed",
                "message": "Could not extract vendor or amount from email",
                "raw": bill_data,
            }
        return self.create_bill(
            vendor_name=bill_data["vendor"],
            amount=float(bill_data["amount"]),
            invoice_number=bill_data.get("invoice_number", f"EMAIL-{email.get('id', 'unknown')[:8]}"),
            invoice_date=bill_data.get("invoice_date", datetime.now().strftime("%Y-%m-%d")),
            due_date=bill_data.get("due_date"),
            description=bill_data.get("description", email.get("subject", "")),
            job_reference=bill_data.get("job_reference"),
            is_subcontractor=bill_data.get("is_subcontractor", False),
        )

    def create_bill(
        self,
        vendor_name: str,
        amount: float,
        invoice_number: str,
        invoice_date: str,
        due_date: str = None,
        description: str = "",
        job_reference: str = None,
        is_subcontractor: bool = False,
        chart_of_account_id: str = None,
    ) -> dict:
        """Create a bill in Bill.com after compliance check. Payment requires human approval."""
        compliance_check = self.compliance.can_pay_vendor(vendor_name)
        if not compliance_check["allowed"]:
            return {
                "status": "blocked",
                "reason": compliance_check["reason"],
                "issues": compliance_check.get("issues", []),
                "vendor": vendor_name,
                "amount": amount,
            }

        if is_subcontractor and not self.compliance.get_vendor(vendor_name):
            self.compliance.register_vendor(vendor_name=vendor_name, is_subcontractor=True)

        approval_tier = self._get_approval_tier(amount)

        if billcom.is_configured():
            vendor = billcom.find_vendor_by_name(vendor_name)
            if not vendor:
                return self._submit_bill_approval(
                    vendor_name, amount, invoice_number, description,
                    job_reference, approval_tier,
                    reason=f"Vendor '{vendor_name}' not found in Bill.com — manual setup required",
                )

            bill = billcom.create_bill(
                vendor_id=vendor.get("id", vendor.get("vendorId")),
                amount=amount,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                due_date=due_date,
                description=description,
                chart_of_account_id=chart_of_account_id,
            )

            if bill:
                bill_id = bill.get("id", bill.get("billId"))
                return self._submit_payment_proposal(
                    vendor_name, amount, invoice_number, bill_id, approval_tier, description
                )

        return self._submit_bill_approval(
            vendor_name, amount, invoice_number, description,
            job_reference, approval_tier,
        )

    def propose_payment_batch(self, bill_ids: list[str] = None) -> dict:
        """Propose a batch of unpaid bills for payment approval."""
        if billcom.is_configured():
            unpaid = billcom.list_unpaid_bills()
        else:
            unpaid = []

        if bill_ids:
            unpaid = [b for b in unpaid if b.get("id") in bill_ids]

        if not unpaid:
            return {"status": "no_bills", "message": "No unpaid bills to propose"}

        total = sum(float(b.get("amount", b.get("totalAmount", 0))) for b in unpaid)
        bill_summary = [
            {
                "id": b.get("id"),
                "vendor": b.get("vendorName", b.get("vendor", {}).get("name", "Unknown")),
                "amount": b.get("amount", b.get("totalAmount")),
                "due_date": b.get("dueDate"),
            }
            for b in unpaid[:20]
        ]

        result = self.approval_gateway.submit(
            approval_type="bill",
            title=f"Payment batch — {len(unpaid)} bill(s), ${total:,.2f}",
            description=f"Approve payment for {len(unpaid)} vendor bills",
            amount=total,
            payload={"bills": bill_summary, "action": "payment_batch"},
            agent_name="ap_agent",
        )
        return {"status": "approval_submitted", "bill_count": len(unpaid), "total": total, "approval": result}

    def get_ap_summary(self) -> dict:
        billcom_summary = billcom.get_ap_summary() if billcom.is_configured() else {"configured": False}
        qbo_bills = qbo.get_unpaid_bills() if qbo._get_access_token() else []
        qbo_unpaid = sum(float(b.get("Balance", 0)) for b in qbo_bills)

        return {
            "billcom": billcom_summary,
            "qbo_unpaid_bills": len(qbo_bills),
            "qbo_unpaid_total": qbo_unpaid,
            "sync_note": (
                "Bill.com and QBO totals should match after sync"
                if billcom_summary.get("configured") else
                "Configure Bill.com credentials to enable AP automation"
            ),
        }

    def list_unpaid_bills(self) -> list[dict]:
        if billcom.is_configured():
            return billcom.list_unpaid_bills()
        return []

    def check_sync_status(self) -> dict:
        """Compare unpaid bill counts between Bill.com and QBO."""
        billcom_bills = billcom.list_unpaid_bills() if billcom.is_configured() else []
        qbo_bills = qbo.get_unpaid_bills()

        return {
            "billcom_unpaid": len(billcom_bills),
            "qbo_unpaid": len(qbo_bills),
            "billcom_total": sum(float(b.get("amount", b.get("totalAmount", 0))) for b in billcom_bills),
            "qbo_total": sum(float(b.get("Balance", 0)) for b in qbo_bills),
            "in_sync": abs(len(billcom_bills) - len(qbo_bills)) <= 2,
            "checked_at": datetime.utcnow().isoformat(),
        }

    def _get_approval_tier(self, amount: float) -> str:
        if amount < AP_AUTO_APPROVE_THRESHOLD:
            return "auto_route"
        if amount < AP_MANAGER_THRESHOLD:
            return "manager"
        return "owner"

    def _submit_bill_approval(
        self, vendor_name, amount, invoice_number, description,
        job_reference, approval_tier, reason=None,
    ) -> dict:
        result = self.approval_gateway.submit(
            approval_type="bill",
            title=f"Bill: {vendor_name} — {invoice_number}",
            description=reason or description,
            amount=amount,
            payload={
                "vendor": vendor_name,
                "invoice_number": invoice_number,
                "job_reference": job_reference,
                "approval_tier": approval_tier,
                "action": "create_bill",
            },
            agent_name="ap_agent",
        )
        return {"status": "approval_submitted", "approval": result, "approval_tier": approval_tier}

    def _submit_payment_proposal(
        self, vendor_name, amount, invoice_number, bill_id, approval_tier, description,
    ) -> dict:
        result = self.approval_gateway.submit(
            approval_type="bill",
            title=f"Pay {vendor_name} — {invoice_number} (${amount:,.2f})",
            description=f"Bill created in Bill.com (ID: {bill_id}). {description}",
            amount=amount,
            payload={
                "vendor": vendor_name,
                "invoice_number": invoice_number,
                "billcom_bill_id": bill_id,
                "approval_tier": approval_tier,
                "action": "approve_payment",
            },
            agent_name="ap_agent",
        )
        return {
            "status": "bill_created",
            "billcom_bill_id": bill_id,
            "approval": result,
            "approval_tier": approval_tier,
            "message": "Bill created in Bill.com. Payment proposal submitted for human approval.",
        }
