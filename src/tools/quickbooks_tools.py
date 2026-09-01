import logging
import requests
from src.config import (
    QUICKBOOKS_CLIENT_ID,
    QUICKBOOKS_CLIENT_SECRET,
    QUICKBOOKS_REALM_ID,
    QUICKBOOKS_REFRESH_TOKEN,
    QUICKBOOKS_ENVIRONMENT,
)

logger = logging.getLogger(__name__)

QBO_BASE_URL = (
    "https://sandbox-quickbooks.api.intuit.com"
    if QUICKBOOKS_ENVIRONMENT == "sandbox"
    else "https://quickbooks.api.intuit.com"
)
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

_access_token = None


def _get_access_token() -> str | None:
    global _access_token
    if not all([QUICKBOOKS_CLIENT_ID, QUICKBOOKS_CLIENT_SECRET, QUICKBOOKS_REFRESH_TOKEN]):
        logger.warning("QuickBooks credentials not configured")
        return None

    try:
        resp = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": QUICKBOOKS_REFRESH_TOKEN,
        }, auth=(QUICKBOOKS_CLIENT_ID, QUICKBOOKS_CLIENT_SECRET), timeout=30)
        resp.raise_for_status()
        _access_token = resp.json()["access_token"]
        return _access_token
    except Exception as e:
        logger.error(f"Failed to refresh QBO token: {e}")
        return None


def _qbo_request(method: str, endpoint: str, **kwargs) -> dict | None:
    token = _get_access_token()
    if not token or not QUICKBOOKS_REALM_ID:
        return None

    url = f"{QBO_BASE_URL}/v3/company/{QUICKBOOKS_REALM_ID}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"QBO API error ({endpoint}): {e}")
        return None


def get_company_info() -> dict | None:
    return _qbo_request("GET", "companyinfo/" + (QUICKBOOKS_REALM_ID or ""))


def query(sql: str) -> list[dict]:
    """Run a QBO SQL-like query. E.g. \"SELECT * FROM Invoice WHERE Balance > '0'\" """
    result = _qbo_request("GET", "query", params={"query": sql, "minorversion": "65"})
    if not result:
        return []
    query_response = result.get("QueryResponse", {})
    for key in query_response:
        if key not in ("startPosition", "maxResults", "totalCount"):
            return query_response[key]
    return []


def get_accounts() -> list[dict]:
    return query("SELECT * FROM Account MAXRESULTS 1000")


def get_open_invoices() -> list[dict]:
    return query("SELECT * FROM Invoice WHERE Balance > '0' MAXRESULTS 100")


def get_unpaid_bills() -> list[dict]:
    return query("SELECT * FROM Bill WHERE Balance > '0' MAXRESULTS 100")


def get_bank_transactions(account_id: str, start_date: str, end_date: str) -> list[dict]:
    return query(
        f"SELECT * FROM Purchase WHERE TxnDate >= '{start_date}' "
        f"AND TxnDate <= '{end_date}' MAXRESULTS 1000"
    )


def get_undeposited_funds() -> list[dict]:
    return query("SELECT * FROM Payment WHERE UnappliedAmt > '0' MAXRESULTS 100")


def create_journal_entry(lines: list[dict], memo: str = "") -> dict | None:
    """Create a journal entry. Lines: [{\"Amount\": 100, \"DetailType\": \"JournalEntryLineDetail\", ...}]"""
    body = {
        "Line": lines,
        "PrivateNote": memo,
    }
    result = _qbo_request("POST", "journalentry", json=body)
    return result.get("JournalEntry") if result else None
