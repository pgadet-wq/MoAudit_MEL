"""
MoA_MEL - Database Models
=========================
SQLAlchemy models for audit sessions, parsed items, corrections, and history.
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float, Boolean,
    DateTime, ForeignKey, Enum, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
import enum

Base = declarative_base()


class AuditStepStatus(enum.Enum):
    """Status of an audit step"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_VALIDATION = "awaiting_validation"
    VALIDATED = "validated"
    MODIFIED = "modified"
    FAILED = "failed"


class AuditSessionStatus(enum.Enum):
    """Status of an audit session"""
    CREATED = "created"
    STEP_1_PARSING_MMEL = "step_1_parsing_mmel"
    STEP_2_VALIDATING_MMEL = "step_2_validating_mmel"
    STEP_3_PARSING_MEL = "step_3_parsing_mel"
    STEP_4_VALIDATING_MEL = "step_4_validating_mel"
    STEP_5_AUDITING = "step_5_auditing"
    STEP_6_RESULTS = "step_6_results"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditSession(Base):
    """Main audit session tracking all steps"""
    __tablename__ = "audit_sessions"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(36), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)

    # Status
    status = Column(String(50), default="created")
    current_step = Column(Integer, default=1)

    # Aircraft context
    aircraft_msn = Column(Integer, nullable=True)
    operation_type = Column(String(10), default="CAT")
    aircraft_type = Column(String(50), nullable=True)

    # Documents
    mmel_filename = Column(String(255), nullable=True)
    mmel_filepath = Column(String(500), nullable=True)
    mel_filename = Column(String(255), nullable=True)
    mel_filepath = Column(String(500), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    mmel_items = relationship("ParsedItem", back_populates="session",
                              foreign_keys="ParsedItem.session_id",
                              primaryjoin="and_(AuditSession.id==ParsedItem.session_id, ParsedItem.document_type=='MMEL')")
    mel_items = relationship("ParsedItem", back_populates="session",
                             foreign_keys="ParsedItem.session_id",
                             primaryjoin="and_(AuditSession.id==ParsedItem.session_id, ParsedItem.document_type=='MEL')")
    audit_results = relationship("AuditResult", back_populates="session")
    step_validations = relationship("StepValidation", back_populates="session")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "name": self.name,
            "status": self.status,
            "current_step": self.current_step,
            "aircraft_msn": self.aircraft_msn,
            "operation_type": self.operation_type,
            "aircraft_type": self.aircraft_type,
            "mmel_filename": self.mmel_filename,
            "mel_filename": self.mel_filename,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ParsedItem(Base):
    """Parsed MEL/MMEL item with correction tracking"""
    __tablename__ = "parsed_items"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("audit_sessions.id"), nullable=False, index=True)
    document_type = Column(String(10), nullable=False)  # MEL or MMEL

    # ATA identification
    ata_chapter = Column(String(5), nullable=False, index=True)
    ata_section = Column(String(5), nullable=True)
    item_number = Column(String(20), nullable=False, index=True)
    item_base = Column(String(15), nullable=True)
    variant_suffix = Column(String(5), nullable=True)

    # Content
    item_description = Column(Text, nullable=True)
    category = Column(String(1), nullable=True)  # A, B, C, D
    number_installed = Column(String(10), default="-")
    number_required = Column(String(10), default="-")
    remarks = Column(Text, nullable=True)

    # Context
    applicable_msn = Column(JSON, default=list)
    operation_scope = Column(JSON, default=list)

    # Metadata
    source_page = Column(Integer, nullable=True)
    extraction_confidence = Column(Float, default=1.0)

    # Correction tracking
    is_corrected = Column(Boolean, default=False)
    original_data = Column(JSON, nullable=True)  # Store original before correction
    corrected_by = Column(String(100), nullable=True)
    corrected_at = Column(DateTime, nullable=True)

    # Relationship
    session = relationship("AuditSession", back_populates="mmel_items", foreign_keys=[session_id])
    corrections = relationship("ItemCorrection", back_populates="item")
    annotations = relationship("ItemAnnotation", back_populates="item")

    def to_dict(self):
        return {
            "id": self.id,
            "document_type": self.document_type,
            "ata_chapter": self.ata_chapter,
            "ata_section": self.ata_section,
            "item_number": self.item_number,
            "item_base": self.item_base,
            "variant_suffix": self.variant_suffix,
            "item_description": self.item_description,
            "category": self.category,
            "number_installed": self.number_installed,
            "number_required": self.number_required,
            "remarks": self.remarks,
            "applicable_msn": self.applicable_msn,
            "operation_scope": self.operation_scope,
            "source_page": self.source_page,
            "extraction_confidence": self.extraction_confidence,
            "is_corrected": self.is_corrected,
            "corrected_by": self.corrected_by,
            "corrected_at": self.corrected_at.isoformat() if self.corrected_at else None,
            "annotations": [a.to_dict() for a in self.annotations] if self.annotations else []
        }


class ItemCorrection(Base):
    """History of corrections made to a parsed item"""
    __tablename__ = "item_corrections"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("parsed_items.id"), nullable=False, index=True)

    field_name = Column(String(50), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)

    corrected_by = Column(String(100), nullable=True)
    corrected_at = Column(DateTime, default=datetime.utcnow)
    reason = Column(Text, nullable=True)

    # Relationship
    item = relationship("ParsedItem", back_populates="corrections")

    def to_dict(self):
        return {
            "id": self.id,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "corrected_by": self.corrected_by,
            "corrected_at": self.corrected_at.isoformat() if self.corrected_at else None,
            "reason": self.reason
        }


class ItemAnnotation(Base):
    """Annotations/comments on parsed items"""
    __tablename__ = "item_annotations"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("parsed_items.id"), nullable=False, index=True)

    content = Column(Text, nullable=False)
    annotation_type = Column(String(50), default="comment")  # comment, warning, question, note
    author = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Optional: highlight specific field
    target_field = Column(String(50), nullable=True)

    # Relationship
    item = relationship("ParsedItem", back_populates="annotations")

    def to_dict(self):
        return {
            "id": self.id,
            "item_id": self.item_id,
            "content": self.content,
            "annotation_type": self.annotation_type,
            "author": self.author,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "target_field": self.target_field
        }


class StepValidation(Base):
    """Tracking of step validations by user"""
    __tablename__ = "step_validations"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("audit_sessions.id"), nullable=False, index=True)

    step_number = Column(Integer, nullable=False)
    step_name = Column(String(100), nullable=False)
    status = Column(String(50), default="pending")

    validated_at = Column(DateTime, nullable=True)
    validated_by = Column(String(100), nullable=True)

    # Stats at validation time
    items_count = Column(Integer, default=0)
    corrections_count = Column(Integer, default=0)
    annotations_count = Column(Integer, default=0)

    notes = Column(Text, nullable=True)

    # Relationship
    session = relationship("AuditSession", back_populates="step_validations")

    def to_dict(self):
        return {
            "id": self.id,
            "step_number": self.step_number,
            "step_name": self.step_name,
            "status": self.status,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
            "validated_by": self.validated_by,
            "items_count": self.items_count,
            "corrections_count": self.corrections_count,
            "annotations_count": self.annotations_count,
            "notes": self.notes
        }


class AuditResult(Base):
    """Audit comparison results"""
    __tablename__ = "audit_results"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("audit_sessions.id"), nullable=False, index=True)

    # Item references
    mel_item_id = Column(Integer, ForeignKey("parsed_items.id"), nullable=True)
    mmel_item_id = Column(Integer, ForeignKey("parsed_items.id"), nullable=True)

    # Identifiers
    mel_item_number = Column(String(20), nullable=True)
    mmel_item_number = Column(String(20), nullable=True)
    ata_chapter = Column(String(5), nullable=True)
    item_description = Column(Text, nullable=True)

    # Verdict
    verdict = Column(String(50), nullable=False)  # COMPLIANT, LESS_RESTRICTIVE, MORE_RESTRICTIVE, MISSING_IN_MEL, MISSING_IN_MMEL
    severity = Column(String(20), nullable=False)  # critical, high, medium, warning, info

    # Categories
    mel_category = Column(String(1), nullable=True)
    mmel_category = Column(String(1), nullable=True)

    # Remarks comparison
    mel_remarks = Column(Text, nullable=True)
    mmel_remarks = Column(Text, nullable=True)

    # HITL
    requires_hitl = Column(Boolean, default=False)
    hitl_reasons = Column(JSON, default=list)
    hitl_status = Column(String(50), default="pending")  # pending, accepted, rejected, escalated
    hitl_validated_by = Column(String(100), nullable=True)
    hitl_validated_at = Column(DateTime, nullable=True)
    hitl_comments = Column(Text, nullable=True)

    # SLA
    sla_hours = Column(Integer, nullable=True)

    # Relationship
    session = relationship("AuditSession", back_populates="audit_results")

    def to_dict(self):
        return {
            "id": self.id,
            "mel_item_id": self.mel_item_id,
            "mmel_item_id": self.mmel_item_id,
            "mel_item_number": self.mel_item_number,
            "mmel_item_number": self.mmel_item_number,
            "ata_chapter": self.ata_chapter,
            "item_description": self.item_description,
            "verdict": self.verdict,
            "severity": self.severity,
            "mel_category": self.mel_category,
            "mmel_category": self.mmel_category,
            "mel_remarks": self.mel_remarks,
            "mmel_remarks": self.mmel_remarks,
            "requires_hitl": self.requires_hitl,
            "hitl_reasons": self.hitl_reasons,
            "hitl_status": self.hitl_status,
            "hitl_validated_by": self.hitl_validated_by,
            "hitl_validated_at": self.hitl_validated_at.isoformat() if self.hitl_validated_at else None,
            "hitl_comments": self.hitl_comments,
            "sla_hours": self.sla_hours
        }


# Database initialization
def init_database(db_path: str = "data/moamel_audit.db"):
    """Initialize the database and create tables"""
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_session_maker(engine):
    """Get a session maker for the database"""
    return sessionmaker(bind=engine)
