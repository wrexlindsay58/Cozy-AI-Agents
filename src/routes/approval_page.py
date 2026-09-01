import logging
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from src.db.approval_queue import get_proposal_by_token, ApprovalStatus
from src.tools.approval_tools import approve, reject

logger = logging.getLogger(__name__)
router = APIRouter()


def _format_amount(proposal: dict) -> str:
    amount = proposal.get("amount")
    if amount is not None:
        return f"${amount:,.2f} {proposal.get('currency', 'USD')}"
    return "N/A"


def _render_page(proposal: dict, message: str = None, error: str = None) -> str:
    status = proposal.get("status", "pending")
    is_pending = status == ApprovalStatus.PENDING.value
    amount_str = _format_amount(proposal)
    payload = proposal.get("payload", {})

    status_color = {"approved": "#34a853", "rejected": "#ea4335", "pending": "#f9ab00"}.get(status, "#666")

    action_buttons = ""
    if is_pending:
        action_buttons = f"""
        <form method="post" action="/approve/{proposal['approval_token']}/action" style="display: inline;">
            <input type="hidden" name="action" value="approve">
            <input type="hidden" name="approved_by" value="approver">
            <button type="submit" style="background: #34a853; color: white; padding: 12px 32px;
                    border: none; border-radius: 4px; font-size: 16px; cursor: pointer; margin-right: 8px;">
                Approve
            </button>
        </form>
        <form method="post" action="/approve/{proposal['approval_token']}/action" style="display: inline;">
            <input type="hidden" name="action" value="reject">
            <input type="hidden" name="approved_by" value="approver">
            <button type="submit" style="background: #ea4335; color: white; padding: 12px 32px;
                    border: none; border-radius: 4px; font-size: 16px; cursor: pointer;">
                Reject
            </button>
        </form>
        """

    detail_rows = ""
    for key, value in payload.items():
        detail_rows += f'<tr><td style="padding: 8px; font-weight: bold;">{key}</td><td style="padding: 8px;">{value}</td></tr>'

    msg_html = ""
    if message:
        msg_html = f'<div style="background: #e8f5e9; padding: 12px; border-radius: 4px; margin-bottom: 16px;">{message}</div>'
    if error:
        msg_html = f'<div style="background: #fce8e6; padding: 12px; border-radius: 4px; margin-bottom: 16px;">{error}</div>'

    resolved_info = ""
    if not is_pending:
        resolved_info = f"""
        <p style="color: {status_color}; font-weight: bold;">
            {status.upper()} by {proposal.get('approved_by', 'Unknown')}
            via {proposal.get('approved_via', 'web')}
        </p>
        """

    return f"""
    <!DOCTYPE html>
    <html><head><title>Approval — {proposal['title']}</title></head>
    <body style="font-family: Arial, sans-serif; max-width: 700px; margin: 40px auto; padding: 0 20px;">
        <h1>Approval Request</h1>
        {msg_html}
        <div style="border: 1px solid #ddd; border-radius: 8px; padding: 24px;">
            <h2 style="margin-top: 0;">{proposal['title']}</h2>
            <p style="color: {status_color}; font-weight: bold; text-transform: uppercase;">{status}</p>
            {resolved_info}
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 8px; font-weight: bold;">Type</td>
                    <td style="padding: 8px;">{proposal['approval_type'].replace('_', ' ').title()}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Amount</td>
                    <td style="padding: 8px;">{amount_str}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Agent</td>
                    <td style="padding: 8px;">{proposal.get('agent_name', 'N/A')}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Description</td>
                    <td style="padding: 8px;">{proposal.get('description', 'N/A')}</td></tr>
                {detail_rows}
            </table>
            <div style="margin-top: 24px;">{action_buttons}</div>
        </div>
        <p style="color: #666; font-size: 12px; margin-top: 24px;">
            You can also approve via Google Chat. First action wins.
        </p>
    </body></html>
    """


@router.get("/approve/{token}", response_class=HTMLResponse)
def view_approval(token: str):
    proposal = get_proposal_by_token(token)
    if not proposal:
        return HTMLResponse("<h1>Approval not found</h1>", status_code=404)
    return HTMLResponse(_render_page(proposal))


@router.post("/approve/{token}/action")
def handle_approval_action(
    token: str,
    action: str = Form(...),
    approved_by: str = Form("approver"),
):
    if action == "approve":
        result = approve(token, approved_by, via="gmail")
    elif action == "reject":
        result = reject(token, approved_by, via="gmail")
    else:
        return HTMLResponse("<h1>Invalid action</h1>", status_code=400)

    if result.get("error"):
        return HTMLResponse(f"<h1>{result['error']}</h1>", status_code=404)

    status_msg = f"Successfully {result['status']}."
    return HTMLResponse(_render_page(result, message=status_msg))
