import logging
from datetime import datetime, timedelta
from src.db import job_billing as jb
from src.db import job_costing as jc
from src.db import commissions as comm_db
from src.db.commissions import CommissionStatus
from src.agents.approval_gateway_agent import ApprovalGatewayAgent

logger = logging.getLogger(__name__)


class CommissionAgent:
    """Rules engine for sales commissions — calculates, accrues, and proposes payouts."""

    def __init__(self):
        self.approval_gateway = ApprovalGatewayAgent()

    def get_rules(self) -> list[dict]:
        return comm_db.list_rules()

    def set_attribution(
        self,
        job_id: str,
        sales_rep_id: str = None,
        sales_rep_name: str = None,
        lead_setter_id: str = None,
        lead_setter_name: str = None,
        sales_rep_split: float = 80.0,
        lead_setter_split: float = 20.0,
    ) -> dict:
        job = jb.get_job(job_id)
        if not job:
            return {"error": "Job not found"}
        return comm_db.set_attribution(
            job_id, sales_rep_id, sales_rep_name,
            lead_setter_id, lead_setter_name,
            sales_rep_split, lead_setter_split,
        )

    def calculate_for_job(self, job_id: str, trigger: str = None) -> list[dict]:
        """Calculate commissions for a job based on active rules and attribution."""
        job = jb.get_job(job_id)
        if not job:
            return []

        attribution = comm_db.get_attribution(job_id)
        if not attribution or not attribution.get("sales_rep_name"):
            return []

        rules = comm_db.list_rules()
        results = []
        contract = job["contract_amount"]
        pnl = jc.get_actual_costs(job_id)
        gross_margin = contract - pnl["total"]

        for rule in rules:
            if trigger and rule["trigger"] != trigger:
                continue
            if rule.get("min_contract") and contract < rule["min_contract"]:
                continue

            amount = self._apply_rule(rule, contract, gross_margin)
            if amount <= 0:
                continue

            reps = self._split_commission(attribution, amount)
            for rep in reps:
                existing = self._find_existing(job_id, rep["name"], rule["trigger"], rule["id"])
                if existing:
                    results.append(existing)
                    continue

                record = comm_db.create_commission_record(
                    job_id=job_id,
                    rep_name=rep["name"],
                    rep_id=rep.get("id"),
                    rep_role=rep["role"],
                    trigger_event=rule["trigger"],
                    base_amount=contract if rule["rule_type"] != "percent_of_margin" else gross_margin,
                    commission_amount=rep["amount"],
                    commission_rate=rule.get("rate"),
                    rule_id=rule["id"],
                    notes=f"Rule: {rule['name']}",
                )
                results.append(record)

        return results

    def accrue_at_trigger(self, job_id: str, trigger: str) -> dict:
        """Accrue commissions when a billing trigger fires (signing, milestone, completion)."""
        records = self.calculate_for_job(job_id, trigger=trigger)
        return {
            "job_id": job_id,
            "trigger": trigger,
            "commissions_accrued": len(records),
            "total_amount": sum(r["commission_amount"] for r in records),
            "records": records,
        }

    def clawback(self, job_id: str, reason: str) -> dict:
        """Claw back commissions on cancelled jobs or warranty callbacks."""
        job = jb.get_job(job_id)
        if not job:
            return {"error": "Job not found"}

        clawbackable = comm_db.list_commissions(job_id=job_id)
        clawed = []
        for rec in clawbackable:
            if rec["status"] in (CommissionStatus.PAID.value, CommissionStatus.CLAWED_BACK.value):
                continue
            rule = comm_db.get_rule(rec["rule_id"]) if rec.get("rule_id") else None
            clawback_days = rule["clawback_days"] if rule else 90
            created = datetime.fromisoformat(rec["created_at"]) if rec.get("created_at") else datetime.utcnow()
            if (datetime.utcnow() - created).days <= clawback_days:
                updated = comm_db.update_commission_status(
                    rec["id"], CommissionStatus.CLAWED_BACK.value, clawback_reason=reason,
                )
                if updated:
                    clawed.append(updated)

        return {
            "job_id": job_id,
            "reason": reason,
            "clawed_back_count": len(clawed),
            "records": clawed,
        }

    def get_monthly_statement(self, rep_name: str, period: str = None) -> dict:
        if not period:
            period = datetime.utcnow().strftime("%Y-%m")
        records = comm_db.list_commissions(period=period)
        rep_records = [r for r in records if r["rep_name"].lower() == rep_name.lower()]

        by_status = {}
        for rec in rep_records:
            by_status.setdefault(rec["status"], []).append(rec)

        total_accrued = sum(r["commission_amount"] for r in rep_records)
        total_paid = sum(
            r["commission_amount"] for r in rep_records
            if r["status"] == CommissionStatus.PAID.value
        )
        total_pending = sum(
            r["commission_amount"] for r in rep_records
            if r["status"] in (CommissionStatus.ACCRUED.value, CommissionStatus.APPROVED.value)
        )

        return {
            "rep_name": rep_name,
            "period": period,
            "total_accrued": total_accrued,
            "total_paid": total_paid,
            "total_pending": total_pending,
            "record_count": len(rep_records),
            "by_status": {k: len(v) for k, v in by_status.items()},
            "records": rep_records,
        }

    def propose_payout(self, commission_ids: list[str] = None, period: str = None) -> dict:
        """Propose commission payout for approval — hands off to Payroll Agent after approval."""
        if commission_ids:
            records = [comm_db.get_commission(cid) for cid in commission_ids]
            records = [r for r in records if r]
        else:
            records = comm_db.list_commissions(
                period=period or datetime.utcnow().strftime("%Y-%m"),
                status=CommissionStatus.ACCRUED.value,
            )

        if not records:
            return {"status": "no_commissions", "message": "No accrued commissions to pay"}

        total = sum(r["commission_amount"] for r in records)
        summary = [
            {"rep": r["rep_name"], "job_id": r["job_id"], "amount": r["commission_amount"]}
            for r in records
        ]

        approval = self.approval_gateway.submit(
            approval_type="commission",
            title=f"Commission payout — {len(records)} rep(s), ${total:,.2f}",
            description=self._format_payout_description(summary),
            amount=total,
            payload={
                "action": "approve_commission_payout",
                "commission_ids": [r["id"] for r in records],
                "period": period or datetime.utcnow().strftime("%Y-%m"),
            },
            agent_name="commission_agent",
        )

        for rec in records:
            comm_db.update_commission_status(rec["id"], CommissionStatus.PENDING_APPROVAL.value)

        return {
            "status": "approval_submitted",
            "commission_count": len(records),
            "total_amount": total,
            "approval": approval,
            "summary": summary,
        }

    def approve_payout(self, commission_ids: list[str]) -> dict:
        """Mark commissions as approved (called after approval gateway resolves)."""
        approved = []
        for cid in commission_ids:
            rec = comm_db.update_commission_status(cid, CommissionStatus.APPROVED.value)
            if rec:
                approved.append(rec)
        return {"status": "approved", "count": len(approved), "records": approved}

    def list_commissions(
        self, job_id: str = None, period: str = None, status: str = None,
    ) -> list[dict]:
        return comm_db.list_commissions(job_id=job_id, period=period, status=status)

    def get_summary(self) -> dict:
        all_records = comm_db.list_commissions()
        accrued = [r for r in all_records if r["status"] == CommissionStatus.ACCRUED.value]
        pending = [r for r in all_records if r["status"] == CommissionStatus.PENDING_APPROVAL.value]
        paid = [r for r in all_records if r["status"] == CommissionStatus.PAID.value]
        clawed = [r for r in all_records if r["status"] == CommissionStatus.CLAWED_BACK.value]

        return {
            "total_records": len(all_records),
            "accrued_count": len(accrued),
            "accrued_amount": sum(r["commission_amount"] for r in accrued),
            "pending_approval_count": len(pending),
            "paid_count": len(paid),
            "paid_amount": sum(r["commission_amount"] for r in paid),
            "clawed_back_count": len(clawed),
            "active_rules": len(comm_db.list_rules()),
        }

    def _apply_rule(self, rule: dict, contract: float, gross_margin: float) -> float:
        rule_type = rule["rule_type"]
        if rule_type == "percent_of_sale":
            return round(contract * (rule["rate"] / 100), 2)
        if rule_type == "percent_of_margin":
            return round(max(gross_margin, 0) * (rule["rate"] / 100), 2)
        if rule_type == "tiered":
            rate = self._tiered_rate(rule["tiers"], contract)
            return round(contract * (rate / 100), 2)
        return 0.0

    def _tiered_rate(self, tiers: list[dict], amount: float) -> float:
        for tier in sorted(tiers, key=lambda t: t["max_amount"] or float("inf")):
            max_amt = tier["max_amount"]
            if max_amt is None or amount <= max_amt:
                return tier["rate"]
        return tiers[-1]["rate"] if tiers else 0.0

    def _split_commission(self, attribution: dict, amount: float) -> list[dict]:
        reps = []
        sales_split = attribution.get("sales_rep_split", 100) / 100
        lead_split = attribution.get("lead_setter_split", 0) / 100

        if attribution.get("sales_rep_name"):
            reps.append({
                "name": attribution["sales_rep_name"],
                "id": attribution.get("sales_rep_id"),
                "role": "sales_rep",
                "amount": round(amount * sales_split, 2),
            })
        if attribution.get("lead_setter_name") and lead_split > 0:
            reps.append({
                "name": attribution["lead_setter_name"],
                "id": attribution.get("lead_setter_id"),
                "role": "lead_setter",
                "amount": round(amount * lead_split, 2),
            })
        return reps

    def _find_existing(self, job_id, rep_name, trigger, rule_id) -> dict | None:
        records = comm_db.list_commissions(job_id=job_id)
        for rec in records:
            if (
                rec["rep_name"] == rep_name
                and rec["trigger_event"] == trigger
                and rec["rule_id"] == rule_id
                and rec["status"] != CommissionStatus.CLAWED_BACK.value
            ):
                return rec
        return None

    def _format_payout_description(self, summary: list[dict]) -> str:
        lines = [f"  {s['rep']}: ${s['amount']:,.2f}" for s in summary[:10]]
        if len(summary) > 10:
            lines.append(f"  ... and {len(summary) - 10} more")
        return "Commission payout breakdown:\n" + "\n".join(lines)
