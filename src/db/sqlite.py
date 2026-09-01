from sqlalchemy import Column, String, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
from src.config import DB_PATH

Base = declarative_base()

class ProcessedEmail(Base):
    __tablename__ = 'processed_emails'
    email_id = Column(String, primary_key=True)
    processed_at = Column(DateTime, default=datetime.datetime.utcnow)

engine = create_engine(f'sqlite:///{DB_PATH}')
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    from src.db.approval_queue import init_approval_db
    from src.db.job_billing import init_job_billing_db
    from src.db.sub_compliance import init_sub_compliance_db
    from src.db.job_costing import init_job_costing_db
    from src.db.change_orders import init_change_order_db
    from src.db.commissions import init_commission_db
    from src.db.payroll import init_payroll_db
    from src.db.event_bus import init_event_bus_db
    init_approval_db()
    init_job_billing_db()
    init_sub_compliance_db()
    init_job_costing_db()
    init_change_order_db()
    init_commission_db()
    init_payroll_db()
    init_event_bus_db()


def is_email_processed(email_id: str) -> bool:
    session = SessionLocal()
    exists = session.query(ProcessedEmail).filter(ProcessedEmail.email_id == email_id).first() is not None
    session.close()
    return exists


def mark_email_processed(email_id: str):
    session = SessionLocal()
    processed_email = ProcessedEmail(email_id=email_id)
    session.merge(processed_email)
    session.commit()
    session.close()
