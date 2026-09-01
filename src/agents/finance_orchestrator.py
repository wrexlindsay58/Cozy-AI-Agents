import logging
from datetime import datetime
from src.db import event_bus as bus
from src.db.event_bus import EventStatus
from src.agents.approval_gateway_agent import ApprovalGatewayAgent
from src.agents.controller_agent import ControllerAgent
from src.agents.ar_agent import ARAgent
from src.agents.progress_billing_agent import ProgressBillingAgent
from src.agents.ap_agent import APAgent
from src.agents.sub_compliance_agent import SubComplianceAgent
from src.agents.job_costing_agent import JobCostingAgent
from src.agents.change_order_agent import ChangeOrderAgent
from src.agents.commission_agent import CommissionAgent
from src.agents.payroll_agent import PayrollAgent
from src.agents.profitability_agent import ProfitabilityAgent
from src.agents.cash_flow_agent import CashFlowAgent

logger = logging.getLogger(__name__)

PRIORITY = {
    "overdue_ar": 100,
    "cash_alert": 90,
    "variance_alert": 80,
    "bill_payment": 75,
    "bill_intake": 70,
    "change_order": 60,
    "job_milestone": 55,
    "commission": 50,
    "payroll": 50,
    "compliance": 45,
    "collections": 40,
    "reconciliation": 35,
    "reporting": 30,
    "default": 25,
}

SCHEDULED_JOBS = {
    "daily_close": {
        "description": "Daily reconciliation and data quality check",
        "agents": ["controller"],
    },
    "weekly_ar_aging": {
        "description": "Weekly AR aging review and collections cycle",
        "agents": ["ar"],
    },
    "daily_dashboard": {
        "description": "Push profitability dashboard to Google Chat",
        "agents": ["profitability"],
    },
    "cash_alert": {
        "description": "Check cash position and push alerts if needed",
        "agents": ["cash_flow"],
    },
    "variance_check": {
        "description": "Check job budget variance alerts",
        "agents": ["job_costing"],
    },
    "compliance_check": {
        "description": "Check expiring COI and non-compliant subs",
        "agents": ["sub_compliance"],
    },
}


class FinanceOrchestrator:
    """Routes all financial events to specialist agents with priority, dedup, and policy enforcement."""

    def __init__(self):
        self.approval_gateway = ApprovalGatewayAgent()
        self.controller = ControllerAgent()
        self.ar = ARAgent()
        self.progress_billing = ProgressBillingAgent()
        self.ap = APAgent()
        self.sub_compliance = SubComplianceAgent()
        self.job_costing = JobCostingAgent()
        self.change_order = ChangeOrderAgent()
        self.commission = CommissionAgent()
        self.payroll = PayrollAgent()
        self.profitability = ProfitabilityAgent()
        self.cash_flow = CashFlowAgent()

    def handle_event(
        self,
        event_type: str,
        source: str,
        payload: dict,
        priority: int = None,
        idempotency_key: str = None,
    ) -> dict:
        """Main entry point — log event, deduplicate, route to specialist."""
        prio = priority or PRIORITY.get(event_type.split(".")[0], PRIORITY["default"])
        event = bus.create_event(event_type, source, payload, prio, idempotency_key)

        if event.get("duplicate"):
            logger.info(f"Duplicate event skipped: {event_type} from {source}")
            return {"status": "duplicate", "event": event}

        bus.update_event(event["id"], status=EventStatus.PROCESSING.value)

        try:
            conflict = self._detect_conflicts(event_type, payload)
            if conflict:
                bus.update_event(
                    event["id"],
                    status=EventStatus.BLOCKED.value,
                    conflict_detected=True,
                    result=conflict,
                    error_message=conflict.get("message"),
                )
                return {"status": "blocked", "conflict": conflict, "event_id": event["id"]}

            result, agent_name = self._route(event_type, payload)

            policy = self._enforce_policy(event_type, payload, result)
            if policy.get("blocked"):
                bus.update_event(
                    event["id"],
                    status=EventStatus.BLOCKED.value,
                    policy_blocked=True,
                    routed_agent=agent_name,
                    result=result,
                    error_message=policy.get("reason"),
                )
                return {"status": "policy_blocked", "policy": policy, "event_id": event["id"]}

            self._handoff(event_type, payload, result)

            bus.update_event(
                event["id"],
                status=EventStatus.COMPLETED.value,
                routed_agent=agent_name,
                result=result,
            )
            return {
                "status": "completed",
                "event_id": event["id"],
                "routed_agent": agent_name,
                "result": result,
            }

        except Exception as e:
            logger.error(f"Event processing failed ({event_type}): {e}")
            bus.update_event(
                event["id"],
                status=EventStatus.FAILED.value,
                error_message=str(e),
            )
            return {"status": "failed", "error": str(e), "event_id": event["id"]}

    def handle_email(self, email: dict, triage: dict = None) -> dict:
        """Route a financial email through the orchestrator."""
        category = (triage or {}).get("category", "BILL")
        event_type = f"email.{category.lower()}"
        priority = self._email_priority(category, triage)
        return self.handle_event(
            event_type=event_type,
            source="email",
            payload={"email": email, "triage": triage or {}},
            priority=priority,
            idempotency_key=f"email:{email.get('id', '')}",
        )

    def handle_billcom_webhook(self, payload: dict) -> dict:
        event_name = payload.get("eventType", payload.get("type", "unknown"))
        event_type = f"billcom.{event_name.lower()}"
        return self.handle_event(
            event_type=event_type,
            source="billcom",
            payload=payload,
            priority=PRIORITY.get("bill_payment", 75),
            idempotency_key=payload.get("id") or payload.get("eventId"),
        )

    def handle_qbo_webhook(self, payload: dict) -> dict:
        entity = payload.get("name", payload.get("entityName", "unknown"))
        operation = payload.get("operation", "update")
        event_type = f"qbo.{entity.lower()}.{operation.lower()}"
        return self.handle_event(
            event_type=event_type,
            source="qbo",
            payload=payload,
            priority=PRIORITY.get("reconciliation", 35),
            idempotency_key=payload.get("id") or payload.get("eventId"),
        )

    def handle_bamboohr_webhook(self, payload: dict) -> dict:
        event_name = payload.get("action", payload.get("type", "unknown"))
        event_type = f"bamboohr.{event_name.lower()}"
        return self.handle_event(
            event_type=event_type,
            source="bamboohr",
            payload=payload,
            priority=PRIORITY.get("payroll", 50),
            idempotency_key=payload.get("id"),
        )

    def handle_job_event(self, job_id: str, event_name: str, payload: dict = None) -> dict:
        """Handle job lifecycle events (completion, milestone, cancellation)."""
        event_type = f"job.{event_name.lower()}"
        data = {"job_id": job_id, "event_name": event_name, **(payload or {})}
        priority = PRIORITY.get("job_milestone" if "milestone" in event_name else "commission", 55)
        return self.handle_event(
            event_type=event_type,
            source="job_system",
            payload=data,
            priority=priority,
            idempotency_key=f"job:{job_id}:{event_name}",
        )

    def run_scheduled_job(self, job_name: str) -> dict:
        """Run a named scheduled job across relevant agents."""
        if job_name not in SCHEDULED_JOBS:
            return {"error": f"Unknown scheduled job: {job_name}", "available": list(SCHEDULED_JOBS.keys())}

        return self.handle_event(
            event_type=f"scheduled.{job_name}",
            source="scheduler",
            payload={"job_name": job_name},
            priority=PRIORITY.get("reporting", 30),
            idempotency_key=f"scheduled:{job_name}:{datetime.utcnow().strftime('%Y-%m-%d')}",
        )

    def run_all_scheduled_jobs(self) -> dict:
        results = {}
        for job_name in SCHEDULED_JOBS:
            results[job_name] = self.run_scheduled_job(job_name)
        return {"jobs_run": len(results), "results": results}

    def get_event_queue(self, limit: int = 20) -> list[dict]:
        return bus.get_pending_events(limit)

    def get_event_history(self, limit: int = 50) -> list[dict]:
        return bus.list_events(limit=limit)

    def get_status(self) -> dict:
        pending = bus.list_events(status=EventStatus.PENDING.value, limit=100)
        recent = bus.list_events(limit=10)
        failed = bus.list_events(status=EventStatus.FAILED.value, limit=10)

        return {
            "orchestrator": "active",
            "agents_registered": 12,
            "pending_events": len(pending),
            "recent_events": len(recent),
            "failed_events": len(failed),
            "scheduled_jobs": list(SCHEDULED_JOBS.keys()),
            "priority_levels": PRIORITY,
        }

    def _route(self, event_type: str, payload: dict) -> tuple[dict, str]:
        """Route event to the appropriate specialist agent."""
        et = event_type.lower()

        if et.startswith("email."):
            return self._route_email(payload)

        if et.startswith("billcom."):
            return self._route_billcom(payload)

        if et.startswith("qbo."):
            return self._route_qbo(payload)

        if et.startswith("bamboohr."):
            return self._route_bamboohr(payload)

        if et.startswith("job."):
            return self._route_job(payload)

        if et.startswith("scheduled."):
            return self._route_scheduled(payload)

        return {"message": f"No handler for {event_type}"}, "orchestrator"

    def _route_email(self, payload: dict) -> tuple[dict, str]:
        email = payload.get("email", {})
        triage = payload.get("triage", {})
        category = triage.get("category", "BILL")

        if category in ("BILL", "VENDOR_DOC", "RECEIPT"):
            return self.ap.process_bill_from_email(email), "ap_agent"

        if category == "CHANGE_ORDER":
            return self.change_order.intake_from_email(email), "change_order_agent"

        if category == "INVOICE":
            return self.ar.match_payments(), "ar_agent"

        approval = self.approval_gateway.submit(
            approval_type=category.lower(),
            title=f"{email.get('subject', 'Financial item')} — from {email.get('sender', 'unknown')}",
            description=(email.get("body") or "")[:500],
            agent_name="finance_orchestrator",
        )
        return {"approval": approval}, "approval_gateway"

    def _route_billcom(self, payload: dict) -> tuple[dict, str]:
        event_type = payload.get("eventType", payload.get("type", "")).lower()

        if "payment" in event_type and "complet" in event_type:
            return {"status": "payment_completed", "payload": payload}, "ap_agent"

        if "bill" in event_type and "approv" in event_type:
            bill_id = payload.get("billId", payload.get("id"))
            job_ref = payload.get("jobReference")
            if job_ref:
                from src.db import job_billing as jb
                jobs = jb.list_jobs()
                matched = next((j for j in jobs if job_ref.lower() in j["name"].lower()), None)
                if matched:
                    amount = float(payload.get("amount", 0))
                    self.job_costing.allocate_ap_cost(
                        matched["id"], amount,
                        payload.get("description", "Bill approved"),
                        bill_id or "",
                    )
            return {"status": "bill_approved", "bill_id": bill_id}, "ap_agent"

        return self.ap.get_ap_summary(), "ap_agent"

    def _route_qbo(self, payload: dict) -> tuple[dict, str]:
        entity = payload.get("name", payload.get("entityName", "")).lower()
        operation = payload.get("operation", "").lower()

        if entity == "payment" and operation in ("create", "update"):
            return self.ar.match_payments(), "ar_agent"

        if entity == "invoice":
            return self.ar.get_ar_aging(), "ar_agent"

        return self.controller.run_reconciliation_check(), "controller_agent"

    def _route_bamboohr(self, payload: dict) -> tuple[dict, str]:
        action = payload.get("action", payload.get("type", "")).lower()

        if "payroll" in action:
            period = payload.get("period", datetime.utcnow().strftime("%Y-%m"))
            return self.payroll.reconcile_payroll_jes(period), "payroll_agent"

        if "time" in action or "timesheet" in action:
            period = datetime.utcnow().strftime("%Y-%m")
            return {
                "allocations": self.payroll.allocate_labor_costs(period),
            }, "payroll_agent"

        return self.payroll.get_employee_roster(), "payroll_agent"

    def _route_job(self, payload: dict) -> tuple[dict, str]:
        job_id = payload.get("job_id")
        event_name = payload.get("event_name", "")

        if "complet" in event_name:
            commission_result = self.commission.accrue_at_trigger(job_id, "completion")
            billing_result = self.progress_billing.invoice_final(job_id)
            return {
                "commissions": commission_result,
                "final_invoice": billing_result,
            }, "progress_billing_agent"

        if "milestone" in event_name:
            milestone = payload.get("milestone_name", "")
            commission_result = self.commission.accrue_at_trigger(job_id, "milestone")
            billing_result = self.progress_billing.invoice_milestone(job_id, milestone)
            return {
                "commissions": commission_result,
                "milestone_invoice": billing_result,
            }, "progress_billing_agent"

        if "cancel" in event_name:
            return self.commission.clawback(job_id, payload.get("reason", "Job cancelled")), "commission_agent"

        if "sign" in event_name:
            return self.commission.accrue_at_trigger(job_id, "signing"), "commission_agent"

        return self.job_costing.get_job_pnl(job_id), "job_costing_agent"

    def _route_scheduled(self, payload: dict) -> tuple[dict, str]:
        job_name = payload.get("job_name", "")

        if job_name == "daily_close":
            return {
                "reconciliation": self.controller.run_reconciliation_check(),
                "data_quality": self.controller.find_data_quality_issues(),
                "close_checklist": self.controller.get_close_checklist(),
            }, "controller_agent"

        if job_name == "weekly_ar_aging":
            return {
                "aging": self.ar.get_ar_aging(),
                "overdue": self.ar.get_overdue_invoices(),
                "collections": self.ar.run_collections_cycle(),
            }, "ar_agent"

        if job_name == "daily_dashboard":
            return self.profitability.push_dashboard_to_chat("daily"), "profitability_agent"

        if job_name == "cash_alert":
            return self.cash_flow.push_cash_alert_to_chat(), "cash_flow_agent"

        if job_name == "variance_check":
            alerts = self.job_costing.get_variance_alerts()
            return {"alerts": alerts, "count": len(alerts)}, "job_costing_agent"

        if job_name == "compliance_check":
            return {
                "dashboard": self.sub_compliance.get_dashboard(),
                "expiring": self.sub_compliance.list_expiring_coi(30),
                "non_compliant": self.sub_compliance.list_non_compliant(),
            }, "sub_compliance_agent"

        return {"error": f"Unknown job: {job_name}"}, "orchestrator"

    def _detect_conflicts(self, event_type: str, payload: dict) -> dict | None:
        """Detect cross-agent conflicts like duplicate bills."""
        if not event_type.startswith("email.") and not event_type.startswith("billcom."):
            return None

        email = payload.get("email", {})
        if email:
            vendor = payload.get("triage", {}).get("vendor") or ""
            body = email.get("body", "")
            if "invoice_number" in body.lower() or vendor:
                extracted = self.ap.extract_bill_from_text(
                    f"Subject: {email.get('subject', '')}\n{body}"
                )
                inv_num = extracted.get("invoice_number")
                vendor_name = extracted.get("vendor", vendor)
                if inv_num and vendor_name:
                    from src.tools import billcom_tools as billcom
                    if billcom.is_configured():
                        bills = billcom.list_bills(max_results=50)
                        for bill in bills:
                            bill_inv = bill.get("invoiceNumber", bill.get("invoice", {}).get("invoiceNumber", ""))
                            bill_vendor = bill.get("vendorName", "")
                            if (
                                inv_num and bill_inv
                                and inv_num.lower() == str(bill_inv).lower()
                                and vendor_name.lower() in bill_vendor.lower()
                            ):
                                return {
                                    "type": "duplicate_bill",
                                    "message": f"Bill {inv_num} from {vendor_name} may already exist in Bill.com",
                                    "existing_bill_id": bill.get("id"),
                                }
        return None

    def _enforce_policy(self, event_type: str, payload: dict, result: dict) -> dict:
        """Enforce permission tiers and business rules."""
        if event_type.startswith("email.") and "ap_result" not in result:
            triage = payload.get("triage", {})
            category = triage.get("category", "")
            if category in ("BILL", "VENDOR_DOC", "RECEIPT"):
                if result.get("blocked"):
                    return {
                        "blocked": True,
                        "reason": result.get("reason", "Subcontractor compliance check failed"),
                    }
                if result.get("status") == "compliance_blocked":
                    return {
                        "blocked": True,
                        "reason": "Payment blocked — subcontractor not compliant",
                    }

        if "payment" in event_type and result.get("status") == "approval_submitted":
            if not result.get("approval"):
                return {
                    "blocked": True,
                    "reason": "Payment proposal requires approval before execution",
                }

        return {"blocked": False}

    def _handoff(self, event_type: str, payload: dict, result: dict):
        """Agent-to-agent handoffs after primary routing."""
        if event_type.startswith("job.") and "complet" in event_type:
            job_id = payload.get("job_id")
            if job_id:
                self.cash_flow.analyze_job_affordability_by_id(job_id)

        if result.get("status") == "bill_approved":
            self.job_costing.get_variance_alerts()

        if event_type == "scheduled.weekly_ar_aging":
            overdue = result.get("overdue", [])
            if overdue and len(overdue) > 0:
                self.cash_flow.get_13_week_forecast()

    def _email_priority(self, category: str, triage: dict) -> int:
        if category == "INVOICE":
            return PRIORITY["overdue_ar"]
        if category in ("BILL", "VENDOR_DOC", "RECEIPT"):
            return PRIORITY["bill_intake"]
        if category == "CHANGE_ORDER":
            return PRIORITY["change_order"]
        return PRIORITY["default"]
