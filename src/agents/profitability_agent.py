import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from src.tools import quickbooks_tools as qbo
from src.tools import google_chat_tools as gchat
from src.db import job_billing as jb
from src.db import job_costing as jc
from src.db import commissions as comm_db
from src.agents.job_costing_agent import JobCostingAgent

logger = logging.getLogger(__name__)

JOB_TYPE_KEYWORDS = {
    "kitchen": ["kitchen", "cabinet", "countertop"],
    "bathroom": ["bath", "bathroom", "shower", "tile"],
    "roofing": ["roof", "roofing", "gutter"],
    "hvac": ["hvac", "furnace", "ac ", "air condition"],
    "plumbing": ["plumb", "pipe", "water heater"],
    "electrical": ["electric", "wiring", "panel"],
    "general": ["remodel", "renovation", "addition"],
}


class ProfitabilityAgent:
    """Company P&L, margin analytics, rep rankings, and financial dashboards."""

    def __init__(self):
        self.job_costing = JobCostingAgent()

    def get_company_pnl(self, start_date: str = None, end_date: str = None) -> dict:
        """Company P&L from local job data, supplemented by QBO when configured."""
        if not end_date:
            end_date = datetime.utcnow().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")

        jobs = jb.list_jobs()
        active = [j for j in jobs if j["status"] == "active"]
        completed = [j for j in jobs if j["status"] == "completed"]

        total_revenue = sum(j["contract_amount"] for j in jobs)
        total_costs = 0.0
        gross_profits = []

        for job in jobs:
            pnl = self.job_costing.get_job_pnl(job["id"])
            if pnl:
                total_costs += pnl["actuals"]["total"]
                gross_profits.append(pnl["gross_profit"])

        gross_profit = total_revenue - total_costs
        gross_margin = (gross_profit / total_revenue * 100) if total_revenue else 0

        result = {
            "period": {"start": start_date, "end": end_date},
            "source": "local_jobs",
            "revenue": round(total_revenue, 2),
            "costs": round(total_costs, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_margin_percent": round(gross_margin, 1),
            "active_jobs": len(active),
            "completed_jobs": len(completed),
            "total_jobs": len(jobs),
        }

        if qbo.is_configured():
            qbo_pnl = qbo.get_profit_and_loss(start_date, end_date)
            if qbo_pnl:
                result["qbo_report"] = {
                    "available": True,
                    "report_date": qbo_pnl.get("Header", {}).get("EndPeriod"),
                }
                result["source"] = "local_jobs+qbo"

        return result

    def get_balance_sheet(self, as_of_date: str = None) -> dict:
        if not as_of_date:
            as_of_date = datetime.utcnow().strftime("%Y-%m-%d")

        if qbo.is_configured():
            report = qbo.get_balance_sheet(as_of_date)
            if report:
                return {
                    "as_of": as_of_date,
                    "source": "qbo",
                    "report": report,
                }

        cash = qbo.get_total_cash_balance() if qbo.is_configured() else 0
        jobs = jb.list_jobs(status="active")
        contract_value = sum(j["contract_amount"] for j in jobs)
        return {
            "as_of": as_of_date,
            "source": "estimated",
            "cash": cash,
            "active_contract_value": contract_value,
            "message": "Connect QBO for full balance sheet",
        }

    def get_margins_by_job_type(self) -> list[dict]:
        """Gross margin breakdown by inferred job type."""
        jobs = jb.list_jobs()
        by_type = defaultdict(lambda: {"revenue": 0, "costs": 0, "count": 0, "jobs": []})

        for job in jobs:
            job_type = self._infer_job_type(job["name"])
            pnl = self.job_costing.get_job_pnl(job["id"])
            if not pnl:
                continue
            by_type[job_type]["revenue"] += pnl["revenue"]
            by_type[job_type]["costs"] += pnl["actuals"]["total"]
            by_type[job_type]["count"] += 1
            by_type[job_type]["jobs"].append({
                "id": job["id"],
                "name": job["name"],
                "margin_percent": pnl["margin_percent"],
            })

        results = []
        for job_type, data in by_type.items():
            revenue = data["revenue"]
            costs = data["costs"]
            margin = ((revenue - costs) / revenue * 100) if revenue else 0
            results.append({
                "job_type": job_type,
                "job_count": data["count"],
                "revenue": round(revenue, 2),
                "costs": round(costs, 2),
                "gross_profit": round(revenue - costs, 2),
                "gross_margin_percent": round(margin, 1),
            })

        return sorted(results, key=lambda x: x["revenue"], reverse=True)

    def get_rep_rankings(self) -> list[dict]:
        """Rank sales reps by revenue and margin contribution."""
        jobs = jb.list_jobs()
        rep_stats = defaultdict(lambda: {
            "revenue": 0, "costs": 0, "job_count": 0, "commissions": 0,
        })

        for job in jobs:
            attr = comm_db.get_attribution(job["id"])
            if not attr or not attr.get("sales_rep_name"):
                continue
            rep = attr["sales_rep_name"]
            pnl = self.job_costing.get_job_pnl(job["id"])
            if not pnl:
                continue
            rep_stats[rep]["revenue"] += pnl["revenue"]
            rep_stats[rep]["costs"] += pnl["actuals"]["total"]
            rep_stats[rep]["job_count"] += 1

        all_commissions = comm_db.list_commissions()
        for rec in all_commissions:
            if rec["rep_role"] == "sales_rep":
                rep_stats[rec["rep_name"]]["commissions"] += rec["commission_amount"]

        rankings = []
        for rep, stats in rep_stats.items():
            revenue = stats["revenue"]
            margin = ((revenue - stats["costs"]) / revenue * 100) if revenue else 0
            rankings.append({
                "rep_name": rep,
                "job_count": stats["job_count"],
                "revenue": round(revenue, 2),
                "costs": round(stats["costs"], 2),
                "gross_margin_percent": round(margin, 1),
                "commissions": round(stats["commissions"], 2),
                "profit_per_job": round((revenue - stats["costs"]) / stats["job_count"], 2) if stats["job_count"] else 0,
            })

        return sorted(rankings, key=lambda x: x["gross_margin_percent"], reverse=True)

    def get_seasonal_trends(self, months: int = 12) -> list[dict]:
        """Monthly revenue and margin trends from job creation dates."""
        jobs = jb.list_jobs()
        monthly = defaultdict(lambda: {"revenue": 0, "costs": 0, "job_count": 0})

        for job in jobs:
            created = job.get("created_at", "")
            if not created:
                continue
            month_key = created[:7]  # YYYY-MM
            pnl = self.job_costing.get_job_pnl(job["id"])
            monthly[month_key]["revenue"] += job["contract_amount"]
            monthly[month_key]["job_count"] += 1
            if pnl:
                monthly[month_key]["costs"] += pnl["actuals"]["total"]

        trends = []
        for month_key in sorted(monthly.keys())[-months:]:
            data = monthly[month_key]
            revenue = data["revenue"]
            margin = ((revenue - data["costs"]) / revenue * 100) if revenue else 0
            trends.append({
                "month": month_key,
                "job_count": data["job_count"],
                "revenue": round(revenue, 2),
                "costs": round(data["costs"], 2),
                "gross_margin_percent": round(margin, 1),
            })

        return trends

    def get_estimate_to_actual_variance(self) -> list[dict]:
        """Compare budgeted costs vs actual costs per job."""
        jobs = jb.list_jobs()
        variances = []

        for job in jobs:
            budget = jc.get_budget(job["id"])
            actuals = jc.get_actual_costs(job["id"])
            if budget["total"] <= 0 and actuals["total"] <= 0:
                continue

            total_budget = budget["total"] or job["contract_amount"] * 0.7
            variance = actuals["total"] - total_budget
            pct_over = (variance / total_budget * 100) if total_budget else 0

            variances.append({
                "job_id": job["id"],
                "job_name": job["name"],
                "contract_amount": job["contract_amount"],
                "budgeted_costs": round(total_budget, 2),
                "actual_costs": round(actuals["total"], 2),
                "variance": round(variance, 2),
                "variance_percent": round(pct_over, 1),
                "status": "over" if variance > 0 else "under",
            })

        return sorted(variances, key=lambda x: abs(x["variance"]), reverse=True)

    def get_monthly_package(self, period: str = None) -> dict:
        """Board-ready monthly financial package."""
        if not period:
            period = datetime.utcnow().strftime("%Y-%m")
        year, month = map(int, period.split("-"))
        start = f"{period}-01"
        if month == 12:
            end = f"{year + 1}-01-01"
        else:
            end = f"{year}-{month + 1:02d}-01"

        return {
            "period": period,
            "generated_at": datetime.utcnow().isoformat(),
            "pnl": self.get_company_pnl(start, end),
            "margins_by_type": self.get_margins_by_job_type(),
            "rep_rankings": self.get_rep_rankings(),
            "seasonal_trends": self.get_seasonal_trends(6),
            "estimate_to_actual": self.get_estimate_to_actual_variance()[:10],
            "portfolio": self.job_costing.get_portfolio_summary(),
        }

    def push_dashboard_to_chat(self, frequency: str = "daily") -> dict:
        """Push a financial dashboard summary to Google Chat."""
        pnl = self.get_company_pnl()
        portfolio = self.job_costing.get_portfolio_summary()
        margins = self.get_margins_by_job_type()
        top_reps = self.get_rep_rankings()[:3]

        margin_lines = "\n".join(
            f"  {m['job_type']}: {m['gross_margin_percent']}% ({m['job_count']} jobs)"
            for m in margins[:5]
        )
        rep_lines = "\n".join(
            f"  {r['rep_name']}: {r['gross_margin_percent']}% margin, ${r['revenue']:,.0f} revenue"
            for r in top_reps
        )

        text = (
            f"<b>{frequency.title()} Finance Dashboard</b>\n\n"
            f"<b>Portfolio</b>\n"
            f"  Active jobs: {portfolio['active_jobs']}\n"
            f"  Contract value: ${portfolio['total_contract_value']:,.0f}\n"
            f"  Portfolio margin: {portfolio['portfolio_margin_percent']}%\n"
            f"  Variance alerts: {portfolio['variance_alerts']}\n\n"
            f"<b>Company P&L (YTD)</b>\n"
            f"  Revenue: ${pnl['revenue']:,.0f}\n"
            f"  Gross margin: {pnl['gross_margin_percent']}%\n\n"
            f"<b>Margin by Job Type</b>\n{margin_lines or '  No data'}\n\n"
            f"<b>Top Reps</b>\n{rep_lines or '  No attribution data'}"
        )

        message_id = gchat.send_dashboard_card(
            title=f"{frequency.title()} Finance Dashboard",
            sections=[
                {"text": text.replace("<b>", "*").replace("</b>", "*")},
            ],
        )

        return {
            "status": "sent" if message_id else "skipped",
            "frequency": frequency,
            "chat_message_id": message_id,
            "dashboard": {
                "portfolio": portfolio,
                "pnl": pnl,
            },
        }

    def _infer_job_type(self, job_name: str) -> str:
        name_lower = job_name.lower()
        for job_type, keywords in JOB_TYPE_KEYWORDS.items():
            if any(kw in name_lower for kw in keywords):
                return job_type
        return "other"
