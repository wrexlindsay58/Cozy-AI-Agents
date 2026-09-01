import logging
from datetime import datetime, timedelta
from src.tools import quickbooks_tools as qbo
from src.tools.gmail_tools import create_draft
from src.config import COLLECTIONS_FROM_EMAIL, LIEN_RIGHTS_STATE

logger = logging.getLogger(__name__)

AGING_BUCKETS = [
    ("current", 0, 7),
    ("7_days", 7, 14),
    ("14_days", 14, 30),
    ("30_days", 30, 60),
    ("60_plus", 60, 9999),
]

COLLECTIONS_TEMPLATES = {
    "7_days": "Friendly reminder that invoice #{doc_number} for ${balance:,.2f} was due on {due_date}. Please let us know if you have any questions.",
    "14_days": "This is a follow-up regarding invoice #{doc_number} for ${balance:,.2f}, now {days_overdue} days past due. Please arrange payment at your earliest convenience.",
    "30_days": "Our records show invoice #{doc_number} for ${balance:,.2f} is now {days_overdue} days overdue. Please contact us immediately to resolve this balance.",
    "60_plus": "URGENT: Invoice #{doc_number} for ${balance:,.2f} is significantly overdue ({days_overdue} days). Immediate payment is required to avoid further action.",
}


class ARAgent:
    """Accounts Receivable — invoicing, aging, payment matching, collections drafts."""

    def get_ar_aging(self) -> dict:
        invoices = qbo.get_open_invoices()
        today = datetime.now().date()
        buckets = {name: [] for name, _, _ in AGING_BUCKETS}
        total_outstanding = 0.0

        for inv in invoices:
            balance = float(inv.get("Balance", 0))
            if balance <= 0:
                continue
            total_outstanding += balance

            due_str = inv.get("DueDate", inv.get("TxnDate", ""))
            try:
                due_date = datetime.strptime(due_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                due_date = today

            days_overdue = (today - due_date).days
            entry = {
                "invoice_id": inv.get("Id"),
                "doc_number": inv.get("DocNumber"),
                "customer": inv.get("CustomerRef", {}).get("name", "Unknown"),
                "balance": balance,
                "due_date": due_str,
                "days_overdue": max(days_overdue, 0),
                "txn_date": inv.get("TxnDate"),
            }

            placed = False
            for bucket_name, min_days, max_days in AGING_BUCKETS:
                if min_days <= days_overdue < max_days:
                    buckets[bucket_name].append(entry)
                    placed = True
                    break
            if not placed:
                buckets["60_plus"].append(entry)

        return {
            "total_outstanding": total_outstanding,
            "invoice_count": sum(len(v) for v in buckets.values()),
            "buckets": buckets,
            "checked_at": datetime.utcnow().isoformat(),
        }

    def get_overdue_invoices(self) -> list[dict]:
        aging = self.get_ar_aging()
        overdue = []
        for bucket_name in ("7_days", "14_days", "30_days", "60_plus"):
            overdue.extend(aging["buckets"].get(bucket_name, []))
        return sorted(overdue, key=lambda x: x["days_overdue"], reverse=True)

    def match_payments(self, since_date: str = None) -> dict:
        """Identify recent QBO payments and match to open invoices."""
        if not since_date:
            since_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        payments = qbo.get_payments(since_date)
        open_invoices = {inv["Id"]: inv for inv in qbo.get_open_invoices()}
        matched = []
        unmatched_payments = []

        for payment in payments:
            linked = payment.get("Line", [])
            payment_matched = False
            for line in linked:
                txn_id = line.get("LinkedTxn", [{}])[0].get("TxnId") if line.get("LinkedTxn") else None
                if txn_id and txn_id in open_invoices:
                    matched.append({
                        "payment_id": payment.get("Id"),
                        "invoice_id": txn_id,
                        "amount": line.get("Amount"),
                        "customer": payment.get("CustomerRef", {}).get("name"),
                        "date": payment.get("TxnDate"),
                    })
                    payment_matched = True
            if not payment_matched:
                unmatched_payments.append({
                    "payment_id": payment.get("Id"),
                    "amount": payment.get("TotalAmt"),
                    "customer": payment.get("CustomerRef", {}).get("name"),
                    "date": payment.get("TxnDate"),
                })

        return {
            "matched": matched,
            "unmatched_payments": unmatched_payments,
            "matched_count": len(matched),
            "unmatched_count": len(unmatched_payments),
        }

    def draft_collections_email(self, invoice: dict) -> dict | None:
        """Draft a collections follow-up email (never auto-send)."""
        days = invoice.get("days_overdue", 0)
        bucket = "7_days"
        for bucket_name, min_days, max_days in AGING_BUCKETS:
            if min_days <= days < max_days:
                bucket = bucket_name
                break
        if days >= 60:
            bucket = "60_plus"

        template = COLLECTIONS_TEMPLATES.get(bucket, COLLECTIONS_TEMPLATES["7_days"])
        body = template.format(
            doc_number=invoice.get("doc_number", "N/A"),
            balance=invoice.get("balance", 0),
            due_date=invoice.get("due_date", "N/A"),
            days_overdue=days,
        )

        customer_name = invoice.get("customer", "Valued Customer")
        subject = f"Payment Reminder — Invoice #{invoice.get('doc_number', 'N/A')}"

        full_body = (
            f"Dear {customer_name},\n\n"
            f"{body}\n\n"
            f"If you have already sent payment, please disregard this notice. "
            f"We appreciate your business.\n\n"
            f"Thank you,\n"
            f"Accounts Receivable"
        )

        return {
            "subject": subject,
            "body": full_body,
            "invoice_id": invoice.get("invoice_id"),
            "bucket": bucket,
            "status": "draft_ready",
        }

    def run_collections_cycle(self) -> dict:
        """Draft collection emails for all overdue invoices."""
        overdue = self.get_overdue_invoices()
        drafts = []
        for inv in overdue:
            draft = self.draft_collections_email(inv)
            if draft:
                drafts.append(draft)
        return {
            "overdue_count": len(overdue),
            "drafts_created": len(drafts),
            "drafts": drafts,
        }

    def get_lien_rights_alert(self, job_completion_date: str) -> dict:
        """Return lien rights deadline info for home improvement work."""
        try:
            completion = datetime.strptime(job_completion_date, "%Y-%m-%d")
        except ValueError:
            return {"error": "Invalid date format. Use YYYY-MM-DD."}

        deadlines = {
            "CA": 90,
            "TX": 120,
            "FL": 90,
            "NY": 120,
        }
        days = deadlines.get(LIEN_RIGHTS_STATE, 90)
        deadline = completion + timedelta(days=days)
        days_remaining = (deadline.date() - datetime.now().date()).days

        return {
            "state": LIEN_RIGHTS_STATE,
            "completion_date": job_completion_date,
            "lien_deadline": deadline.strftime("%Y-%m-%d"),
            "days_remaining": days_remaining,
            "urgent": days_remaining <= 14,
            "message": (
                f"Lien rights deadline in {LIEN_RIGHTS_STATE}: "
                f"{deadline.strftime('%Y-%m-%d')} ({days_remaining} days remaining)"
            ),
        }

    def get_summary(self) -> dict:
        aging = self.get_ar_aging()
        overdue = self.get_overdue_invoices()
        return {
            "total_outstanding": aging["total_outstanding"],
            "open_invoices": aging["invoice_count"],
            "overdue_count": len(overdue),
            "overdue_amount": sum(i["balance"] for i in overdue),
            "aging": {k: len(v) for k, v in aging["buckets"].items()},
        }
