import datetime
import enum
import hashlib
import json
import uuid
from sqlalchemy import Column, String, DateTime, Float, Text, Boolean, Integer
from src.db.sqlite import Base, SessionLocal, engine


class EventStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DUPLICATE = "duplicate"
    BLOCKED = "blocked"


class FinanceEvent(Base):
    __tablename__ = "finance_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type = Column(String, nullable=False)
    source = Column(String, nullable=False)  # email, billcom, qbo, bamboohr, scheduler, api
    idempotency_key = Column(String, unique=True)
    priority = Column(Integer, default=50)
    status = Column(String, default=EventStatus.PENDING.value)
    payload_json = Column(Text)
    result_json = Column(Text)
    routed_agent = Column(String)
    conflict_detected = Column(Boolean, default=False)
    policy_blocked = Column(Boolean, default=False)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    processed_at = Column(DateTime)


def init_event_bus_db():
    FinanceEvent.__table__.create(bind=engine, checkfirst=True)


def _make_idempotency_key(event_type: str, source: str, payload: dict) -> str:
  raw = f"{event_type}:{source}:{json.dumps(payload, sort_keys=True, default=str)}"
  return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _serialize(event: FinanceEvent) -> dict:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "source": event.source,
        "idempotency_key": event.idempotency_key,
        "priority": event.priority,
        "status": event.status,
        "payload": json.loads(event.payload_json) if event.payload_json else {},
        "result": json.loads(event.result_json) if event.result_json else None,
        "routed_agent": event.routed_agent,
        "conflict_detected": event.conflict_detected,
        "policy_blocked": event.policy_blocked,
        "error_message": event.error_message,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "processed_at": event.processed_at.isoformat() if event.processed_at else None,
    }


def create_event(
    event_type: str,
    source: str,
    payload: dict,
    priority: int = 50,
    idempotency_key: str = None,
) -> dict:
    key = idempotency_key or _make_idempotency_key(event_type, source, payload)

    session = SessionLocal()
    existing = session.query(FinanceEvent).filter(
        FinanceEvent.idempotency_key == key
    ).first()
    if existing:
        session.close()
        return {**_serialize(existing), "duplicate": True}

    event = FinanceEvent(
        event_type=event_type,
        source=source,
        idempotency_key=key,
        priority=priority,
        payload_json=json.dumps(payload, default=str),
    )
    session.add(event)
    session.commit()
    result = _serialize(event)
    session.close()
    return result


def update_event(
    event_id: str,
    status: str = None,
    result: dict = None,
    routed_agent: str = None,
    conflict_detected: bool = None,
    policy_blocked: bool = None,
    error_message: str = None,
) -> dict | None:
    session = SessionLocal()
    event = session.query(FinanceEvent).filter(FinanceEvent.id == event_id).first()
    if not event:
        session.close()
        return None

    if status:
        event.status = status
        if status in (EventStatus.COMPLETED.value, EventStatus.FAILED.value, EventStatus.BLOCKED.value):
            event.processed_at = datetime.datetime.utcnow()
    if result is not None:
        event.result_json = json.dumps(result, default=str)
    if routed_agent:
        event.routed_agent = routed_agent
    if conflict_detected is not None:
        event.conflict_detected = conflict_detected
    if policy_blocked is not None:
        event.policy_blocked = policy_blocked
    if error_message:
        event.error_message = error_message

    session.commit()
    out = _serialize(event)
    session.close()
    return out


def get_event(event_id: str) -> dict | None:
    session = SessionLocal()
    event = session.query(FinanceEvent).filter(FinanceEvent.id == event_id).first()
    result = _serialize(event) if event else None
    session.close()
    return result


def list_events(
    status: str = None,
    event_type: str = None,
    limit: int = 50,
) -> list[dict]:
    session = SessionLocal()
    query = session.query(FinanceEvent)
    if status:
        query = query.filter(FinanceEvent.status == status)
    if event_type:
        query = query.filter(FinanceEvent.event_type == event_type)
    events = query.order_by(
        FinanceEvent.priority.desc(),
        FinanceEvent.created_at.desc(),
    ).limit(limit).all()
    result = [_serialize(e) for e in events]
    session.close()
    return result


def get_pending_events(limit: int = 20) -> list[dict]:
    return list_events(status=EventStatus.PENDING.value, limit=limit)
