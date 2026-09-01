import logging
from src.config import GOOGLE_CHAT_SPACE
from src.tools.google_auth import get_chat_service

logger = logging.getLogger(__name__)


def _format_amount(proposal: dict) -> str:
    amount = proposal.get("amount")
    currency = proposal.get("currency", "USD")
    if amount is not None:
        return f"${amount:,.2f} {currency}"
    return "N/A"


def build_approval_card(proposal: dict, approval_url: str) -> dict:
    amount_str = _format_amount(proposal)
    return {
        "cardsV2": [{
            "cardId": proposal["id"],
            "card": {
                "header": {
                    "title": f"Approval Required: {proposal['title']}",
                    "subtitle": f"{proposal['approval_type'].replace('_', ' ').title()} — {amount_str}",
                },
                "sections": [{
                    "widgets": [
                        {"textParagraph": {"text": proposal.get("description") or "No description provided."}},
                        {
                            "buttonList": {
                                "buttons": [
                                    {
                                        "text": "Approve",
                                        "onClick": {
                                            "action": {
                                                "function": "approve_proposal",
                                                "parameters": [
                                                    {"key": "token", "value": proposal["approval_token"]},
                                                    {"key": "action", "value": "approve"},
                                                ],
                                            },
                                        },
                                    },
                                    {
                                        "text": "Reject",
                                        "onClick": {
                                            "action": {
                                                "function": "reject_proposal",
                                                "parameters": [
                                                    {"key": "token", "value": proposal["approval_token"]},
                                                    {"key": "action", "value": "reject"},
                                                ],
                                            },
                                        },
                                    },
                                    {
                                        "text": "View Details",
                                        "onClick": {"openLink": {"url": approval_url}},
                                    },
                                ],
                            },
                        },
                    ],
                }],
            },
        }],
    }


def build_resolved_card(proposal: dict, resolution_message: str) -> dict:
    amount_str = _format_amount(proposal)
    status = proposal.get("status", "resolved").upper()
    return {
        "cardsV2": [{
            "cardId": proposal["id"],
            "card": {
                "header": {
                    "title": f"{status}: {proposal['title']}",
                    "subtitle": f"{amount_str}",
                },
                "sections": [{
                    "widgets": [
                        {"textParagraph": {"text": resolution_message}},
                    ],
                }],
            },
        }],
    }


def send_approval_card(proposal: dict, approval_url: str) -> str | None:
    if not GOOGLE_CHAT_SPACE:
        logger.warning("GOOGLE_CHAT_SPACE not configured — skipping Chat card")
        return None

    service = get_chat_service()
    card = build_approval_card(proposal, approval_url)
    result = service.spaces().messages().create(
        parent=GOOGLE_CHAT_SPACE,
        body=card,
    ).execute()
    return result.get("name")


def update_approval_card(proposal: dict, resolution_message: str):
    if not proposal.get("chat_message_name"):
        return

    service = get_chat_service()
    card = build_resolved_card(proposal, resolution_message)
    service.spaces().messages().update(
        name=proposal["chat_message_name"],
        body=card,
    ).execute()


def send_text_message(text: str) -> str | None:
    """Send a plain-text message to the configured Google Chat space."""
    if not GOOGLE_CHAT_SPACE:
        logger.warning("GOOGLE_CHAT_SPACE not configured — skipping Chat message")
        return None

    service = get_chat_service()
    result = service.spaces().messages().create(
        parent=GOOGLE_CHAT_SPACE,
        body={"text": text},
    ).execute()
    return result.get("name")


def send_dashboard_card(title: str, sections: list[dict]) -> str | None:
    """Send a formatted dashboard card to Google Chat."""
    if not GOOGLE_CHAT_SPACE:
        logger.warning("GOOGLE_CHAT_SPACE not configured — skipping dashboard")
        return None

    widgets = []
    for section in sections:
        widgets.append({"textParagraph": {"text": section.get("text", "")}})
        if section.get("divider"):
            widgets.append({"divider": {}})

    card = {
        "cardsV2": [{
            "cardId": title.replace(" ", "-").lower()[:50],
            "card": {
                "header": {"title": title, "subtitle": "Finance Agent Dashboard"},
                "sections": [{"widgets": widgets}],
            },
        }],
    }

    service = get_chat_service()
    result = service.spaces().messages().create(
        parent=GOOGLE_CHAT_SPACE,
        body=card,
    ).execute()
    return result.get("name")
