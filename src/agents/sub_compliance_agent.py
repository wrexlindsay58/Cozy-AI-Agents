import logging
from datetime import datetime, timedelta
from src.db import sub_compliance as sc
from src.agents.approval_gateway_agent import ApprovalGatewayAgent

logger = logging.getLogger(__name__)


class SubComplianceAgent:
    """Track subcontractor COI, W-9, and lien waiver compliance."""

    def register_vendor(self, **kwargs) -> dict:
        return sc.register_vendor(**kwargs)

    def get_vendor(self, vendor_name: str) -> dict | None:
        return sc.get_vendor(vendor_name)

    def list_vendors(self, is_subcontractor: bool = None) -> list[dict]:
        return sc.list_vendors(is_subcontractor)

    def update_coi(self, vendor_name: str, coi_expiration: str, document_url: str = None) -> dict:
        result = sc.update_coi(vendor_name, coi_expiration, document_url)
        if not result:
            return {"error": f"Vendor '{vendor_name}' not found"}
        return result

    def check_compliance(self, vendor_name: str) -> dict:
        return sc.check_compliance(vendor_name)

    def list_expiring_coi(self, within_days: int = 30) -> list[dict]:
        return sc.list_expiring_coi(within_days)

    def list_non_compliant(self) -> list[dict]:
        return sc.list_non_compliant()

    def get_dashboard(self) -> dict:
        subs = sc.list_vendors(is_subcontractor=True)
        expiring = sc.list_expiring_coi(30)
        non_compliant = sc.list_non_compliant()
        return {
            "total_subcontractors": len(subs),
            "compliant_count": len([s for s in subs if s["compliant"]]),
            "non_compliant_count": len(non_compliant),
            "expiring_within_30_days": len(expiring),
            "non_compliant": non_compliant,
            "expiring_coi": expiring,
        }

    def can_pay_vendor(self, vendor_name: str) -> dict:
        """Check if AP Agent is allowed to process a bill for this vendor."""
        check = sc.check_compliance(vendor_name)
        if check.get("is_subcontractor") and not check.get("compliant", True):
            return {
                "allowed": False,
                "reason": check.get("message"),
                "issues": check.get("issues", []),
            }
        return {"allowed": True, "reason": "Compliant or not a subcontractor"}
