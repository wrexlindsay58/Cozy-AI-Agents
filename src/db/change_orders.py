import datetime
import enum
import uuid
from sqlalchemy import Column, String, DateTime, Float, Text, Boolean, ForeignKey
from src.db.sqlite import Base, SessionLocal, engine
from src.db import job_costing as jc


class ChangeOrderStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class ChangeOrder(Base):
    __tablename__ = "change_orders"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    additional_revenue = Column(Float, nullable=False, default=0.0)
    additional_cost = Column(Float, nullable=False, default=0.0)
    margin_impact = Column(Float)
    status = Column(String, default=ChangeOrderStatus.DRAFT.value)
    customer_approved = Column(Boolean, default=False)
    approval_token = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)
    approved_at = Column(DateTime)


def init_change_order_db():
    ChangeOrder.__table__.create(bind=engine, checkfirst=True)


def _serialize(co: ChangeOrder) -> dict:
    margin = co.margin_impact
    if margin is None and co.additional_revenue:
        margin = co.additional_revenue - co.additional_cost
    margin_pct = (margin / co.additional_revenue * 100) if co.additional_revenue else 0
    return {
        "id": co.id,
        "job_id": co.job_id,
        "title": co.title,
        "description": co.description,
        "additional_revenue": co.additional_revenue,
        "additional_cost": co.additional_cost,
        "margin_impact": margin,
        "margin_percent": round(margin_pct, 1),
        "status": co.status,
        "customer_approved": co.customer_approved,
        "approval_token": co.approval_token,
        "created_at": co.created_at.isoformat() if co.created_at else None,
        "approved_at": co.approved_at.isoformat() if co.approved_at else None,
        "is_risk": co.status in (ChangeOrderStatus.DRAFT.value, ChangeOrderStatus.PENDING_APPROVAL.value),
    }


def create_change_order(
    job_id: str,
    title: str,
    description: str,
    additional_revenue: float,
    additional_cost: float,
) -> dict:
    margin = additional_revenue - additional_cost
    session = SessionLocal()
    co = ChangeOrder(
        job_id=job_id,
        title=title,
        description=description,
        additional_revenue=additional_revenue,
        additional_cost=additional_cost,
        margin_impact=margin,
    )
    session.add(co)
    session.commit()
    result = _serialize(co)
    session.close()
    return result


def get_change_order(co_id: str) -> dict | None:
    session = SessionLocal()
    co = session.query(ChangeOrder).filter(ChangeOrder.id == co_id).first()
    result = _serialize(co) if co else None
    session.close()
    return result


def list_change_orders(job_id: str = None, status: str = None) -> list[dict]:
    session = SessionLocal()
    query = session.query(ChangeOrder)
    if job_id:
        query = query.filter(ChangeOrder.job_id == job_id)
    if status:
        query = query.filter(ChangeOrder.status == status)
    orders = query.order_by(ChangeOrder.created_at.desc()).all()
    result = [_serialize(co) for co in orders]
    session.close()
    return result


def update_status(co_id: str, status: str, customer_approved: bool = None) -> dict | None:
    session = SessionLocal()
    co = session.query(ChangeOrder).filter(ChangeOrder.id == co_id).first()
    if not co:
        session.close()
        return None
    co.status = status
    co.updated_at = datetime.datetime.utcnow()
    if status == ChangeOrderStatus.APPROVED.value:
        co.approved_at = datetime.datetime.utcnow()
    if customer_approved is not None:
        co.customer_approved = customer_approved
    session.commit()
    result = _serialize(co)
    session.close()
    return result


def list_unsigned(job_id: str = None) -> list[dict]:
    session = SessionLocal()
    query = session.query(ChangeOrder).filter(
        ChangeOrder.status.in_([
            ChangeOrderStatus.DRAFT.value,
            ChangeOrderStatus.PENDING_APPROVAL.value,
        ]),
        ChangeOrder.customer_approved == False,
    )
    if job_id:
        query = query.filter(ChangeOrder.job_id == job_id)
    orders = query.all()
    result = [_serialize(co) for co in orders]
    session.close()
    return result


def apply_approved_change_order(co_id: str) -> dict | None:
    """Apply an approved change order to job budget and contract amount."""
    from src.db import job_billing as jb

    co = get_change_order(co_id)
    if not co or co["status"] != ChangeOrderStatus.APPROVED.value:
        return None

    job = jb.get_job(co["job_id"])
    if not job:
        return None

    session = SessionLocal()
    job_row = session.query(jb.Job).filter(jb.Job.id == co["job_id"]).first()
    if job_row:
        job_row.contract_amount += co["additional_revenue"]
        job_row.updated_at = datetime.datetime.utcnow()
        session.commit()
    session.close()

    if co["additional_cost"] > 0:
        jc.add_cost(
            co["job_id"], "other", co["additional_cost"],
            description=f"Change order: {co['title']}", source="change_order",
            reference_id=co_id,
        )

    update_status(co_id, ChangeOrderStatus.COMPLETED.value)
    return get_change_order(co_id)
