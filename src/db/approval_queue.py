import datetime
import enum
import json
import uuid
from sqlalchemy import Column, String, DateTime, Float, Text, Enum
from src.db.sqlite import Base, SessionLocal, engine


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalType(str, enum.Enum):
    BILL = "bill"
    COMMISSION = "commission"
    JOURNAL_ENTRY = "journal_entry"
    CHANGE_ORDER = "change_order"
    PAYROLL = "payroll"
    CREDIT_MEMO = "credit_memo"
    CLOSE_ITEM = "close_item"


class ApprovalChannel(str, enum.Enum):
    CHAT = "chat"
    GMAIL = "gmail"
    WEB = "web"


class ApprovalProposal(Base):
    __tablename__ = "approval_proposals"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    approval_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    amount = Column(Float)
    currency = Column(String, default="USD")
    payload = Column(Text)  # JSON blob with full details
    status = Column(String, default=ApprovalStatus.PENDING.value)
    approver_email = Column(String)
    approved_by = Column(String)
    approved_via = Column(String)
    approval_token = Column(String, unique=True, nullable=False)
    agent_name = Column(String)
    chat_message_name = Column(String)
    gmail_message_id = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    resolved_at = Column(DateTime)


def init_approval_db():
    ApprovalProposal.__table__.create(bind=engine, checkfirst=True)


def _serialize(proposal: ApprovalProposal) -> dict:
    return {
        "id": proposal.id,
        "approval_type": proposal.approval_type,
        "title": proposal.title,
        "description": proposal.description,
        "amount": proposal.amount,
        "currency": proposal.currency,
        "payload": json.loads(proposal.payload) if proposal.payload else {},
        "status": proposal.status,
        "approver_email": proposal.approver_email,
        "approved_by": proposal.approved_by,
        "approved_via": proposal.approved_via,
        "approval_token": proposal.approval_token,
        "agent_name": proposal.agent_name,
        "chat_message_name": proposal.chat_message_name,
        "gmail_message_id": proposal.gmail_message_id,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None,
        "resolved_at": proposal.resolved_at.isoformat() if proposal.resolved_at else None,
    }


def create_proposal(
    approval_type: str,
    title: str,
    description: str = None,
    amount: float = None,
    currency: str = "USD",
    payload: dict = None,
    approver_email: str = None,
    agent_name: str = None,
) -> dict:
    session = SessionLocal()
    token = str(uuid.uuid4())
    proposal = ApprovalProposal(
        approval_type=approval_type,
        title=title,
        description=description,
        amount=amount,
        currency=currency,
        payload=json.dumps(payload or {}),
        approver_email=approver_email,
        agent_name=agent_name,
        approval_token=token,
    )
    session.add(proposal)
    session.commit()
    result = _serialize(proposal)
    session.close()
    return result


def get_proposal_by_token(token: str) -> dict | None:
    session = SessionLocal()
    proposal = session.query(ApprovalProposal).filter(
        ApprovalProposal.approval_token == token
    ).first()
    result = _serialize(proposal) if proposal else None
    session.close()
    return result


def get_proposal_by_id(proposal_id: str) -> dict | None:
    session = SessionLocal()
    proposal = session.query(ApprovalProposal).filter(
        ApprovalProposal.id == proposal_id
    ).first()
    result = _serialize(proposal) if proposal else None
    session.close()
    return result


def list_pending_proposals(approver_email: str = None) -> list[dict]:
    session = SessionLocal()
    query = session.query(ApprovalProposal).filter(
        ApprovalProposal.status == ApprovalStatus.PENDING.value
    )
    if approver_email:
        query = query.filter(ApprovalProposal.approver_email == approver_email)
    proposals = query.order_by(ApprovalProposal.created_at.desc()).all()
    result = [_serialize(p) for p in proposals]
    session.close()
    return result


def resolve_proposal(
    token: str,
    status: str,
    approved_by: str,
    approved_via: str,
) -> dict | None:
    session = SessionLocal()
    proposal = session.query(ApprovalProposal).filter(
        ApprovalProposal.approval_token == token
    ).first()
    if not proposal:
        session.close()
        return None
    if proposal.status != ApprovalStatus.PENDING.value:
        session.close()
        return _serialize(proposal)

    proposal.status = status
    proposal.approved_by = approved_by
    proposal.approved_via = approved_via
    proposal.resolved_at = datetime.datetime.utcnow()
    proposal.updated_at = datetime.datetime.utcnow()
    session.commit()
    result = _serialize(proposal)
    session.close()
    return result


def update_proposal_channels(
    proposal_id: str,
    chat_message_name: str = None,
    gmail_message_id: str = None,
) -> dict | None:
    session = SessionLocal()
    proposal = session.query(ApprovalProposal).filter(
        ApprovalProposal.id == proposal_id
    ).first()
    if not proposal:
        session.close()
        return None
    if chat_message_name:
        proposal.chat_message_name = chat_message_name
    if gmail_message_id:
        proposal.gmail_message_id = gmail_message_id
    proposal.updated_at = datetime.datetime.utcnow()
    session.commit()
    result = _serialize(proposal)
    session.close()
    return result
