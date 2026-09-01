import datetime
import enum
import json
import uuid
from sqlalchemy import Column, String, DateTime, Float, Text, Boolean, ForeignKey
from src.db.sqlite import Base, SessionLocal, engine

DEFAULT_RULES = [
    {
        "name": "Standard Sale Commission",
        "rule_type": "percent_of_sale",
        "rate": 5.0,
        "trigger": "completion",
        "clawback_days": 90,
    },
    {
        "name": "Signing Bonus",
        "rule_type": "percent_of_sale",
        "rate": 2.0,
        "trigger": "signing",
        "clawback_days": 90,
    },
    {
        "name": "Margin-Based (Large Jobs)",
        "rule_type": "percent_of_margin",
        "rate": 10.0,
        "trigger": "completion",
        "clawback_days": 90,
        "min_contract": 75000,
    },
    {
        "name": "Tiered by Job Size",
        "rule_type": "tiered",
        "tiers": [
            {"max_amount": 25000, "rate": 3.0},
            {"max_amount": 75000, "rate": 5.0},
            {"max_amount": None, "rate": 7.0},
        ],
        "trigger": "completion",
        "clawback_days": 90,
    },
]


class CommissionStatus(str, enum.Enum):
    ACCRUED = "accrued"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PAID = "paid"
    CLAWED_BACK = "clawed_back"
    DISPUTED = "disputed"


class CommissionRule(Base):
    __tablename__ = "commission_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    rule_type = Column(String, nullable=False)  # percent_of_sale, percent_of_margin, tiered, split
    rate = Column(Float)
    tiers_json = Column(Text)
    trigger = Column(String, default="completion")  # signing, milestone, completion
    clawback_days = Column(Float, default=90)
    min_contract = Column(Float)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class JobAttribution(Base):
    __tablename__ = "job_attributions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False, unique=True)
    sales_rep_id = Column(String)
    sales_rep_name = Column(String)
    lead_setter_id = Column(String)
    lead_setter_name = Column(String)
    sales_rep_split = Column(Float, default=100.0)  # % of commission to sales rep
    lead_setter_split = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CommissionRecord(Base):
    __tablename__ = "commission_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    rule_id = Column(String, ForeignKey("commission_rules.id"))
    rep_id = Column(String)
    rep_name = Column(String, nullable=False)
    rep_role = Column(String, default="sales_rep")  # sales_rep, lead_setter
    trigger_event = Column(String, nullable=False)
    base_amount = Column(Float, nullable=False)
    commission_rate = Column(Float)
    commission_amount = Column(Float, nullable=False)
    status = Column(String, default=CommissionStatus.ACCRUED.value)
    period = Column(String)  # YYYY-MM
    notes = Column(Text)
    clawback_reason = Column(Text)
    payroll_run_id = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    paid_at = Column(DateTime)


def init_commission_db():
    CommissionRule.__table__.create(bind=engine, checkfirst=True)
    JobAttribution.__table__.create(bind=engine, checkfirst=True)
    CommissionRecord.__table__.create(bind=engine, checkfirst=True)
    _seed_default_rules()


def _seed_default_rules():
    session = SessionLocal()
    if session.query(CommissionRule).count() == 0:
        for rule in DEFAULT_RULES:
            session.add(CommissionRule(
                name=rule["name"],
                rule_type=rule["rule_type"],
                rate=rule.get("rate"),
                tiers_json=json.dumps(rule["tiers"]) if rule.get("tiers") else None,
                trigger=rule["trigger"],
                clawback_days=rule.get("clawback_days", 90),
                min_contract=rule.get("min_contract"),
            ))
        session.commit()
    session.close()


def _serialize_rule(rule: CommissionRule) -> dict:
    tiers = json.loads(rule.tiers_json) if rule.tiers_json else None
    return {
        "id": rule.id,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "rate": rule.rate,
        "tiers": tiers,
        "trigger": rule.trigger,
        "clawback_days": rule.clawback_days,
        "min_contract": rule.min_contract,
        "active": rule.active,
    }


def _serialize_record(rec: CommissionRecord) -> dict:
    return {
        "id": rec.id,
        "job_id": rec.job_id,
        "rule_id": rec.rule_id,
        "rep_id": rec.rep_id,
        "rep_name": rec.rep_name,
        "rep_role": rec.rep_role,
        "trigger_event": rec.trigger_event,
        "base_amount": rec.base_amount,
        "commission_rate": rec.commission_rate,
        "commission_amount": rec.commission_amount,
        "status": rec.status,
        "period": rec.period,
        "notes": rec.notes,
        "clawback_reason": rec.clawback_reason,
        "payroll_run_id": rec.payroll_run_id,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "paid_at": rec.paid_at.isoformat() if rec.paid_at else None,
    }


def list_rules(active_only: bool = True) -> list[dict]:
    session = SessionLocal()
    query = session.query(CommissionRule)
    if active_only:
        query = query.filter(CommissionRule.active == True)
    rules = query.all()
    result = [_serialize_rule(r) for r in rules]
    session.close()
    return result


def get_rule(rule_id: str) -> dict | None:
    session = SessionLocal()
    rule = session.query(CommissionRule).filter(CommissionRule.id == rule_id).first()
    result = _serialize_rule(rule) if rule else None
    session.close()
    return result


def set_attribution(
    job_id: str,
    sales_rep_id: str = None,
    sales_rep_name: str = None,
    lead_setter_id: str = None,
    lead_setter_name: str = None,
    sales_rep_split: float = 100.0,
    lead_setter_split: float = 0.0,
) -> dict:
    session = SessionLocal()
    existing = session.query(JobAttribution).filter(JobAttribution.job_id == job_id).first()
    if existing:
        if sales_rep_id is not None:
            existing.sales_rep_id = sales_rep_id
        if sales_rep_name is not None:
            existing.sales_rep_name = sales_rep_name
        if lead_setter_id is not None:
            existing.lead_setter_id = lead_setter_id
        if lead_setter_name is not None:
            existing.lead_setter_name = lead_setter_name
        existing.sales_rep_split = sales_rep_split
        existing.lead_setter_split = lead_setter_split
        attr = existing
    else:
        attr = JobAttribution(
            job_id=job_id,
            sales_rep_id=sales_rep_id,
            sales_rep_name=sales_rep_name,
            lead_setter_id=lead_setter_id,
            lead_setter_name=lead_setter_name,
            sales_rep_split=sales_rep_split,
            lead_setter_split=lead_setter_split,
        )
        session.add(attr)
    session.commit()
    result = _serialize_attribution(attr)
    session.close()
    return result


def get_attribution(job_id: str) -> dict | None:
    session = SessionLocal()
    attr = session.query(JobAttribution).filter(JobAttribution.job_id == job_id).first()
    result = _serialize_attribution(attr) if attr else None
    session.close()
    return result


def _serialize_attribution(attr: JobAttribution) -> dict:
    return {
        "id": attr.id,
        "job_id": attr.job_id,
        "sales_rep_id": attr.sales_rep_id,
        "sales_rep_name": attr.sales_rep_name,
        "lead_setter_id": attr.lead_setter_id,
        "lead_setter_name": attr.lead_setter_name,
        "sales_rep_split": attr.sales_rep_split,
        "lead_setter_split": attr.lead_setter_split,
    }


def create_commission_record(
    job_id: str,
    rep_name: str,
    trigger_event: str,
    base_amount: float,
    commission_amount: float,
    rule_id: str = None,
    rep_id: str = None,
    rep_role: str = "sales_rep",
    commission_rate: float = None,
    period: str = None,
    notes: str = None,
) -> dict:
    if not period:
        period = datetime.datetime.utcnow().strftime("%Y-%m")
    session = SessionLocal()
    rec = CommissionRecord(
        job_id=job_id,
        rule_id=rule_id,
        rep_id=rep_id,
        rep_name=rep_name,
        rep_role=rep_role,
        trigger_event=trigger_event,
        base_amount=base_amount,
        commission_rate=commission_rate,
        commission_amount=commission_amount,
        period=period,
        notes=notes,
    )
    session.add(rec)
    session.commit()
    result = _serialize_record(rec)
    session.close()
    return result


def get_commission(co_id: str) -> dict | None:
    session = SessionLocal()
    rec = session.query(CommissionRecord).filter(CommissionRecord.id == co_id).first()
    result = _serialize_record(rec) if rec else None
    session.close()
    return result


def list_commissions(
    job_id: str = None,
    rep_id: str = None,
    period: str = None,
    status: str = None,
) -> list[dict]:
    session = SessionLocal()
    query = session.query(CommissionRecord)
    if job_id:
        query = query.filter(CommissionRecord.job_id == job_id)
    if rep_id:
        query = query.filter(CommissionRecord.rep_id == rep_id)
    if period:
        query = query.filter(CommissionRecord.period == period)
    if status:
        query = query.filter(CommissionRecord.status == status)
    records = query.order_by(CommissionRecord.created_at.desc()).all()
    result = [_serialize_record(r) for r in records]
    session.close()
    return result


def update_commission_status(
    commission_id: str,
    status: str,
    clawback_reason: str = None,
    payroll_run_id: str = None,
) -> dict | None:
    session = SessionLocal()
    rec = session.query(CommissionRecord).filter(CommissionRecord.id == commission_id).first()
    if not rec:
        session.close()
        return None
    rec.status = status
    if clawback_reason:
        rec.clawback_reason = clawback_reason
    if payroll_run_id:
        rec.payroll_run_id = payroll_run_id
    if status == CommissionStatus.PAID.value:
        rec.paid_at = datetime.datetime.utcnow()
    session.commit()
    result = _serialize_record(rec)
    session.close()
    return result


def mark_commissions_paid(commission_ids: list[str], payroll_run_id: str) -> list[dict]:
    results = []
    for cid in commission_ids:
        rec = update_commission_status(cid, CommissionStatus.PAID.value, payroll_run_id=payroll_run_id)
        if rec:
            results.append(rec)
    return results
