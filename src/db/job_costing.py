import datetime
import enum
import uuid
from sqlalchemy import Column, String, DateTime, Float, Text, ForeignKey
from src.db.sqlite import Base, SessionLocal, engine

COST_CATEGORIES = ["labor", "materials", "subcontractor", "permits", "overhead", "other"]

VARIANCE_THRESHOLDS = [
    ("warning", 0.80),
    ("critical", 1.00),
    ("over_budget", 1.20),
]


class JobBudget(Base):
    __tablename__ = "job_budgets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    category = Column(String, nullable=False)
    estimated_amount = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class JobCost(Base):
    __tablename__ = "job_costs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    category = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(Text)
    source = Column(String, default="manual")  # manual, ap, qbo, payroll
    reference_id = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


def init_job_costing_db():
    JobBudget.__table__.create(bind=engine, checkfirst=True)
    JobCost.__table__.create(bind=engine, checkfirst=True)


def set_budget(job_id: str, estimates: dict) -> dict:
    """Set or update budget estimates. estimates: {labor: 10000, materials: 5000, ...}"""
    session = SessionLocal()
    for category, amount in estimates.items():
        if category not in COST_CATEGORIES:
            continue
        existing = session.query(JobBudget).filter(
            JobBudget.job_id == job_id,
            JobBudget.category == category,
        ).first()
        if existing:
            existing.estimated_amount = float(amount)
            existing.updated_at = datetime.datetime.utcnow()
        else:
            session.add(JobBudget(job_id=job_id, category=category, estimated_amount=float(amount)))
    session.commit()
    session.close()
    return get_budget(job_id)


def get_budget(job_id: str) -> dict:
    session = SessionLocal()
    rows = session.query(JobBudget).filter(JobBudget.job_id == job_id).all()
    session.close()
    budget = {cat: 0.0 for cat in COST_CATEGORIES}
    for r in rows:
        budget[r.category] = r.estimated_amount
    budget["total"] = sum(budget.values())
    return budget


def add_cost(
    job_id: str,
    category: str,
    amount: float,
    description: str = "",
    source: str = "manual",
    reference_id: str = None,
) -> dict:
    if category not in COST_CATEGORIES:
        category = "other"
    session = SessionLocal()
    cost = JobCost(
        job_id=job_id,
        category=category,
        amount=amount,
        description=description,
        source=source,
        reference_id=reference_id,
    )
    session.add(cost)
    session.commit()
    session.close()
    return get_actual_costs(job_id)


def get_actual_costs(job_id: str) -> dict:
    session = SessionLocal()
    rows = session.query(JobCost).filter(JobCost.job_id == job_id).all()
    session.close()
    actuals = {cat: 0.0 for cat in COST_CATEGORIES}
    for r in rows:
        actuals[r.category] += r.amount
    actuals["total"] = sum(actuals.values())
    return actuals


def list_cost_entries(job_id: str) -> list[dict]:
    session = SessionLocal()
    rows = session.query(JobCost).filter(
        JobCost.job_id == job_id
    ).order_by(JobCost.created_at.desc()).all()
    result = [{
        "id": r.id,
        "category": r.category,
        "amount": r.amount,
        "description": r.description,
        "source": r.source,
        "reference_id": r.reference_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
    session.close()
    return result


def get_variance(job_id: str, contract_amount: float) -> dict:
    budget = get_budget(job_id)
    actuals = get_actual_costs(job_id)
    total_budget = budget["total"] or contract_amount * 0.7  # default 70% cost ratio if no budget set
    total_actual = actuals["total"]
    pct_used = (total_actual / total_budget) if total_budget > 0 else 0

    alert_level = None
    for level, threshold in VARIANCE_THRESHOLDS:
        if pct_used >= threshold:
            alert_level = level

    by_category = {}
    for cat in COST_CATEGORIES:
        est = budget.get(cat, 0)
        act = actuals.get(cat, 0)
        by_category[cat] = {
            "estimated": est,
            "actual": act,
            "variance": act - est,
            "pct_used": (act / est) if est > 0 else None,
        }

    return {
        "total_budget": total_budget,
        "total_actual": total_actual,
        "variance": total_actual - total_budget,
        "pct_used": round(pct_used * 100, 1),
        "alert_level": alert_level,
        "by_category": by_category,
    }
