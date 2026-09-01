import datetime
from datetime import date, timedelta
import uuid
from sqlalchemy import Column, String, DateTime, Float, Boolean, Text
from src.db.sqlite import Base, SessionLocal, engine


class VendorCompliance(Base):
    __tablename__ = "vendor_compliance"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vendor_name = Column(String, nullable=False, unique=True)
    billcom_vendor_id = Column(String)
    is_subcontractor = Column(Boolean, default=False)
    coi_expiration = Column(String)  # YYYY-MM-DD
    coi_document_url = Column(String)
    w9_on_file = Column(Boolean, default=False)
    lien_waiver_required = Column(Boolean, default=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


def init_sub_compliance_db():
    VendorCompliance.__table__.create(bind=engine, checkfirst=True)


def _serialize(v: VendorCompliance) -> dict:
    today = date.today().isoformat()
    coi_valid = v.coi_expiration and v.coi_expiration >= today if v.coi_expiration else False
    compliant = True
    issues = []

    if v.is_subcontractor:
        if not coi_valid:
            compliant = False
            issues.append("COI expired or missing")
        if not v.w9_on_file:
            compliant = False
            issues.append("W-9 not on file")

    return {
        "id": v.id,
        "vendor_name": v.vendor_name,
        "billcom_vendor_id": v.billcom_vendor_id,
        "is_subcontractor": v.is_subcontractor,
        "coi_expiration": v.coi_expiration,
        "coi_valid": coi_valid,
        "w9_on_file": v.w9_on_file,
        "lien_waiver_required": v.lien_waiver_required,
        "compliant": compliant,
        "issues": issues,
        "notes": v.notes,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def register_vendor(
    vendor_name: str,
    is_subcontractor: bool = False,
    billcom_vendor_id: str = None,
    coi_expiration: str = None,
    w9_on_file: bool = False,
    lien_waiver_required: bool = True,
    notes: str = None,
) -> dict:
    session = SessionLocal()
    existing = session.query(VendorCompliance).filter(
        VendorCompliance.vendor_name == vendor_name
    ).first()
    if existing:
        existing.is_subcontractor = is_subcontractor
        existing.billcom_vendor_id = billcom_vendor_id or existing.billcom_vendor_id
        existing.coi_expiration = coi_expiration or existing.coi_expiration
        existing.w9_on_file = w9_on_file
        existing.lien_waiver_required = lien_waiver_required
        existing.notes = notes or existing.notes
        existing.updated_at = datetime.datetime.utcnow()
        session.commit()
        result = _serialize(existing)
    else:
        vendor = VendorCompliance(
            vendor_name=vendor_name,
            is_subcontractor=is_subcontractor,
            billcom_vendor_id=billcom_vendor_id,
            coi_expiration=coi_expiration,
            w9_on_file=w9_on_file,
            lien_waiver_required=lien_waiver_required,
            notes=notes,
        )
        session.add(vendor)
        session.commit()
        result = _serialize(vendor)
    session.close()
    return result


def get_vendor(vendor_name: str) -> dict | None:
    session = SessionLocal()
    v = session.query(VendorCompliance).filter(
        VendorCompliance.vendor_name == vendor_name
    ).first()
    result = _serialize(v) if v else None
    session.close()
    return result


def list_vendors(is_subcontractor: bool = None) -> list[dict]:
    session = SessionLocal()
    query = session.query(VendorCompliance)
    if is_subcontractor is not None:
        query = query.filter(VendorCompliance.is_subcontractor == is_subcontractor)
    vendors = query.order_by(VendorCompliance.vendor_name).all()
    result = [_serialize(v) for v in vendors]
    session.close()
    return result


def update_coi(vendor_name: str, coi_expiration: str, document_url: str = None) -> dict | None:
    session = SessionLocal()
    v = session.query(VendorCompliance).filter(
        VendorCompliance.vendor_name == vendor_name
    ).first()
    if not v:
        session.close()
        return None
    v.coi_expiration = coi_expiration
    if document_url:
        v.coi_document_url = document_url
    v.updated_at = datetime.datetime.utcnow()
    session.commit()
    result = _serialize(v)
    session.close()
    return result


def check_compliance(vendor_name: str) -> dict:
    vendor = get_vendor(vendor_name)
    if not vendor:
        return {
            "vendor_name": vendor_name,
            "registered": False,
            "compliant": True,
            "issues": [],
            "message": "Vendor not registered as subcontractor — no compliance check required",
        }
    if not vendor["is_subcontractor"]:
        return {
            **vendor,
            "registered": True,
            "compliant": True,
            "message": "Vendor is not a subcontractor",
        }
    return {
        **vendor,
        "registered": True,
        "message": "Compliant" if vendor["compliant"] else f"BLOCKED: {', '.join(vendor['issues'])}",
    }


def list_expiring_coi(within_days: int = 30) -> list[dict]:
    session = SessionLocal()
    vendors = session.query(VendorCompliance).filter(
        VendorCompliance.is_subcontractor == True,
        VendorCompliance.coi_expiration.isnot(None),
    ).all()
    cutoff = (date.today() + timedelta(days=within_days)).isoformat()
    today = date.today().isoformat()
    expiring = []
    for v in vendors:
        if v.coi_expiration and today <= v.coi_expiration <= cutoff:
            expiring.append(_serialize(v))
    session.close()
    return expiring


def list_non_compliant() -> list[dict]:
    vendors = list_vendors(is_subcontractor=True)
    return [v for v in vendors if not v["compliant"]]
