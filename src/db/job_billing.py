import datetime
import enum
import json
import uuid
from sqlalchemy import Column, String, DateTime, Float, Text, Boolean, ForeignKey
from src.db.sqlite import Base, SessionLocal, engine


class JobStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MilestoneStatus(str, enum.Enum):
    PENDING = "pending"
    INVOICED = "invoiced"
    PAID = "paid"


DEFAULT_MILESTONES = [
    {"name": "demo_complete", "label": "Demo Complete", "percentage": 15},
    {"name": "rough_in", "label": "Rough-In Complete", "percentage": 25},
    {"name": "finish", "label": "Finish Work Complete", "percentage": 25},
]


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    customer_name = Column(String, nullable=False)
    customer_email = Column(String)
    contract_amount = Column(Float, nullable=False)
    deposit_percent = Column(Float, default=40.0)
    retainage_percent = Column(Float, default=10.0)
    completion_percent = Column(Float, default=0.0)
    qbo_customer_id = Column(String)
    qbo_project_id = Column(String)
    status = Column(String, default=JobStatus.ACTIVE.value)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class BillingMilestone(Base):
    __tablename__ = "billing_milestones"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    name = Column(String, nullable=False)
    label = Column(String, nullable=False)
    percentage = Column(Float, nullable=False)
    amount = Column(Float)
    status = Column(String, default=MilestoneStatus.PENDING.value)
    qbo_invoice_id = Column(String)
    invoiced_at = Column(DateTime)
    paid_at = Column(DateTime)


class JobDeposit(Base):
    __tablename__ = "job_deposits"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    amount = Column(Float, nullable=False)
    percentage = Column(Float, nullable=False)
    status = Column(String, default=MilestoneStatus.PENDING.value)
    qbo_invoice_id = Column(String)
    invoiced_at = Column(DateTime)
    received_at = Column(DateTime)


def init_job_billing_db():
    Job.__table__.create(bind=engine, checkfirst=True)
    BillingMilestone.__table__.create(bind=engine, checkfirst=True)
    JobDeposit.__table__.create(bind=engine, checkfirst=True)


def _serialize_job(job: Job, milestones=None, deposit=None) -> dict:
    billed_pct = sum(m.percentage for m in (milestones or []) if m.status != MilestoneStatus.PENDING.value)
    if deposit and deposit.status != MilestoneStatus.PENDING.value:
        billed_pct += deposit.percentage
    return {
        "id": job.id,
        "name": job.name,
        "customer_name": job.customer_name,
        "customer_email": job.customer_email,
        "contract_amount": job.contract_amount,
        "deposit_percent": job.deposit_percent,
        "retainage_percent": job.retainage_percent,
        "completion_percent": job.completion_percent,
        "billed_percent": billed_pct,
        "billing_behind": job.completion_percent > billed_pct + 10,
        "qbo_customer_id": job.qbo_customer_id,
        "qbo_project_id": job.qbo_project_id,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def create_job(
    name: str,
    customer_name: str,
    contract_amount: float,
    customer_email: str = None,
    deposit_percent: float = None,
    retainage_percent: float = None,
    qbo_customer_id: str = None,
    qbo_project_id: str = None,
) -> dict:
    from src.config import DEFAULT_DEPOSIT_PERCENT, DEFAULT_RETAINAGE_PERCENT

    session = SessionLocal()
    job = Job(
        name=name,
        customer_name=customer_name,
        customer_email=customer_email,
        contract_amount=contract_amount,
        deposit_percent=deposit_percent or DEFAULT_DEPOSIT_PERCENT,
        retainage_percent=retainage_percent or DEFAULT_RETAINAGE_PERCENT,
        qbo_customer_id=qbo_customer_id,
        qbo_project_id=qbo_project_id,
    )
    session.add(job)
    session.flush()

    deposit_amount = contract_amount * (job.deposit_percent / 100)
    deposit = JobDeposit(
        job_id=job.id,
        amount=deposit_amount,
        percentage=job.deposit_percent,
    )
    session.add(deposit)

    for ms in DEFAULT_MILESTONES:
        milestone = BillingMilestone(
            job_id=job.id,
            name=ms["name"],
            label=ms["label"],
            percentage=ms["percentage"],
            amount=contract_amount * (ms["percentage"] / 100),
        )
        session.add(milestone)

    session.commit()
    result = get_job(job.id)
    session.close()
    return result


def get_job(job_id: str) -> dict | None:
    session = SessionLocal()
    job = session.query(Job).filter(Job.id == job_id).first()
    if not job:
        session.close()
        return None

    milestones = session.query(BillingMilestone).filter(
        BillingMilestone.job_id == job_id
    ).order_by(BillingMilestone.percentage).all()
    deposit = session.query(JobDeposit).filter(JobDeposit.job_id == job_id).first()

    result = _serialize_job(job, milestones, deposit)
    result["deposit"] = _serialize_deposit(deposit) if deposit else None
    result["milestones"] = [_serialize_milestone(m) for m in milestones]
    session.close()
    return result


def list_jobs(status: str = None) -> list[dict]:
    session = SessionLocal()
    query = session.query(Job)
    if status:
        query = query.filter(Job.status == status)
    jobs = query.order_by(Job.created_at.desc()).all()
    result = []
    for job in jobs:
        milestones = session.query(BillingMilestone).filter(BillingMilestone.job_id == job.id).all()
        deposit = session.query(JobDeposit).filter(JobDeposit.job_id == job.id).first()
        result.append(_serialize_job(job, milestones, deposit))
    session.close()
    return result


def update_job_completion(job_id: str, completion_percent: float) -> dict | None:
    session = SessionLocal()
    job = session.query(Job).filter(Job.id == job_id).first()
    if not job:
        session.close()
        return None
    job.completion_percent = completion_percent
    job.updated_at = datetime.datetime.utcnow()
    session.commit()
    session.close()
    return get_job(job_id)


def mark_milestone_invoiced(milestone_id: str, qbo_invoice_id: str) -> dict | None:
    session = SessionLocal()
    milestone = session.query(BillingMilestone).filter(BillingMilestone.id == milestone_id).first()
    if not milestone:
        session.close()
        return None
    milestone.status = MilestoneStatus.INVOICED.value
    milestone.qbo_invoice_id = qbo_invoice_id
    milestone.invoiced_at = datetime.datetime.utcnow()
    session.commit()
    job_id = milestone.job_id
    session.close()
    return get_job(job_id)


def mark_deposit_invoiced(job_id: str, qbo_invoice_id: str) -> dict | None:
    session = SessionLocal()
    deposit = session.query(JobDeposit).filter(JobDeposit.job_id == job_id).first()
    if not deposit:
        session.close()
        return None
    deposit.status = MilestoneStatus.INVOICED.value
    deposit.qbo_invoice_id = qbo_invoice_id
    deposit.invoiced_at = datetime.datetime.utcnow()
    session.commit()
    session.close()
    return get_job(job_id)


def mark_milestone_paid(milestone_id: str) -> dict | None:
    session = SessionLocal()
    milestone = session.query(BillingMilestone).filter(BillingMilestone.id == milestone_id).first()
    if not milestone:
        session.close()
        return None
    milestone.status = MilestoneStatus.PAID.value
    milestone.paid_at = datetime.datetime.utcnow()
    session.commit()
    job_id = milestone.job_id
    session.close()
    return get_job(job_id)


def mark_deposit_paid(job_id: str) -> dict | None:
    session = SessionLocal()
    deposit = session.query(JobDeposit).filter(JobDeposit.job_id == job_id).first()
    if not deposit:
        session.close()
        return None
    deposit.status = MilestoneStatus.PAID.value
    deposit.received_at = datetime.datetime.utcnow()
    session.commit()
    session.close()
    return get_job(job_id)


def get_pending_milestones(job_id: str) -> list[dict]:
    session = SessionLocal()
    milestones = session.query(BillingMilestone).filter(
        BillingMilestone.job_id == job_id,
        BillingMilestone.status == MilestoneStatus.PENDING.value,
    ).all()
    result = [_serialize_milestone(m) for m in milestones]
    session.close()
    return result


def _serialize_milestone(m: BillingMilestone) -> dict:
    return {
        "id": m.id,
        "job_id": m.job_id,
        "name": m.name,
        "label": m.label,
        "percentage": m.percentage,
        "amount": m.amount,
        "status": m.status,
        "qbo_invoice_id": m.qbo_invoice_id,
        "invoiced_at": m.invoiced_at.isoformat() if m.invoiced_at else None,
        "paid_at": m.paid_at.isoformat() if m.paid_at else None,
    }


def _serialize_deposit(d: JobDeposit) -> dict:
    return {
        "id": d.id,
        "job_id": d.job_id,
        "amount": d.amount,
        "percentage": d.percentage,
        "status": d.status,
        "qbo_invoice_id": d.qbo_invoice_id,
        "invoiced_at": d.invoiced_at.isoformat() if d.invoiced_at else None,
        "received_at": d.received_at.isoformat() if d.received_at else None,
    }
