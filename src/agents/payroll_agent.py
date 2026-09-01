import logging
from datetime import datetime
from src.tools import bamboohr_tools as bamboo
from src.db import job_billing as jb
from src.db import job_costing as jc
from src.db import commissions as comm_db
from src.db import payroll as payroll_db
from src.db.payroll import PayrollRunStatus
from src.db.commissions import CommissionStatus
from src.agents.approval_gateway_agent import ApprovalGatewayAgent
from src.agents.job_costing_agent import JobCostingAgent

logger = logging.getLogger(__name__)

OVERTIME_THRESHOLD_HOURS = 40


class PayrollAgent:
    """Pre-validates payroll, allocates labor costs to jobs, and proposes payroll runs."""

    def __init__(self):
        self.approval_gateway = ApprovalGatewayAgent()
        self.job_costing = JobCostingAgent()

    def get_employee_roster(self) -> dict:
        if bamboo.is_configured():
            return bamboo.get_payroll_summary()
        return {
            "configured": False,
            "message": "BambooHR not configured — using local data only",
            "active_employees": 0,
            "employees": [],
        }

    def get_time_entries(self, period: str) -> list[dict]:
        start, end = bamboo.get_period_dates(period)
        if bamboo.is_configured():
            return bamboo.get_company_time_entries(start, end)
        return []

    def pre_validate_payroll(self, period: str = None) -> dict:
        """Validate payroll against job budgets and flag overtime."""
        if not period:
            period = datetime.utcnow().strftime("%Y-%m")

        flags = []
        time_entries = self.get_time_entries(period)

        employee_hours = {}
        for entry in time_entries:
            emp_id = entry.get("employee_id", "unknown")
            hours = float(entry.get("hours", entry.get("duration", 0)) or 0)
            employee_hours[emp_id] = employee_hours.get(emp_id, 0) + hours

        for emp_id, hours in employee_hours.items():
            if hours > OVERTIME_THRESHOLD_HOURS:
                flags.append({
                    "type": "overtime",
                    "severity": "high",
                    "employee_id": emp_id,
                    "hours": hours,
                    "message": f"Employee {emp_id} has {hours:.1f} hours (>{OVERTIME_THRESHOLD_HOURS} OT threshold)",
                })

        active_jobs = jb.list_jobs(status="active")
        for job in active_jobs:
            budget = jc.get_budget(job["id"])
            actuals = jc.get_actual_costs(job["id"])
            labor_budget = budget.get("labor", 0)
            labor_actual = actuals.get("labor", 0)
            if labor_budget > 0 and labor_actual > labor_budget:
                flags.append({
                    "type": "labor_over_budget",
                    "severity": "medium",
                    "job_id": job["id"],
                    "job_name": job["name"],
                    "budget": labor_budget,
                    "actual": labor_actual,
                    "message": f"{job['name']}: labor ${labor_actual:,.0f} exceeds budget ${labor_budget:,.0f}",
                })

        approved_commissions = comm_db.list_commissions(
            period=period, status=CommissionStatus.APPROVED.value,
        )
        total_commission = sum(c["commission_amount"] for c in approved_commissions)

        return {
            "period": period,
            "validation_status": "issues_found" if flags else "clean",
            "flag_count": len(flags),
            "flags": flags,
            "employee_count": len(employee_hours),
            "total_hours": sum(employee_hours.values()),
            "approved_commissions": len(approved_commissions),
            "total_commission": total_commission,
            "bamboohr_configured": bamboo.is_configured(),
        }

    def allocate_labor_costs(self, period: str, payroll_run_id: str = None) -> list[dict]:
        """Allocate labor costs from time entries to jobs via job costing."""
        start, end = bamboo.get_period_dates(period)
        allocations = []
        time_entries = self.get_time_entries(period)

        for entry in time_entries:
            hours = float(entry.get("hours", entry.get("duration", 0)) or 0)
            if hours <= 0:
                continue

            job_ref = entry.get("job", entry.get("project", entry.get("note", "")))
            if not job_ref:
                continue

            jobs = jb.list_jobs()
            matched = next(
                (j for j in jobs if job_ref.lower() in j["name"].lower()),
                None,
            )
            if not matched:
                continue

            hourly_rate = float(entry.get("payRate", entry.get("rate", 25)) or 25)
            labor_cost = bamboo.calculate_labor_cost(hours, hourly_rate)
            emp_name = entry.get("employee_name", "Unknown")

            self.job_costing.add_cost(
                matched["id"], "labor", labor_cost,
                description=f"Labor: {emp_name} ({hours:.1f}h)",
                source="payroll",
            )

            if payroll_run_id:
                alloc = payroll_db.add_allocation(
                    payroll_run_id=payroll_run_id,
                    employee_id=entry.get("employee_id", ""),
                    employee_name=emp_name,
                    job_id=matched["id"],
                    job_name=matched["name"],
                    hours=hours,
                    labor_cost=labor_cost,
                    period=period,
                )
                allocations.append(alloc)

        return allocations

    def receive_commissions(self, commission_ids: list[str]) -> dict:
        """Receive approved commissions from Commission Agent for payroll inclusion."""
        records = []
        total = 0.0
        for cid in commission_ids:
            rec = comm_db.get_commission(cid)
            if rec and rec["status"] == CommissionStatus.APPROVED.value:
                records.append(rec)
                total += rec["commission_amount"]
        return {
            "commission_count": len(records),
            "total_commission": total,
            "records": records,
        }

    def propose_payroll_run(self, period: str = None) -> dict:
        """Pre-validate and propose a payroll run for human approval in BambooHR."""
        if not period:
            period = datetime.utcnow().strftime("%Y-%m")

        validation = self.pre_validate_payroll(period)
        approved_commissions = comm_db.list_commissions(
            period=period, status=CommissionStatus.APPROVED.value,
        )
        commission_ids = [c["id"] for c in approved_commissions]
        total_commission = sum(c["commission_amount"] for c in approved_commissions)

        roster = self.get_employee_roster()
        employee_count = roster.get("active_employees", 0)

        run = payroll_db.create_payroll_run(
            period=period,
            total_commission=total_commission,
            employee_count=employee_count,
            validation_flags=validation["flags"],
            commission_ids=commission_ids,
            notes="Agent-prepared payroll run — human must execute in BambooHR",
        )

        approval = self.approval_gateway.submit(
            approval_type="payroll",
            title=f"Payroll run — {period} (${total_commission:,.2f} commissions)",
            description=self._format_payroll_description(validation, total_commission),
            amount=total_commission,
            payload={
                "action": "approve_payroll_run",
                "payroll_run_id": run["id"],
                "period": period,
                "commission_ids": commission_ids,
            },
            agent_name="payroll_agent",
        )

        payroll_db.update_payroll_run_status(run["id"], PayrollRunStatus.PENDING_APPROVAL.value)

        return {
            "status": "approval_submitted",
            "payroll_run": run,
            "validation": validation,
            "approval": approval,
        }

    def approve_payroll_run(self, run_id: str, approved_by: str) -> dict:
        """Mark payroll run approved and mark commissions as paid."""
        run = payroll_db.get_payroll_run(run_id)
        if not run:
            return {"error": "Payroll run not found"}

        payroll_db.update_payroll_run_status(run_id, PayrollRunStatus.APPROVED.value, approved_by)
        self.allocate_labor_costs(run["period"], payroll_run_id=run_id)

        paid = comm_db.mark_commissions_paid(run["commission_ids"], run_id)
        payroll_db.update_payroll_run_status(run_id, PayrollRunStatus.COMPLETED.value)

        return {
            "status": "approved",
            "payroll_run_id": run_id,
            "approved_by": approved_by,
            "commissions_paid": len(paid),
            "message": "Payroll approved — human must execute in BambooHR UI",
        }

    def reconcile_payroll_jes(self, period: str = None) -> dict:
        """Check that BambooHR payroll JEs appear in QBO (read-only reconciliation)."""
        from src.tools import quickbooks_tools as qbo

        if not period:
            period = datetime.utcnow().strftime("%Y-%m")

        issues = []
        if not qbo.is_configured():
            issues.append({
                "type": "qbo_not_configured",
                "message": "QuickBooks not configured — cannot reconcile payroll JEs",
            })

        runs = payroll_db.list_payroll_runs(period=period, status=PayrollRunStatus.COMPLETED.value)

        return {
            "period": period,
            "status": "issues_found" if issues else "pending_verification",
            "completed_runs": len(runs),
            "issues": issues,
            "message": "Verify BambooHR payroll JEs posted to QBO for this period",
        }

    def get_summary(self) -> dict:
        runs = payroll_db.list_payroll_runs()
        pending = [r for r in runs if r["status"] == PayrollRunStatus.PENDING_APPROVAL.value]
        completed = [r for r in runs if r["status"] == PayrollRunStatus.COMPLETED.value]

        return {
            "bamboohr_configured": bamboo.is_configured(),
            "total_runs": len(runs),
            "pending_approval": len(pending),
            "completed_runs": len(completed),
            "employee_count": self.get_employee_roster().get("active_employees", 0),
        }

    def _format_payroll_description(self, validation: dict, total_commission: float) -> str:
        lines = [
            f"Period: {validation['period']}",
            f"Employees: {validation['employee_count']}",
            f"Total hours: {validation['total_hours']:.1f}",
            f"Approved commissions: ${total_commission:,.2f}",
        ]
        if validation["flags"]:
            lines.append(f"\nValidation flags ({validation['flag_count']}):")
            for flag in validation["flags"][:5]:
                lines.append(f"  [{flag['severity']}] {flag['message']}")
        lines.append("\nHuman must run payroll in BambooHR after approval.")
        return "\n".join(lines)
