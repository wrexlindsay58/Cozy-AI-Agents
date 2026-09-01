import logging
from src.db import job_billing as jb
from src.db import job_costing as jc
from src.db import change_orders as co_db

logger = logging.getLogger(__name__)


class JobCostingAgent:
    """Real-time job P&L, budget variance, and WIP tracking."""

    def set_budget(self, job_id: str, estimates: dict) -> dict:
        job = jb.get_job(job_id)
        if not job:
            return {"error": "Job not found"}
        budget = jc.set_budget(job_id, estimates)
        return {"job_id": job_id, "budget": budget}

    def add_cost(
        self, job_id: str, category: str, amount: float,
        description: str = "", source: str = "manual", reference_id: str = None,
    ) -> dict:
        job = jb.get_job(job_id)
        if not job:
            return {"error": "Job not found"}
        actuals = jc.add_cost(job_id, category, amount, description, source, reference_id)
        variance = jc.get_variance(job_id, job["contract_amount"])
        return {"job_id": job_id, "actuals": actuals, "variance": variance}

    def get_job_pnl(self, job_id: str) -> dict | None:
        job = jb.get_job(job_id)
        if not job:
            return None

        budget = jc.get_budget(job_id)
        actuals = jc.get_actual_costs(job_id)
        variance = jc.get_variance(job_id, job["contract_amount"])
        revenue = job["contract_amount"]
        gross_profit = revenue - actuals["total"]
        margin_pct = (gross_profit / revenue * 100) if revenue > 0 else 0

        return {
            "job": job,
            "revenue": revenue,
            "budget": budget,
            "actuals": actuals,
            "variance": variance,
            "gross_profit": gross_profit,
            "margin_percent": round(margin_pct, 1),
            "cost_entries": jc.list_cost_entries(job_id),
        }

    def get_variance_alerts(self) -> list[dict]:
        jobs = jb.list_jobs(status="active")
        alerts = []
        for job in jobs:
            variance = jc.get_variance(job["id"], job["contract_amount"])
            if variance["alert_level"]:
                alerts.append({
                    "job_id": job["id"],
                    "job_name": job["name"],
                    "customer": job["customer_name"],
                    "alert_level": variance["alert_level"],
                    "pct_used": variance["pct_used"],
                    "total_budget": variance["total_budget"],
                    "total_actual": variance["total_actual"],
                    "message": self._alert_message(job["name"], variance),
                })
        return sorted(alerts, key=lambda x: x["pct_used"], reverse=True)

    def get_wip_report(self) -> list[dict]:
        """Work-in-progress: active jobs with costs incurred but not yet fully billed."""
        jobs = jb.list_jobs(status="active")
        wip = []
        for job in jobs:
            actuals = jc.get_actual_costs(job["id"])
            if actuals["total"] <= 0:
                continue
            billed_revenue = job["contract_amount"] * (job.get("billed_percent", 0) / 100)
            wip.append({
                "job_id": job["id"],
                "job_name": job["name"],
                "customer": job["customer_name"],
                "contract_amount": job["contract_amount"],
                "costs_incurred": actuals["total"],
                "billed_revenue": billed_revenue,
                "wip_asset": actuals["total"] - billed_revenue,
                "completion_percent": job["completion_percent"],
                "billed_percent": job.get("billed_percent", 0),
            })
        return wip

    def get_portfolio_summary(self) -> dict:
        jobs = jb.list_jobs()
        active = [j for j in jobs if j["status"] == "active"]
        total_revenue = sum(j["contract_amount"] for j in active)
        total_costs = 0.0
        margins = []

        for job in active:
            pnl = self.get_job_pnl(job["id"])
            if pnl:
                total_costs += pnl["actuals"]["total"]
                margins.append(pnl["margin_percent"])

        avg_margin = sum(margins) / len(margins) if margins else 0
        return {
            "active_jobs": len(active),
            "total_contract_value": total_revenue,
            "total_costs": total_costs,
            "portfolio_margin_percent": round(avg_margin, 1),
            "variance_alerts": len(self.get_variance_alerts()),
            "wip_jobs": len(self.get_wip_report()),
        }

    def allocate_ap_cost(self, job_id: str, amount: float, description: str, bill_reference: str) -> dict:
        """Called by AP Agent when a bill is coded to a job."""
        return self.add_cost(
            job_id, "materials", amount, description,
            source="ap", reference_id=bill_reference,
        )

    def _alert_message(self, job_name: str, variance: dict) -> str:
        level = variance["alert_level"]
        pct = variance["pct_used"]
        if level == "over_budget":
            return f"{job_name}: OVER BUDGET at {pct}% of estimate"
        if level == "critical":
            return f"{job_name}: At {pct}% of budget — review immediately"
        return f"{job_name}: At {pct}% of budget — approaching limit"
