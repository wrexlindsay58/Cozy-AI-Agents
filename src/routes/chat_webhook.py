import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from src.agents.approval_gateway_agent import ApprovalGatewayAgent

logger = logging.getLogger(__name__)
router = APIRouter()
gateway = ApprovalGatewayAgent()


@router.post("/chat/webhook")
async def chat_webhook(request: Request):
    """Handle Google Chat events (MESSAGE, CARD_CLICKED)."""
    event = await request.json()
    event_type = event.get("type", "")

    if event_type == "MESSAGE":
        return JSONResponse({"text": "Finance Agent is online. Approvals will appear here automatically."})

    if event_type == "CARD_CLICKED":
        action = event.get("action", {})
        method = action.get("actionMethodName", action.get("function", ""))
        parameters = action.get("parameters", [])
        user = event.get("user", {})
        user_email = user.get("email", "unknown@chat.user")

        result = gateway.handle_chat_action(method, parameters, user_email)

        if result.get("error"):
            return JSONResponse({"text": f"Error: {result['error']}"})

        status = result.get("status", "processed")
        return JSONResponse({
            "actionResponse": {
                "type": "UPDATE_MESSAGE",
            },
            "text": f"Proposal {status} by {user_email} via Google Chat.",
        })

    return JSONResponse({})
