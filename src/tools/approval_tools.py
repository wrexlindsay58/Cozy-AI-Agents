import logging
from src.config import (
    GOOGLE_CHAT_SPACE,
    APPROVAL_BASE_URL,
    DEFAULT_APPROVER_EMAIL,
)
from src.db.approval_queue import (
    create_proposal,
    get_proposal_by_token,
    resolve_proposal,
    update_proposal_channels,
    ApprovalStatus,
)
from src.tools.google_chat_tools import send_approval_card, update_approval_card
from src.tools.gmail_approval_tools import send_approval_email

logger = logging.getLogger(__name__)


def submit_for_approval(
    approval_type: str,
    title: str,
    description: str = None,
    amount: float = None,
    currency: str = "USD",
    payload: dict = None,
    approver_email: str = None,
    agent_name: str = None,
) -> dict:
    """Create a proposal and dispatch to both Google Chat and Gmail."""
    approver = approver_email or DEFAULT_APPROVER_EMAIL
    proposal = create_proposal(
        approval_type=approval_type,
        title=title,
        description=description,
        amount=amount,
        currency=currency,
        payload=payload,
        approver_email=approver,
        agent_name=agent_name,
    )

    approval_url = f"{APPROVAL_BASE_URL}/approve/{proposal['approval_token']}"

    chat_message_name = None
    gmail_message_id = None

    try:
        chat_message_name = send_approval_card(proposal, approval_url)
    except Exception as e:
        logger.error(f"Failed to send Chat approval card: {e}")

    try:
        gmail_message_id = send_approval_email(proposal, approval_url, approver)
    except Exception as e:
        logger.error(f"Failed to send Gmail approval email: {e}")

    if chat_message_name or gmail_message_id:
        update_proposal_channels(
            proposal["id"],
            chat_message_name=chat_message_name,
            gmail_message_id=gmail_message_id,
        )

    proposal["approval_url"] = approval_url
    return proposal


def approve(token: str, approved_by: str, via: str = "web") -> dict:
    """Approve a proposal. First action wins — idempotent."""
    existing = get_proposal_by_token(token)
    if not existing:
        return {"error": "Proposal not found"}
    if existing["status"] != ApprovalStatus.PENDING.value:
        return existing

    result = resolve_proposal(token, ApprovalStatus.APPROVED.value, approved_by, via)
    _sync_channels(result)
    _execute_post_approval_action(result, approved_by)
    return result


def reject(token: str, rejected_by: str, via: str = "web") -> dict:
    """Reject a proposal. First action wins — idempotent."""
    existing = get_proposal_by_token(token)
    if not existing:
        return {"error": "Proposal not found"}
    if existing["status"] != ApprovalStatus.PENDING.value:
        return existing

    result = resolve_proposal(token, ApprovalStatus.REJECTED.value, rejected_by, via)
    _sync_channels(result)
    _execute_post_rejection_action(result)
    return result


def _execute_post_approval_action(proposal: dict, approved_by: str):
    """Run downstream actions after an approval is resolved."""
    if not proposal or proposal.get("status") != ApprovalStatus.APPROVED.value:
        return

    payload = proposal.get("payload") or {}
    action = payload.get("action")

    if action == "approve_change_order":
        co_id = payload.get("change_order_id")
        if co_id:
            from src.agents.change_order_agent import ChangeOrderAgent
            ChangeOrderAgent().approve(co_id, approved_by=approved_by)

    if action == "approve_commission_payout":
        commission_ids = payload.get("commission_ids", [])
        if commission_ids:
            from src.agents.commission_agent import CommissionAgent
            CommissionAgent().approve_payout(commission_ids)

    if action == "approve_payroll_run":
        run_id = payload.get("payroll_run_id")
        if run_id:
            from src.agents.payroll_agent import PayrollAgent
            PayrollAgent().approve_payroll_run(run_id, approved_by)


def _execute_post_rejection_action(proposal: dict):
    """Run downstream actions after a rejection is resolved."""
    if not proposal or proposal.get("status") != ApprovalStatus.REJECTED.value:
        return

    payload = proposal.get("payload") or {}
    action = payload.get("action")

    if action == "approve_change_order":
        co_id = payload.get("change_order_id")
        if co_id:
            from src.agents.change_order_agent import ChangeOrderAgent
            ChangeOrderAgent().reject(co_id)

    if action == "approve_commission_payout":
        commission_ids = payload.get("commission_ids", [])
        if commission_ids:
            from src.db import commissions as comm_db
            from src.db.commissions import CommissionStatus
            for cid in commission_ids:
                comm_db.update_commission_status(cid, CommissionStatus.ACCRUED.value)

    if action == "approve_payroll_run":
        run_id = payload.get("payroll_run_id")
        if run_id:
            from src.db import payroll as payroll_db
            from src.db.payroll import PayrollRunStatus
            payroll_db.update_payroll_run_status(run_id, PayrollRunStatus.REJECTED.value)


def _sync_channels(proposal: dict):
    """Update the channel that wasn't used to show resolution status."""
    if not proposal:
        return
    status_label = proposal["status"].upper()
    via = proposal.get("approved_via", "web")
    by = proposal.get("approved_by", "Unknown")
    message = f"{status_label} by {by} via {via}"

    try:
        if proposal.get("chat_message_name"):
            update_approval_card(proposal, message)
    except Exception as e:
        logger.error(f"Failed to update Chat card: {e}")
