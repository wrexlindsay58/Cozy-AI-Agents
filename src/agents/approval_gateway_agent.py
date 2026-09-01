import logging
from src.tools import approval_tools
from src.db.approval_queue import list_pending_proposals, get_proposal_by_id

logger = logging.getLogger(__name__)


class ApprovalGatewayAgent:
    """Cross-cutting agent that routes all approval proposals through dual-channel delivery."""

    def submit(
        self,
        approval_type: str,
        title: str,
        description: str = None,
        amount: float = None,
        currency: str = "USD",
        payload: dict = None,
        approver_email: str = None,
        agent_name: str = None,
    ) -> dict:
        logger.info(f"Submitting approval: {title} ({approval_type})")
        return approval_tools.submit_for_approval(
            approval_type=approval_type,
            title=title,
            description=description,
            amount=amount,
            currency=currency,
            payload=payload,
            approver_email=approver_email,
            agent_name=agent_name,
        )

    def approve(self, token: str, approved_by: str, via: str = "web") -> dict:
        return approval_tools.approve(token, approved_by, via)

    def reject(self, token: str, rejected_by: str, via: str = "web") -> dict:
        return approval_tools.reject(token, rejected_by, via)

    def get_pending(self, approver_email: str = None) -> list[dict]:
        return list_pending_proposals(approver_email)

    def get_proposal(self, proposal_id: str) -> dict | None:
        return get_proposal_by_id(proposal_id)

    def handle_chat_action(self, action_method: str, parameters: list[dict], user_email: str) -> dict:
        """Handle CARD_CLICKED events from Google Chat."""
        params = {p["key"]: p["value"] for p in parameters}
        token = params.get("token")
        action = params.get("action")

        if not token:
            return {"error": "Missing approval token"}

        if action == "approve" or action_method == "approve_proposal":
            return self.approve(token, user_email, via="chat")
        elif action == "reject" or action_method == "reject_proposal":
            return self.reject(token, user_email, via="chat")

        return {"error": f"Unknown action: {action}"}
