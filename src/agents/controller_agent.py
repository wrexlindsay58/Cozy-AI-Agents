import logging
from datetime import datetime, timedelta
from src.tools import quickbooks_tools as qbo

logger = logging.getLogger(__name__)


class ControllerAgent:
    """Reconciliation, month-end close, and data quality checks via QuickBooks."""

    def run_reconciliation_check(self) -> dict:
        """Check for unreconciled items and data quality issues."""
        issues = []

        open_invoices = qbo.get_open_invoices()
        unpaid_bills = qbo.get_unpaid_bills()

        overdue_invoices = []
        for inv in open_invoices:
            due = inv.get("DueDate", "")
            if due and due < datetime.now().strftime("%Y-%m-%d"):
                overdue_invoices.append({
                    "id": inv.get("Id"),
                    "customer": inv.get("CustomerRef", {}).get("name", "Unknown"),
                    "balance": inv.get("Balance"),
                    "due_date": due,
                })

        if overdue_invoices:
            issues.append({
                "type": "overdue_ar",
                "severity": "high",
                "count": len(overdue_invoices),
                "details": overdue_invoices[:10],
                "message": f"{len(overdue_invoices)} overdue invoice(s) found",
            })

        if len(unpaid_bills) > 0:
            issues.append({
                "type": "open_ap",
                "severity": "medium",
                "count": len(unpaid_bills),
                "message": f"{len(unpaid_bills)} unpaid bill(s) outstanding",
            })

        return {
            "status": "issues_found" if issues else "clean",
            "issue_count": len(issues),
            "issues": issues,
            "summary": {
                "open_invoices": len(open_invoices),
                "unpaid_bills": len(unpaid_bills),
                "overdue_invoices": len(overdue_invoices),
            },
            "checked_at": datetime.utcnow().isoformat(),
        }

    def get_close_checklist(self) -> list[dict]:
        """Return month-end close checklist with completion status."""
        recon = self.run_reconciliation_check()
        return [
            {"step": 1, "task": "Reconcile bank accounts", "status": "pending", "agent": "controller"},
            {"step": 2, "task": "Review AR aging", "status": "done" if not recon["issues"] else "action_needed",
             "details": recon["summary"]},
            {"step": 3, "task": "Review AP outstanding", "status": "pending", "agent": "controller"},
            {"step": 4, "task": "Verify payroll JEs posted", "status": "pending", "agent": "controller"},
            {"step": 5, "task": "Review uncoded transactions", "status": "pending", "agent": "controller"},
            {"step": 6, "task": "Check for duplicate bills", "status": "pending", "agent": "controller"},
            {"step": 7, "task": "Reconcile undeposited funds", "status": "pending", "agent": "controller"},
            {"step": 8, "task": "Review job costing allocations", "status": "pending", "agent": "job_costing"},
            {"step": 9, "task": "Post adjusting journal entries", "status": "pending", "agent": "controller"},
            {"step": 10, "task": "Generate P&L and balance sheet", "status": "pending", "agent": "profitability"},
            {"step": 11, "task": "Review 1099-eligible vendors", "status": "pending", "agent": "controller"},
            {"step": 12, "task": "Close books for period", "status": "pending", "agent": "controller"},
        ]

    def find_data_quality_issues(self) -> list[dict]:
        """Scan for common data quality problems."""
        issues = []
        accounts = qbo.get_accounts()

        uncategorized = [a for a in accounts if "uncategorized" in a.get("Name", "").lower()]
        if uncategorized:
            issues.append({
                "type": "uncategorized_accounts",
                "message": f"{len(uncategorized)} uncategorized account(s) in chart of accounts",
            })

        recon = self.run_reconciliation_check()
        issues.extend(recon.get("issues", []))

        return issues
