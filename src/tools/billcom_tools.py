import logging
from datetime import datetime, timedelta
from typing import Optional
import requests
from src.config import (
    BILLCOM_DEV_KEY,
    BILLCOM_ORG_ID,
    BILLCOM_USERNAME,
    BILLCOM_PASSWORD,
    BILLCOM_ENVIRONMENT,
)

logger = logging.getLogger(__name__)

BILLCOM_BASE_URL = (
    "https://gateway.stage.bill.com/connect"
    if BILLCOM_ENVIRONMENT == "sandbox"
    else "https://api.bill.com"
)

_session_id: Optional[str] = None
_session_expires: Optional[datetime] = None


def _login() -> Optional[str]:
    global _session_id, _session_expires

    if _session_id and _session_expires and datetime.utcnow() < _session_expires:
        return _session_id

    if not all([BILLCOM_DEV_KEY, BILLCOM_ORG_ID, BILLCOM_USERNAME, BILLCOM_PASSWORD]):
        logger.warning("Bill.com credentials not configured")
        return None

    try:
        resp = requests.post(
            f"{BILLCOM_BASE_URL}/v3/login",
            json={
                "username": BILLCOM_USERNAME,
                "password": BILLCOM_PASSWORD,
                "organizationId": BILLCOM_ORG_ID,
                "devKey": BILLCOM_DEV_KEY,
            },
            headers={"content-type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        _session_id = data.get("sessionId")
        _session_expires = datetime.utcnow() + timedelta(hours=47)
        return _session_id
    except Exception as e:
        logger.error(f"Bill.com login failed: {e}")
        return None


def _headers() -> dict:
    session = _login()
    if not session:
        return {}
    return {
        "content-type": "application/json",
        "devKey": BILLCOM_DEV_KEY,
        "sessionId": session,
    }


def _request(method: str, endpoint: str, **kwargs) -> dict | list | None:
    if not _headers():
        return None

    url = f"{BILLCOM_BASE_URL}{endpoint}"
    try:
        resp = requests.request(method, url, headers=_headers(), timeout=30, **kwargs)
        if resp.status_code == 401:
            global _session_id
            _session_id = None
            if not _headers():
                return None
            resp = requests.request(method, url, headers=_headers(), timeout=30, **kwargs)
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return {}
    except Exception as e:
        logger.error(f"Bill.com API error ({endpoint}): {e}")
        return None


def is_configured() -> bool:
    return all([BILLCOM_DEV_KEY, BILLCOM_ORG_ID, BILLCOM_USERNAME, BILLCOM_PASSWORD])


def list_vendors(max_results: int = 100) -> list[dict]:
    result = _request("GET", f"/v3/vendors?max={max_results}")
    if not result:
        return []
    return result if isinstance(result, list) else result.get("results", result.get("vendors", []))


def find_vendor_by_name(name: str) -> dict | None:
    vendors = list_vendors()
    name_lower = name.lower()
    for v in vendors:
        vendor_name = v.get("name", v.get("companyName", "")).lower()
        if name_lower in vendor_name or vendor_name in name_lower:
            return v
    return None


def list_bills(payment_status: str = None, max_results: int = 100) -> list[dict]:
    endpoint = f"/v3/bills?max={max_results}"
    if payment_status:
        endpoint += f"&filters=paymentStatus:eq:{payment_status}"
    result = _request("GET", endpoint)
    if not result:
        return []
    return result if isinstance(result, list) else result.get("results", result.get("bills", []))


def get_bill(bill_id: str) -> dict | None:
    return _request("GET", f"/v3/bills/{bill_id}")


def create_bill(
    vendor_id: str,
    amount: float,
    invoice_number: str,
    invoice_date: str,
    due_date: str = None,
    description: str = "",
    chart_of_account_id: str = None,
    job_id: str = None,
) -> dict | None:
    """Create a bill in Bill.com. Does NOT execute payment."""
    line_item = {
        "amount": amount,
        "description": description or f"Invoice {invoice_number}",
    }
    if chart_of_account_id:
        line_item["classifications"] = {"chartOfAccountId": chart_of_account_id}

    body = {
        "vendorId": vendor_id,
        "dueDate": due_date or invoice_date,
        "invoice": {
            "invoiceNumber": invoice_number,
            "invoiceDate": invoice_date,
        },
        "billLineItems": [line_item],
    }
    if job_id:
        body["billLineItems"][0].setdefault("classifications", {})["jobId"] = job_id

    result = _request("POST", "/v3/bills", json=body)
    if isinstance(result, dict):
        return result.get("bill", result)
    return result


def list_unpaid_bills() -> list[dict]:
    return list_bills(payment_status="UNPAID")


def get_ap_summary() -> dict:
    bills = list_bills(max_results=200)
    unpaid = [b for b in bills if b.get("paymentStatus") in ("UNPAID", "PARTIAL", None)]
    total_unpaid = sum(float(b.get("amount", b.get("totalAmount", 0))) for b in unpaid)
    return {
        "total_bills": len(bills),
        "unpaid_count": len(unpaid),
        "total_unpaid": total_unpaid,
        "configured": is_configured(),
    }
