import logging
from collections import defaultdict
from datetime import datetime, timedelta
from src.config import (
    CASH_FLOW_ALERT_THRESHOLD,
    CASH_FLOW_STARTING_BALANCE,
    FORECAST_WEEKS,
)
from src.tools import quickbooks_tools as qbo
from src.tools import google_chat_tools as gchat
from src.db import job_billing as jb
from src.db import job_costing as jc
from src.db import commissions as comm_db
from src.db.commissions import CommissionStatus

logger = logging.getLogger(__name__)


class CashFlowAgent:
    """13-week cash flow forecast, job affordability, and liquidity alerts."""

    def get_current_cash_position(self) -> dict:
        """Current cash from QBO bank accounts or configured starting balance."""
        if qbo.is_configured():
            balances = qbo.get_bank_account_balances()
            total = sum(b["balance"] for b in balances)
            return {
                "source": "qbo",
                "total_cash": round(total, 2),
                "accounts": balances,
                "alert_threshold": CASH_FLOW_ALERT_THRESHOLD,
                "below_threshold": total < CASH_FLOW_ALERT_THRESHOLD,
            }

        return {
            "source": "configured",
            "total_cash": CASH_FLOW_STARTING_BALANCE,
            "accounts": [],
            "alert_threshold": CASH_FLOW_ALERT_THRESHOLD,
            "below_threshold": CASH_FLOW_STARTING_BALANCE < CASH_FLOW_ALERT_THRESHOLD,
            "message": "Set QBO credentials or CASH_FLOW_STARTING_BALANCE for accurate cash position",
        }

    def get_13_week_forecast(self, starting_cash: float = None) -> dict:
        """Rolling 13-week cash flow forecast from AR, AP, and payroll data."""
        if starting_cash is None:
            starting_cash = self.get_current_cash_position()["total_cash"]

        today = datetime.utcnow().date()
        weeks = []

        ar_inflows = self._project_ar_collections()
        ap_outflows = self._project_ap_payments()
        payroll_outflows = self._project_payroll()
        job_inflows = self._project_job_billing()

        running_cash = starting_cash
        min_cash = starting_cash
        min_week = 0
        alerts = []

        for week_num in range(FORECAST_WEEKS):
            week_start = today + timedelta(weeks=week_num)
            week_end = week_start + timedelta(days=6)
            week_key = week_start.strftime("%Y-%m-%d")

            inflow = (
                ar_inflows.get(week_key, 0)
                + job_inflows.get(week_key, 0)
            )
            outflow = (
                ap_outflows.get(week_key, 0)
                + payroll_outflows.get(week_key, 0)
            )
            net = inflow - outflow
            running_cash += net

            if running_cash < min_cash:
                min_cash = running_cash
                min_week = week_num + 1

            week_data = {
                "week": week_num + 1,
                "start_date": week_key,
                "end_date": week_end.strftime("%Y-%m-%d"),
                "inflows": round(inflow, 2),
                "outflows": round(outflow, 2),
                "net": round(net, 2),
                "ending_cash": round(running_cash, 2),
            }
            weeks.append(week_data)

            if running_cash < CASH_FLOW_ALERT_THRESHOLD:
                alerts.append({
                    "week": week_num + 1,
                    "date": week_key,
                    "projected_cash": round(running_cash, 2),
                    "threshold": CASH_FLOW_ALERT_THRESHOLD,
                    "message": f"Week {week_num + 1}: projected cash ${running_cash:,.0f} below ${CASH_FLOW_ALERT_THRESHOLD:,.0f} threshold",
                })

        return {
            "starting_cash": round(starting_cash, 2),
            "forecast_weeks": FORECAST_WEEKS,
            "ending_cash": round(running_cash, 2),
            "minimum_cash": round(min_cash, 2),
            "minimum_cash_week": min_week,
            "weeks": weeks,
            "alerts": alerts,
            "alert_count": len(alerts),
            "status": "critical" if alerts else "healthy",
        }

    def analyze_job_affordability(
        self,
        contract_amount: float,
        estimated_costs: float,
        deposit_percent: float = 40,
        duration_weeks: int = 8,
    ) -> dict:
        """'Can we afford this job?' — model cash impact before signing."""
        deposit = contract_amount * (deposit_percent / 100)
        remaining = contract_amount - deposit
        weekly_billing = remaining / max(duration_weeks - 1, 1)
        weekly_costs = estimated_costs / duration_weeks

        current = self.get_current_cash_position()
        starting_cash = current["total_cash"]

        weeks = []
        running_cash = starting_cash
        min_cash = starting_cash

        for w in range(duration_weeks):
            inflow = deposit if w == 0 else weekly_billing
            outflow = weekly_costs
            net = inflow - outflow
            running_cash += net
            min_cash = min(min_cash, running_cash)
            weeks.append({
                "week": w + 1,
                "inflow": round(inflow, 2),
                "outflow": round(outflow, 2),
                "net": round(net, 2),
                "ending_cash": round(running_cash, 2),
            })

        max_cash_need = estimated_costs - deposit
        affordable = min_cash >= CASH_FLOW_ALERT_THRESHOLD

        return {
            "affordable": affordable,
            "contract_amount": contract_amount,
            "estimated_costs": estimated_costs,
            "estimated_margin_percent": round(
                (contract_amount - estimated_costs) / contract_amount * 100, 1,
            ) if contract_amount else 0,
            "deposit": round(deposit, 2),
            "max_cash_need": round(max(0, max_cash_need), 2),
            "minimum_projected_cash": round(min_cash, 2),
            "ending_projected_cash": round(running_cash, 2),
            "alert_threshold": CASH_FLOW_ALERT_THRESHOLD,
            "weeks": weeks,
            "recommendation": (
                "Proceed — cash position stays above threshold"
                if affordable
                else f"Caution — projected cash drops to ${min_cash:,.0f}, below ${CASH_FLOW_ALERT_THRESHOLD:,.0f} threshold"
            ),
        }

    def analyze_job_affordability_by_id(self, job_id: str) -> dict:
        job = jb.get_job(job_id)
        if not job:
            return {"error": "Job not found"}

        budget = jc.get_budget(job_id)
        estimated_costs = budget["total"] or job["contract_amount"] * 0.7
        duration_weeks = max(int(job.get("completion_percent", 0) / 100 * 12) or 8, 4)

        result = self.analyze_job_affordability(
            contract_amount=job["contract_amount"],
            estimated_costs=estimated_costs,
            deposit_percent=job.get("deposit_percent", 40),
            duration_weeks=duration_weeks,
        )
        result["job_id"] = job_id
        result["job_name"] = job["name"]
        return result

    def get_seasonal_plan(self) -> dict:
        """Seasonal cash planning based on historical job creation patterns."""
        jobs = jb.list_jobs()
        monthly_jobs = defaultdict(lambda: {"count": 0, "revenue": 0})

        for job in jobs:
            created = job.get("created_at", "")
            if not created:
                continue
            month = int(created[5:7])
            monthly_jobs[month]["count"] += 1
            monthly_jobs[month]["revenue"] += job["contract_amount"]

        season_names = {
            (12, 1, 2): "winter",
            (3, 4, 5): "spring",
            (6, 7, 8): "summer",
            (9, 10, 11): "fall",
        }
        seasonal = defaultdict(lambda: {"count": 0, "revenue": 0})
        for month, data in monthly_jobs.items():
            for months, season in season_names.items():
                if month in months:
                    seasonal[season]["count"] += data["count"]
                    seasonal[season]["revenue"] += data["revenue"]

        current_month = datetime.utcnow().month
        current_season = next(
            (s for months, s in season_names.items() if current_month in months),
            "unknown",
        )

        slow_seasons = sorted(
            seasonal.items(), key=lambda x: x[1]["revenue"],
        )

        return {
            "current_season": current_season,
            "seasonal_breakdown": dict(seasonal),
            "slowest_season": slow_seasons[0][0] if slow_seasons else None,
            "busiest_season": slow_seasons[-1][0] if slow_seasons else None,
            "recommendation": self._seasonal_recommendation(current_season, seasonal),
        }

    def model_collection_scenario(
        self,
        accelerate_ar_days: int = 0,
        defer_ap_days: int = 0,
    ) -> dict:
        """Model impact of accelerating AR collections or deferring AP."""
        base = self.get_13_week_forecast()
        adjusted_starting = base["starting_cash"]

        ar_shift = self._project_ar_collections(accelerate_days=accelerate_ar_days)
        ap_shift = self._project_ap_payments(defer_days=defer_ap_days)

        today = datetime.utcnow().date()
        running_cash = adjusted_starting
        weeks = []

        for week_num in range(FORECAST_WEEKS):
            week_start = today + timedelta(weeks=week_num)
            week_key = week_start.strftime("%Y-%m-%d")
            inflow = ar_shift.get(week_key, 0)
            outflow = ap_shift.get(week_key, 0)
            net = inflow - outflow
            running_cash += net
            weeks.append({
                "week": week_num + 1,
                "net": round(net, 2),
                "ending_cash": round(running_cash, 2),
            })

        return {
            "scenario": {
                "accelerate_ar_days": accelerate_ar_days,
                "defer_ap_days": defer_ap_days,
            },
            "base_ending_cash": base["ending_cash"],
            "adjusted_ending_cash": round(running_cash, 2),
            "cash_improvement": round(running_cash - base["ending_cash"], 2),
            "weeks": weeks,
        }

    def push_cash_alert_to_chat(self) -> dict:
        """Push cash flow alerts to Google Chat if thresholds are breached."""
        forecast = self.get_13_week_forecast()
        position = self.get_current_cash_position()

        if not forecast["alerts"] and not position["below_threshold"]:
            return {"status": "no_alerts", "message": "Cash position is healthy"}

        alert_lines = "\n".join(f"  ⚠ {a['message']}" for a in forecast["alerts"][:5])
        text = (
            f"*Cash Flow Alert*\n\n"
            f"Current cash: ${position['total_cash']:,.0f}\n"
            f"Threshold: ${CASH_FLOW_ALERT_THRESHOLD:,.0f}\n"
            f"13-week minimum: ${forecast['minimum_cash']:,.0f} (week {forecast['minimum_cash_week']})\n\n"
            f"{alert_lines or '  Current cash below threshold'}"
        )

        message_id = gchat.send_dashboard_card(
            title="Cash Flow Alert",
            sections=[{"text": text}],
        )

        return {
            "status": "sent" if message_id else "skipped",
            "alert_count": len(forecast["alerts"]),
            "chat_message_id": message_id,
            "forecast_summary": {
                "minimum_cash": forecast["minimum_cash"],
                "ending_cash": forecast["ending_cash"],
            },
        }

    def get_summary(self) -> dict:
        position = self.get_current_cash_position()
        forecast = self.get_13_week_forecast()
        seasonal = self.get_seasonal_plan()

        return {
            "current_cash": position["total_cash"],
            "below_threshold": position["below_threshold"],
            "alert_threshold": CASH_FLOW_ALERT_THRESHOLD,
            "forecast_status": forecast["status"],
            "forecast_alerts": forecast["alert_count"],
            "minimum_cash_13wk": forecast["minimum_cash"],
            "ending_cash_13wk": forecast["ending_cash"],
            "current_season": seasonal["current_season"],
            "slowest_season": seasonal["slowest_season"],
        }

    def _project_ar_collections(self, accelerate_days: int = 0) -> dict:
        weekly = defaultdict(float)

        if qbo.is_configured():
            invoices = qbo.get_open_invoices()
            for inv in invoices:
                due = inv.get("DueDate", "")
                balance = float(inv.get("Balance", 0) or 0)
                if due and balance > 0:
                    due_date = datetime.strptime(due, "%Y-%m-%d").date()
                    if accelerate_days:
                        due_date -= timedelta(days=accelerate_days)
                    week_start = due_date - timedelta(days=due_date.weekday())
                    weekly[week_start.strftime("%Y-%m-%d")] += balance
        else:
            jobs = jb.list_jobs(status="active")
            for job in jobs:
                unbilled = job["contract_amount"] * (1 - job.get("billed_percent", 0) / 100)
                if unbilled > 0:
                    week_key = datetime.utcnow().date().strftime("%Y-%m-%d")
                    weekly[week_key] += unbilled * 0.25

        return dict(weekly)

    def _project_ap_payments(self, defer_days: int = 0) -> dict:
        weekly = defaultdict(float)

        if qbo.is_configured():
            bills = qbo.get_unpaid_bills()
            for bill in bills:
                due = bill.get("DueDate", "")
                balance = float(bill.get("Balance", 0) or 0)
                if due and balance > 0:
                    due_date = datetime.strptime(due, "%Y-%m-%d").date()
                    if defer_days:
                        due_date += timedelta(days=defer_days)
                    week_start = due_date - timedelta(days=due_date.weekday())
                    weekly[week_start.strftime("%Y-%m-%d")] += balance

        return dict(weekly)

    def _project_payroll(self) -> dict:
        weekly = defaultdict(float)
        approved = comm_db.list_commissions(status=CommissionStatus.APPROVED.value)
        total_commission = sum(c["commission_amount"] for c in approved)

        today = datetime.utcnow().date()
        biweekly_amount = total_commission / 2 if total_commission else 5000
        for week_num in range(FORECAST_WEEKS):
            if week_num % 2 == 0:
                week_start = today + timedelta(weeks=week_num)
                weekly[week_start.strftime("%Y-%m-%d")] += biweekly_amount

        return dict(weekly)

    def _project_job_billing(self) -> dict:
        weekly = defaultdict(float)
        jobs = jb.list_jobs(status="active")

        for job in jobs:
            if job.get("billing_behind"):
                gap = job["completion_percent"] - job.get("billed_percent", 0)
                catch_up = job["contract_amount"] * (gap / 100) * 0.5
                week_key = datetime.utcnow().date().strftime("%Y-%m-%d")
                weekly[week_key] += catch_up

        return dict(weekly)

    def _seasonal_recommendation(self, current_season: str, seasonal: dict) -> str:
        slowest = min(seasonal.items(), key=lambda x: x[1]["revenue"])[0] if seasonal else None
        if current_season == slowest:
            return (
                f"{current_season.title()} is historically slow — "
                "defer non-essential AP, accelerate AR collections, and build cash reserves"
            )
        return f"{current_season.title()} season — monitor cash weekly and maintain AP payment schedule"
