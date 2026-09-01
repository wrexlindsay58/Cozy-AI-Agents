import logging
from datetime import datetime, timedelta
from typing import Optional
import requests
from src.config import BAMBOOHR_SUBDOMAIN, BAMBOOHR_API_KEY

logger = logging.getLogger(__name__)

DEFAULT_BURDEN_RATE = 1.35  # payroll taxes + benefits multiplier


def is_configured() -> bool:
    return bool(BAMBOOHR_SUBDOMAIN and BAMBOOHR_API_KEY)


def _base_url() -> str:
    return f"https://api.bamboohr.com/api/gateway.php/{BAMBOOHR_SUBDOMAIN}/v1"


def _auth() -> tuple[str, str]:
    return (BAMBOOHR_API_KEY, "x")


def _request(method: str, endpoint: str, **kwargs) -> dict | list | str | None:
    if not is_configured():
        logger.warning("BambooHR credentials not configured")
        return None

    url = f"{_base_url()}{endpoint}"
    try:
        resp = requests.request(
            method, url, auth=_auth(), timeout=30, **kwargs,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            return resp.json()
        return resp.text
    except Exception as e:
        logger.error(f"BambooHR API error ({endpoint}): {e}")
        return None


def list_employees(status: str = "active") -> list[dict]:
    """Return employee directory with basic fields."""
    result = _request(
        "GET",
        "/employees/directory",
        headers={"Accept": "application/json"},
    )
    if not result:
        return []
    employees = result.get("employees", result) if isinstance(result, dict) else result
    if status:
        employees = [e for e in employees if e.get("status", "active").lower() == status.lower()]
    return employees


def get_employee(employee_id: str) -> dict | None:
    fields = "firstName,lastName,workEmail,department,jobTitle,status,payRate,payType"
    result = _request(
        "GET",
        f"/employees/{employee_id}/",
        params={"fields": fields},
        headers={"Accept": "application/json"},
    )
    return result if isinstance(result, dict) else None


def find_employee_by_name(name: str) -> dict | None:
    name_lower = name.lower()
    for emp in list_employees():
        full = f"{emp.get('firstName', '')} {emp.get('lastName', '')}".strip().lower()
        if name_lower in full or full in name_lower:
            return emp
    return None


def get_time_entries(
    employee_id: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Fetch time entries for an employee in a date range."""
    result = _request(
        "GET",
        f"/time_tracking/timesheet/{employee_id}/{start_date}/{end_date}",
        headers={"Accept": "application/json"},
    )
    if not result:
        return []
    if isinstance(result, dict):
        return result.get("entries", result.get("timesheet", []))
    return result if isinstance(result, list) else []


def get_company_time_entries(start_date: str, end_date: str) -> list[dict]:
    """Aggregate time entries across all active employees."""
    entries = []
    for emp in list_employees():
        emp_id = str(emp.get("id", ""))
        if not emp_id:
            continue
        emp_entries = get_time_entries(emp_id, start_date, end_date)
        for entry in emp_entries:
            entry["employee_id"] = emp_id
            entry["employee_name"] = f"{emp.get('firstName', '')} {emp.get('lastName', '')}".strip()
        entries.extend(emp_entries)
    return entries


def get_pto_balance(employee_id: str) -> dict | None:
    result = _request(
        "GET",
        f"/employees/{employee_id}/time_off/calculator",
        headers={"Accept": "application/json"},
    )
    return result if isinstance(result, dict) else None


def get_payroll_summary() -> dict:
    """Return a summary of BambooHR configuration and employee count."""
    employees = list_employees()
    return {
        "configured": is_configured(),
        "subdomain": BAMBOOHR_SUBDOMAIN,
        "active_employees": len(employees),
        "employees": [
            {
                "id": e.get("id"),
                "name": f"{e.get('firstName', '')} {e.get('lastName', '')}".strip(),
                "department": e.get("department"),
                "job_title": e.get("jobTitle"),
            }
            for e in employees[:50]
        ],
    }


def calculate_labor_cost(
    hours: float,
    hourly_rate: float,
    burden_rate: float = DEFAULT_BURDEN_RATE,
) -> float:
    return round(hours * hourly_rate * burden_rate, 2)


def get_period_dates(period: str) -> tuple[str, str]:
    """Convert YYYY-MM period to start/end dates."""
    year, month = map(int, period.split("-"))
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = datetime(year, month + 1, 1) - timedelta(days=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
