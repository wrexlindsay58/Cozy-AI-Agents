import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from src.agents.finance_orchestrator import FinanceOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter()
orchestrator = FinanceOrchestrator()


@router.post("/webhooks/billcom")
async def billcom_webhook(request: Request):
    """Handle Bill.com webhook events (bill approved, payment completed, etc.)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    result = orchestrator.handle_billcom_webhook(payload)
    return JSONResponse(result)


@router.post("/webhooks/qbo")
async def qbo_webhook(request: Request):
    """Handle QuickBooks Online webhook events."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    event_notifications = payload.get("eventNotifications", [payload])
    results = []
    for notification in event_notifications:
        entities = notification.get("dataChangeEvent", {}).get("entities", [notification])
        for entity in entities:
            results.append(orchestrator.handle_qbo_webhook(entity))

    if len(results) == 1:
        return JSONResponse(results[0])
    return JSONResponse({"processed": len(results), "results": results})


@router.post("/webhooks/bamboohr")
async def bamboohr_webhook(request: Request):
    """Handle BambooHR webhook events (payroll complete, time entry, etc.)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    result = orchestrator.handle_bamboohr_webhook(payload)
    return JSONResponse(result)


@router.get("/webhooks/health")
def webhooks_health():
    return {"status": "ok", "endpoints": ["/webhooks/billcom", "/webhooks/qbo", "/webhooks/bamboohr"]}
