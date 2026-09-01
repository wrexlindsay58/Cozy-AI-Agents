import base64
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from src.tools.google_auth import get_gmail_service

logger = logging.getLogger(__name__)


def _build_approval_email_html(proposal: dict, approval_url: str) -> str:
    amount = proposal.get("amount")
    amount_str = f"${amount:,.2f} {proposal.get('currency', 'USD')}" if amount else "N/A"
    description = proposal.get("description") or "No additional details."

    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2>Approval Required</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="padding: 8px; font-weight: bold;">Type</td>
                <td style="padding: 8px;">{proposal['approval_type'].replace('_', ' ').title()}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Title</td>
                <td style="padding: 8px;">{proposal['title']}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Amount</td>
                <td style="padding: 8px;">{amount_str}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Agent</td>
                <td style="padding: 8px;">{proposal.get('agent_name', 'N/A')}</td></tr>
        </table>
        <p style="margin-top: 16px;">{description}</p>
        <p style="margin-top: 24px;">
            <a href="{approval_url}"
               style="background-color: #1a73e8; color: white; padding: 12px 24px;
                      text-decoration: none; border-radius: 4px; margin-right: 8px;">
                Review &amp; Approve
            </a>
        </p>
        <p style="color: #666; font-size: 12px; margin-top: 24px;">
            You can also approve via Google Chat. First action wins.
        </p>
    </body>
    </html>
    """


def send_approval_email(proposal: dict, approval_url: str, recipient: str) -> str | None:
    if not recipient:
        logger.warning("No approver email — skipping Gmail approval")
        return None

    service = get_gmail_service()
    msg = MIMEMultipart("alternative")
    msg["to"] = recipient
    msg["subject"] = f"[Approval Required] {proposal['title']}"

    amount = proposal.get("amount")
    amount_str = f"${amount:,.2f}" if amount else "N/A"
    plain = (
        f"Approval Required: {proposal['title']}\n"
        f"Type: {proposal['approval_type']}\n"
        f"Amount: {amount_str}\n\n"
        f"Review and approve: {approval_url}\n\n"
        f"You can also approve via Google Chat. First action wins."
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_build_approval_email_html(proposal, approval_url), "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()
    return result.get("id")
