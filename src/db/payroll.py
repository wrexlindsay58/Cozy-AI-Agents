import datetime
import enum
import json
import uuid
from sqlalchemy import Column, String, DateTime, Float, Text, Boolean, ForeignKey
from src.db.sqlite import Base, SessionLocal, engine


class PayrollRunStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class PayrollRun(Base):
    __tablename__ = "payroll_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    period = Column(String, nullable=False)  # YYYY-MM
    status = Column(String, default=PayrollRunStatus.DRAFT.value)
    total_salary = Column(Float, default=0.0)
    total_commission = Column(Float, default=0.0)
    total_amount = Column(Float, default=0.0)
    employee_count = Column(Float, default=0)
    validation_flags_json = Column(Text)
    commission_ids_json = Column(Text)
    notes = Column(Text)
    approved_by = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    approved_at = Column(DateTime)


class PayrollAllocation(Base):
    __tablename__ = "payroll_allocations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    payroll_run_id = Column(String, ForeignKey("payroll_runs.id"))
    employee_id = Column(String)
    employee_name = Column(String)
    job_id = Column(String)
    job_name = Column(String)
    hours = Column(Float, default=0.0)
    labor_cost = Column(Float, default=0.0)
    period = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


def init_payroll_db():
    PayrollRun.__table__.create(bind=engine, checkfirst=True)
    PayrollAllocation.__table__.create(bind=engine, checkfirst=True)


def _serialize_run(run: PayrollRun) -> dict:
    flags = json.loads(run.validation_flags_json) if run.validation_flags_json else []
    commission_ids = json.loads(run.commission_ids_json) if run.commission_ids_json else []
    return {
        "id": run.id,
        "period": run.period,
        "status": run.status,
        "total_salary": run.total_salary,
        "total_commission": run.total_commission,
        "total_amount": run.total_amount,
        "employee_count": run.employee_count,
        "validation_flags": flags,
        "commission_ids": commission_ids,
        "notes": run.notes,
        "approved_by": run.approved_by,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
    }


def _serialize_allocation(alloc: PayrollAllocation) -> dict:
    return {
        "id": alloc.id,
        "payroll_run_id": alloc.payroll_run_id,
        "employee_id": alloc.employee_id,
        "employee_name": alloc.employee_name,
        "job_id": alloc.job_id,
        "job_name": alloc.job_name,
        "hours": alloc.hours,
        "labor_cost": alloc.labor_cost,
        "period": alloc.period,
    }


def create_payroll_run(
    period: str,
    total_salary: float = 0,
    total_commission: float = 0,
    employee_count: int = 0,
    validation_flags: list = None,
    commission_ids: list[str] = None,
    notes: str = None,
) -> dict:
    session = SessionLocal()
    run = PayrollRun(
        period=period,
        total_salary=total_salary,
        total_commission=total_commission,
        total_amount=total_salary + total_commission,
        employee_count=employee_count,
        validation_flags_json=json.dumps(validation_flags or []),
        commission_ids_json=json.dumps(commission_ids or []),
        notes=notes,
    )
    session.add(run)
    session.commit()
    result = _serialize_run(run)
    session.close()
    return result


def get_payroll_run(run_id: str) -> dict | None:
    session = SessionLocal()
    run = session.query(PayrollRun).filter(PayrollRun.id == run_id).first()
    result = _serialize_run(run) if run else None
    session.close()
    return result


def list_payroll_runs(period: str = None, status: str = None) -> list[dict]:
    session = SessionLocal()
    query = session.query(PayrollRun)
    if period:
        query = query.filter(PayrollRun.period == period)
    if status:
        query = query.filter(PayrollRun.status == status)
    runs = query.order_by(PayrollRun.created_at.desc()).all()
    result = [_serialize_run(r) for r in runs]
    session.close()
    return result


def update_payroll_run_status(
    run_id: str,
    status: str,
    approved_by: str = None,
) -> dict | None:
    session = SessionLocal()
    run = session.query(PayrollRun).filter(PayrollRun.id == run_id).first()
    if not run:
        session.close()
        return None
    run.status = status
    if approved_by:
        run.approved_by = approved_by
    if status == PayrollRunStatus.APPROVED.value:
        run.approved_at = datetime.datetime.utcnow()
    session.commit()
    result = _serialize_run(run)
    session.close()
    return result


def add_allocation(
    payroll_run_id: str,
    employee_id: str,
    employee_name: str,
    job_id: str,
    job_name: str,
    hours: float,
    labor_cost: float,
    period: str,
) -> dict:
    session = SessionLocal()
    alloc = PayrollAllocation(
        payroll_run_id=payroll_run_id,
        employee_id=employee_id,
        employee_name=employee_name,
        job_id=job_id,
        job_name=job_name,
        hours=hours,
        labor_cost=labor_cost,
        period=period,
    )
    session.add(alloc)
    session.commit()
    result = _serialize_allocation(alloc)
    session.close()
    return result


def list_allocations(payroll_run_id: str = None, job_id: str = None) -> list[dict]:
    session = SessionLocal()
    query = session.query(PayrollAllocation)
    if payroll_run_id:
        query = query.filter(PayrollAllocation.payroll_run_id == payroll_run_id)
    if job_id:
        query = query.filter(PayrollAllocation.job_id == job_id)
    allocs = query.all()
    result = [_serialize_allocation(a) for a in allocs]
    session.close()
    return result
