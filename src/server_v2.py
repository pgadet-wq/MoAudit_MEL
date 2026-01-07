"""
MoA_MEL - Server V2 with Sequential Workflow
=============================================
FastAPI server with 6-step wizard workflow and user validation at each step.

Steps:
1. Parse MMEL file
2. Validate MMEL parsing (user review)
3. Parse MEL file
4. Validate MEL parsing (user review)
5. Run audit (MEL vs MMEL comparison)
6. Evaluate and classify discrepancies
"""

import os
import sys
import uuid
import json
import shutil
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel, Field
import logging

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Database
from database.models import (
    init_database, get_session_maker,
    AuditSession, ParsedItem, ItemCorrection, ItemAnnotation,
    StepValidation, AuditResult
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MoA_MEL_V2")

# ============== Configuration ==============

UPLOAD_DIR = Path("data/uploads")
OUTPUT_DIR = Path("outputs")
STATIC_DIR = Path("static")
DB_PATH = Path("data/moamel_audit.db")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Initialize database
engine = init_database(str(DB_PATH))
SessionLocal = get_session_maker(engine)

# ============== Pydantic Models ==============

class SessionCreate(BaseModel):
    """Create a new audit session"""
    name: Optional[str] = None
    aircraft_msn: Optional[int] = None
    operation_type: str = "CAT"
    aircraft_type: Optional[str] = None


class SessionUpdate(BaseModel):
    """Update session configuration"""
    name: Optional[str] = None
    aircraft_msn: Optional[int] = None
    operation_type: Optional[str] = None
    aircraft_type: Optional[str] = None


class ItemUpdate(BaseModel):
    """Update a parsed item (correction)"""
    ata_chapter: Optional[str] = None
    ata_section: Optional[str] = None
    item_number: Optional[str] = None
    item_description: Optional[str] = None
    category: Optional[str] = None
    number_installed: Optional[str] = None
    number_required: Optional[str] = None
    remarks: Optional[str] = None
    corrected_by: Optional[str] = "user"
    reason: Optional[str] = None


class AnnotationCreate(BaseModel):
    """Create an annotation on an item"""
    content: str
    annotation_type: str = "comment"  # comment, warning, question, note
    author: Optional[str] = None
    target_field: Optional[str] = None


class StepValidationRequest(BaseModel):
    """Request to validate a step"""
    validated_by: Optional[str] = "user"
    notes: Optional[str] = None


class HITLValidation(BaseModel):
    """HITL validation request"""
    decision: str  # accepted, rejected, escalated
    validated_by: Optional[str] = None
    comments: Optional[str] = None


# ============== FastAPI App ==============

app = FastAPI(
    title="MoA_MEL Audit V2",
    description="MEL/MMEL Audit with Sequential Validation Workflow",
    version="2.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============== Helper Functions ==============

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        return db
    finally:
        pass  # Session will be closed after use


def parse_pdf_to_items(pdf_path: str, doc_type: str) -> List[Dict]:
    """Parse a PDF file and extract items"""
    items = []

    try:
        # Try Docling parser
        from docling.document_converter import DocumentConverter

        logger.info(f"Parsing {doc_type} with Docling: {pdf_path}")
        converter = DocumentConverter()
        result = converter.convert(pdf_path)
        markdown = result.document.export_to_markdown()

        # Extract items using regex patterns
        import re

        # Pattern for ATA items
        ata_pattern = r'(\d{2})-(\d{2})-(\d{2,3})([A-Z])?'

        lines = markdown.split('\n')
        current_chapter = None

        for i, line in enumerate(lines):
            # Detect chapter headers
            chapter_match = re.match(r'^#+\s*(?:ATA\s*)?(\d{2})\s*[-–]\s*(.+)$', line)
            if chapter_match:
                current_chapter = chapter_match.group(1)
                continue

            # Detect items
            item_match = re.search(ata_pattern, line)
            if item_match:
                chapter, section, item_num, suffix = item_match.groups()

                # Extract context (next few lines)
                context = '\n'.join(lines[i:min(i+5, len(lines))])

                # Try to extract description
                desc_match = re.search(r'\d{2}-\d{2}-\d{2,3}[A-Z]?\s+(.+?)(?:\s*\||\s*$)', line)
                description = desc_match.group(1).strip() if desc_match else ""

                # Try to extract category
                category = "C"  # Default
                for cat in ['A', 'B', 'C', 'D']:
                    if re.search(rf'\|\s*{cat}\s*\|', context) or re.search(rf'\b{cat}\b', context[:50]):
                        category = cat
                        break

                # Extract remarks
                remarks_match = re.search(r'\([OM]\)[^|]*', context, re.IGNORECASE)
                remarks = remarks_match.group(0).strip() if remarks_match else ""

                items.append({
                    "ata_chapter": chapter,
                    "ata_section": section,
                    "item_number": f"{chapter}-{section}-{item_num.zfill(2)}{suffix or ''}",
                    "item_base": f"{chapter}-{section}-{item_num.zfill(2)}",
                    "variant_suffix": suffix or "",
                    "item_description": description,
                    "category": category,
                    "number_installed": "-",
                    "number_required": "-",
                    "remarks": remarks,
                    "source_page": 0,
                    "extraction_confidence": 0.85
                })

        logger.info(f"Extracted {len(items)} items from {doc_type}")

    except ImportError:
        logger.warning("Docling not available, using mock parser")
        # Fallback: create mock items for testing
        items = create_mock_items(doc_type)
    except Exception as e:
        logger.error(f"Error parsing PDF: {e}")
        raise

    return items


def create_mock_items(doc_type: str) -> List[Dict]:
    """Create mock items for testing when parser unavailable"""
    mock_chapters = ["21", "22", "24", "27", "28", "29", "30", "32", "34", "36"]
    items = []

    for ch in mock_chapters:
        for i in range(1, 4):
            items.append({
                "ata_chapter": ch,
                "ata_section": str(i * 10).zfill(2),
                "item_number": f"{ch}-{str(i * 10).zfill(2)}-01",
                "item_base": f"{ch}-{str(i * 10).zfill(2)}-01",
                "variant_suffix": "",
                "item_description": f"Sample {doc_type} item {ch}-{i}",
                "category": ["A", "B", "C", "D"][i % 4],
                "number_installed": "2",
                "number_required": "1",
                "remarks": "(O) May be inoperative provided conditions are met.",
                "source_page": i,
                "extraction_confidence": 0.9
            })

    return items


# ============== API Endpoints ==============

# ----- Root & Health -----

@app.get("/")
async def root():
    return {"message": "MoA_MEL Audit V2", "version": "2.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# ----- Session Management -----

@app.post("/api/sessions")
async def create_session(request: SessionCreate):
    """Create a new audit session"""
    db = get_db()
    try:
        session = AuditSession(
            session_id=str(uuid.uuid4()),
            name=request.name or f"Audit {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            status="created",
            current_step=1,
            aircraft_msn=request.aircraft_msn,
            operation_type=request.operation_type,
            aircraft_type=request.aircraft_type
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        logger.info(f"Created session: {session.session_id}")
        return session.to_dict()
    finally:
        db.close()


@app.get("/api/sessions")
async def list_sessions(limit: int = 20, offset: int = 0):
    """List all audit sessions (history)"""
    db = get_db()
    try:
        sessions = db.query(AuditSession)\
            .order_by(AuditSession.created_at.desc())\
            .offset(offset)\
            .limit(limit)\
            .all()

        total = db.query(AuditSession).count()

        return {
            "sessions": [s.to_dict() for s in sessions],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    finally:
        db.close()


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Get step validations
        validations = db.query(StepValidation).filter(
            StepValidation.session_id == session.id
        ).all()

        result = session.to_dict()
        result["step_validations"] = [v.to_dict() for v in validations]

        return result
    finally:
        db.close()


@app.put("/api/sessions/{session_id}")
async def update_session(session_id: str, request: SessionUpdate):
    """Update session configuration"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if request.name is not None:
            session.name = request.name
        if request.aircraft_msn is not None:
            session.aircraft_msn = request.aircraft_msn
        if request.operation_type is not None:
            session.operation_type = request.operation_type
        if request.aircraft_type is not None:
            session.aircraft_type = request.aircraft_type

        session.updated_at = datetime.utcnow()
        db.commit()

        return session.to_dict()
    finally:
        db.close()


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and all related data"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Delete related data
        db.query(ParsedItem).filter(ParsedItem.session_id == session.id).delete()
        db.query(StepValidation).filter(StepValidation.session_id == session.id).delete()
        db.query(AuditResult).filter(AuditResult.session_id == session.id).delete()
        db.delete(session)
        db.commit()

        return {"message": "Session deleted"}
    finally:
        db.close()


# ----- Step 1: Upload and Parse MMEL -----

@app.post("/api/sessions/{session_id}/step1/upload")
async def step1_upload_mmel(session_id: str, file: UploadFile = File(...)):
    """Step 1: Upload MMEL PDF file"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Save file
        file_ext = Path(file.filename).suffix
        unique_name = f"mmel_{session_id[:8]}{file_ext}"
        file_path = UPLOAD_DIR / unique_name

        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Update session
        session.mmel_filename = file.filename
        session.mmel_filepath = str(file_path)
        session.status = "step_1_parsing_mmel"
        session.updated_at = datetime.utcnow()
        db.commit()

        return {
            "message": "MMEL uploaded successfully",
            "filename": file.filename,
            "path": str(file_path)
        }
    finally:
        db.close()


@app.post("/api/sessions/{session_id}/step1/parse")
async def step1_parse_mmel(session_id: str, background_tasks: BackgroundTasks):
    """Step 1: Parse uploaded MMEL file"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if not session.mmel_filepath or not Path(session.mmel_filepath).exists():
            raise HTTPException(status_code=400, detail="MMEL file not uploaded")

        # Parse the file
        items = parse_pdf_to_items(session.mmel_filepath, "MMEL")

        # Delete existing MMEL items for this session
        db.query(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MMEL"
        ).delete()

        # Save items to database
        for item_data in items:
            item = ParsedItem(
                session_id=session.id,
                document_type="MMEL",
                ata_chapter=item_data.get("ata_chapter", ""),
                ata_section=item_data.get("ata_section", ""),
                item_number=item_data.get("item_number", ""),
                item_base=item_data.get("item_base", ""),
                variant_suffix=item_data.get("variant_suffix", ""),
                item_description=item_data.get("item_description", ""),
                category=item_data.get("category", "C"),
                number_installed=item_data.get("number_installed", "-"),
                number_required=item_data.get("number_required", "-"),
                remarks=item_data.get("remarks", ""),
                source_page=item_data.get("source_page", 0),
                extraction_confidence=item_data.get("extraction_confidence", 1.0)
            )
            db.add(item)

        # Update session status
        session.status = "step_2_validating_mmel"
        session.current_step = 2
        session.updated_at = datetime.utcnow()
        db.commit()

        return {
            "message": "MMEL parsed successfully",
            "items_count": len(items),
            "next_step": 2
        }
    finally:
        db.close()


# ----- Step 2: Validate MMEL Parsing -----

@app.get("/api/sessions/{session_id}/step2/items")
async def step2_get_mmel_items(
    session_id: str,
    chapter: Optional[str] = None,
    page: int = 1,
    per_page: int = 50
):
    """Step 2: Get parsed MMEL items for validation"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        query = db.query(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MMEL"
        )

        if chapter:
            query = query.filter(ParsedItem.ata_chapter == chapter)

        total = query.count()
        items = query.order_by(ParsedItem.ata_chapter, ParsedItem.item_number)\
            .offset((page - 1) * per_page)\
            .limit(per_page)\
            .all()

        # Get chapters summary
        chapters = db.query(
            ParsedItem.ata_chapter,
            db.func.count(ParsedItem.id).label('count')
        ).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MMEL"
        ).group_by(ParsedItem.ata_chapter).all()

        return {
            "items": [item.to_dict() for item in items],
            "total": total,
            "page": page,
            "per_page": per_page,
            "chapters": [{"chapter": ch, "count": cnt} for ch, cnt in chapters]
        }
    finally:
        db.close()


@app.put("/api/sessions/{session_id}/items/{item_id}")
async def update_item(session_id: str, item_id: int, request: ItemUpdate):
    """Update a parsed item (correction)"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        item = db.query(ParsedItem).filter(
            ParsedItem.id == item_id,
            ParsedItem.session_id == session.id
        ).first()

        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        # Store original data before first correction
        if not item.is_corrected:
            item.original_data = item.to_dict()

        # Track corrections
        corrections_made = []

        for field in ['ata_chapter', 'ata_section', 'item_number', 'item_description',
                      'category', 'number_installed', 'number_required', 'remarks']:
            new_value = getattr(request, field, None)
            if new_value is not None:
                old_value = getattr(item, field)
                if old_value != new_value:
                    # Record correction
                    correction = ItemCorrection(
                        item_id=item.id,
                        field_name=field,
                        old_value=str(old_value) if old_value else None,
                        new_value=str(new_value),
                        corrected_by=request.corrected_by,
                        reason=request.reason
                    )
                    db.add(correction)
                    corrections_made.append(field)

                    # Apply correction
                    setattr(item, field, new_value)

        if corrections_made:
            item.is_corrected = True
            item.corrected_by = request.corrected_by
            item.corrected_at = datetime.utcnow()

        db.commit()
        db.refresh(item)

        return {
            "item": item.to_dict(),
            "corrections_made": corrections_made
        }
    finally:
        db.close()


@app.post("/api/sessions/{session_id}/items/{item_id}/annotations")
async def add_annotation(session_id: str, item_id: int, request: AnnotationCreate):
    """Add an annotation to an item"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        item = db.query(ParsedItem).filter(
            ParsedItem.id == item_id,
            ParsedItem.session_id == session.id
        ).first()

        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        annotation = ItemAnnotation(
            item_id=item.id,
            content=request.content,
            annotation_type=request.annotation_type,
            author=request.author,
            target_field=request.target_field
        )
        db.add(annotation)
        db.commit()
        db.refresh(annotation)

        return annotation.to_dict()
    finally:
        db.close()


@app.delete("/api/sessions/{session_id}/annotations/{annotation_id}")
async def delete_annotation(session_id: str, annotation_id: int):
    """Delete an annotation"""
    db = get_db()
    try:
        annotation = db.query(ItemAnnotation).filter(
            ItemAnnotation.id == annotation_id
        ).first()

        if not annotation:
            raise HTTPException(status_code=404, detail="Annotation not found")

        db.delete(annotation)
        db.commit()

        return {"message": "Annotation deleted"}
    finally:
        db.close()


@app.post("/api/sessions/{session_id}/step2/validate")
async def step2_validate_mmel(session_id: str, request: StepValidationRequest):
    """Step 2: Validate MMEL parsing and proceed to step 3"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Count items and corrections
        items_count = db.query(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MMEL"
        ).count()

        corrections_count = db.query(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MMEL",
            ParsedItem.is_corrected == True
        ).count()

        annotations_count = db.query(ItemAnnotation).join(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MMEL"
        ).count()

        # Create validation record
        validation = StepValidation(
            session_id=session.id,
            step_number=2,
            step_name="MMEL Parsing Validation",
            status="validated",
            validated_at=datetime.utcnow(),
            validated_by=request.validated_by,
            items_count=items_count,
            corrections_count=corrections_count,
            annotations_count=annotations_count,
            notes=request.notes
        )
        db.add(validation)

        # Update session
        session.status = "step_3_parsing_mel"
        session.current_step = 3
        session.updated_at = datetime.utcnow()
        db.commit()

        return {
            "message": "MMEL validation completed",
            "items_count": items_count,
            "corrections_count": corrections_count,
            "annotations_count": annotations_count,
            "next_step": 3
        }
    finally:
        db.close()


# ----- Step 3: Upload and Parse MEL -----

@app.post("/api/sessions/{session_id}/step3/upload")
async def step3_upload_mel(session_id: str, file: UploadFile = File(...)):
    """Step 3: Upload MEL PDF file"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Save file
        file_ext = Path(file.filename).suffix
        unique_name = f"mel_{session_id[:8]}{file_ext}"
        file_path = UPLOAD_DIR / unique_name

        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Update session
        session.mel_filename = file.filename
        session.mel_filepath = str(file_path)
        session.updated_at = datetime.utcnow()
        db.commit()

        return {
            "message": "MEL uploaded successfully",
            "filename": file.filename,
            "path": str(file_path)
        }
    finally:
        db.close()


@app.post("/api/sessions/{session_id}/step3/parse")
async def step3_parse_mel(session_id: str):
    """Step 3: Parse uploaded MEL file"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if not session.mel_filepath or not Path(session.mel_filepath).exists():
            raise HTTPException(status_code=400, detail="MEL file not uploaded")

        # Parse the file
        items = parse_pdf_to_items(session.mel_filepath, "MEL")

        # Delete existing MEL items for this session
        db.query(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MEL"
        ).delete()

        # Save items to database
        for item_data in items:
            item = ParsedItem(
                session_id=session.id,
                document_type="MEL",
                ata_chapter=item_data.get("ata_chapter", ""),
                ata_section=item_data.get("ata_section", ""),
                item_number=item_data.get("item_number", ""),
                item_base=item_data.get("item_base", ""),
                variant_suffix=item_data.get("variant_suffix", ""),
                item_description=item_data.get("item_description", ""),
                category=item_data.get("category", "C"),
                number_installed=item_data.get("number_installed", "-"),
                number_required=item_data.get("number_required", "-"),
                remarks=item_data.get("remarks", ""),
                source_page=item_data.get("source_page", 0),
                extraction_confidence=item_data.get("extraction_confidence", 1.0)
            )
            db.add(item)

        # Update session status
        session.status = "step_4_validating_mel"
        session.current_step = 4
        session.updated_at = datetime.utcnow()
        db.commit()

        return {
            "message": "MEL parsed successfully",
            "items_count": len(items),
            "next_step": 4
        }
    finally:
        db.close()


# ----- Step 4: Validate MEL Parsing -----

@app.get("/api/sessions/{session_id}/step4/items")
async def step4_get_mel_items(
    session_id: str,
    chapter: Optional[str] = None,
    page: int = 1,
    per_page: int = 50
):
    """Step 4: Get parsed MEL items for validation"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        query = db.query(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MEL"
        )

        if chapter:
            query = query.filter(ParsedItem.ata_chapter == chapter)

        total = query.count()
        items = query.order_by(ParsedItem.ata_chapter, ParsedItem.item_number)\
            .offset((page - 1) * per_page)\
            .limit(per_page)\
            .all()

        # Get chapters summary
        chapters = db.query(
            ParsedItem.ata_chapter,
            db.func.count(ParsedItem.id).label('count')
        ).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MEL"
        ).group_by(ParsedItem.ata_chapter).all()

        return {
            "items": [item.to_dict() for item in items],
            "total": total,
            "page": page,
            "per_page": per_page,
            "chapters": [{"chapter": ch, "count": cnt} for ch, cnt in chapters]
        }
    finally:
        db.close()


@app.post("/api/sessions/{session_id}/step4/validate")
async def step4_validate_mel(session_id: str, request: StepValidationRequest):
    """Step 4: Validate MEL parsing and proceed to step 5"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Count items and corrections
        items_count = db.query(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MEL"
        ).count()

        corrections_count = db.query(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MEL",
            ParsedItem.is_corrected == True
        ).count()

        annotations_count = db.query(ItemAnnotation).join(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MEL"
        ).count()

        # Create validation record
        validation = StepValidation(
            session_id=session.id,
            step_number=4,
            step_name="MEL Parsing Validation",
            status="validated",
            validated_at=datetime.utcnow(),
            validated_by=request.validated_by,
            items_count=items_count,
            corrections_count=corrections_count,
            annotations_count=annotations_count,
            notes=request.notes
        )
        db.add(validation)

        # Update session
        session.status = "step_5_auditing"
        session.current_step = 5
        session.updated_at = datetime.utcnow()
        db.commit()

        return {
            "message": "MEL validation completed",
            "items_count": items_count,
            "corrections_count": corrections_count,
            "annotations_count": annotations_count,
            "next_step": 5
        }
    finally:
        db.close()


# ----- Step 5: Run Audit -----

@app.post("/api/sessions/{session_id}/step5/run")
async def step5_run_audit(session_id: str):
    """Step 5: Run the MEL vs MMEL audit"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Get all MEL and MMEL items
        mel_items = db.query(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MEL"
        ).all()

        mmel_items = db.query(ParsedItem).filter(
            ParsedItem.session_id == session.id,
            ParsedItem.document_type == "MMEL"
        ).all()

        if not mel_items:
            raise HTTPException(status_code=400, detail="No MEL items found")
        if not mmel_items:
            raise HTTPException(status_code=400, detail="No MMEL items found")

        # Delete existing audit results
        db.query(AuditResult).filter(
            AuditResult.session_id == session.id
        ).delete()

        # Create index of MMEL items by item_number
        mmel_index = {item.item_number: item for item in mmel_items}
        mel_index = {item.item_number: item for item in mel_items}

        # Category hierarchy (A is most restrictive)
        category_rank = {"A": 1, "B": 2, "C": 3, "D": 4}

        results = []

        # Compare MEL items against MMEL
        for mel_item in mel_items:
            mmel_item = mmel_index.get(mel_item.item_number)

            if mmel_item:
                # Found matching MMEL item - compare
                mel_rank = category_rank.get(mel_item.category, 5)
                mmel_rank = category_rank.get(mmel_item.category, 5)

                if mel_rank == mmel_rank:
                    verdict = "COMPLIANT"
                    severity = "info"
                    requires_hitl = False
                    hitl_reasons = []
                elif mel_rank < mmel_rank:
                    verdict = "MORE_RESTRICTIVE"
                    severity = "info"
                    requires_hitl = False
                    hitl_reasons = []
                else:
                    verdict = "LESS_RESTRICTIVE"
                    severity = "critical"
                    requires_hitl = True
                    hitl_reasons = [
                        f"MEL category ({mel_item.category}) is less restrictive than MMEL ({mmel_item.category})"
                    ]

                result = AuditResult(
                    session_id=session.id,
                    mel_item_id=mel_item.id,
                    mmel_item_id=mmel_item.id,
                    mel_item_number=mel_item.item_number,
                    mmel_item_number=mmel_item.item_number,
                    ata_chapter=mel_item.ata_chapter,
                    item_description=mel_item.item_description or mmel_item.item_description,
                    verdict=verdict,
                    severity=severity,
                    mel_category=mel_item.category,
                    mmel_category=mmel_item.category,
                    mel_remarks=mel_item.remarks,
                    mmel_remarks=mmel_item.remarks,
                    requires_hitl=requires_hitl,
                    hitl_reasons=hitl_reasons,
                    sla_hours=48 if severity == "critical" else None
                )
                db.add(result)
                results.append(result)
            else:
                # MEL item not in MMEL
                result = AuditResult(
                    session_id=session.id,
                    mel_item_id=mel_item.id,
                    mmel_item_id=None,
                    mel_item_number=mel_item.item_number,
                    mmel_item_number=None,
                    ata_chapter=mel_item.ata_chapter,
                    item_description=mel_item.item_description,
                    verdict="MISSING_IN_MMEL",
                    severity="warning",
                    mel_category=mel_item.category,
                    mmel_category=None,
                    mel_remarks=mel_item.remarks,
                    mmel_remarks=None,
                    requires_hitl=True,
                    hitl_reasons=["Item exists in MEL but not in MMEL"]
                )
                db.add(result)
                results.append(result)

        # Check for MMEL items missing in MEL
        for mmel_item in mmel_items:
            if mmel_item.item_number not in mel_index:
                result = AuditResult(
                    session_id=session.id,
                    mel_item_id=None,
                    mmel_item_id=mmel_item.id,
                    mel_item_number=None,
                    mmel_item_number=mmel_item.item_number,
                    ata_chapter=mmel_item.ata_chapter,
                    item_description=mmel_item.item_description,
                    verdict="MISSING_IN_MEL",
                    severity="high",
                    mel_category=None,
                    mmel_category=mmel_item.category,
                    mel_remarks=None,
                    mmel_remarks=mmel_item.remarks,
                    requires_hitl=True,
                    hitl_reasons=["Item exists in MMEL but not in MEL"]
                )
                db.add(result)
                results.append(result)

        # Update session
        session.status = "step_6_results"
        session.current_step = 6
        session.updated_at = datetime.utcnow()
        db.commit()

        # Calculate statistics
        stats = {
            "total": len(results),
            "compliant": sum(1 for r in results if r.verdict == "COMPLIANT"),
            "more_restrictive": sum(1 for r in results if r.verdict == "MORE_RESTRICTIVE"),
            "less_restrictive": sum(1 for r in results if r.verdict == "LESS_RESTRICTIVE"),
            "missing_in_mel": sum(1 for r in results if r.verdict == "MISSING_IN_MEL"),
            "missing_in_mmel": sum(1 for r in results if r.verdict == "MISSING_IN_MMEL"),
            "hitl_required": sum(1 for r in results if r.requires_hitl)
        }

        return {
            "message": "Audit completed",
            "statistics": stats,
            "next_step": 6
        }
    finally:
        db.close()


# ----- Step 6: Results & Classification -----

@app.get("/api/sessions/{session_id}/step6/results")
async def step6_get_results(
    session_id: str,
    verdict: Optional[str] = None,
    severity: Optional[str] = None,
    chapter: Optional[str] = None,
    hitl_only: bool = False,
    page: int = 1,
    per_page: int = 50
):
    """Step 6: Get audit results with filtering"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        query = db.query(AuditResult).filter(
            AuditResult.session_id == session.id
        )

        if verdict:
            query = query.filter(AuditResult.verdict == verdict)
        if severity:
            query = query.filter(AuditResult.severity == severity)
        if chapter:
            query = query.filter(AuditResult.ata_chapter == chapter)
        if hitl_only:
            query = query.filter(AuditResult.requires_hitl == True)

        total = query.count()
        results = query.order_by(
            AuditResult.severity.desc(),
            AuditResult.ata_chapter,
            AuditResult.mel_item_number
        ).offset((page - 1) * per_page).limit(per_page).all()

        # Get statistics
        all_results = db.query(AuditResult).filter(
            AuditResult.session_id == session.id
        ).all()

        stats = {
            "total": len(all_results),
            "by_verdict": {},
            "by_severity": {},
            "hitl_required": 0,
            "hitl_validated": 0
        }

        for r in all_results:
            stats["by_verdict"][r.verdict] = stats["by_verdict"].get(r.verdict, 0) + 1
            stats["by_severity"][r.severity] = stats["by_severity"].get(r.severity, 0) + 1
            if r.requires_hitl:
                stats["hitl_required"] += 1
                if r.hitl_status != "pending":
                    stats["hitl_validated"] += 1

        # Calculate compliance rate
        compliant = stats["by_verdict"].get("COMPLIANT", 0)
        more_restrictive = stats["by_verdict"].get("MORE_RESTRICTIVE", 0)
        stats["compliance_rate"] = round(
            (compliant + more_restrictive) / stats["total"] * 100, 2
        ) if stats["total"] > 0 else 0

        return {
            "results": [r.to_dict() for r in results],
            "total": total,
            "page": page,
            "per_page": per_page,
            "statistics": stats
        }
    finally:
        db.close()


@app.get("/api/sessions/{session_id}/step6/summary")
async def step6_get_summary(session_id: str):
    """Step 6: Get audit summary"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        results = db.query(AuditResult).filter(
            AuditResult.session_id == session.id
        ).all()

        # Count by verdict
        by_verdict = {}
        by_severity = {}
        by_chapter = {}
        critical_items = []

        for r in results:
            by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
            by_severity[r.severity] = by_severity.get(r.severity, 0) + 1

            ch = r.ata_chapter or "00"
            if ch not in by_chapter:
                by_chapter[ch] = {"total": 0, "issues": 0}
            by_chapter[ch]["total"] += 1
            if r.verdict not in ["COMPLIANT", "MORE_RESTRICTIVE"]:
                by_chapter[ch]["issues"] += 1

            if r.severity == "critical":
                critical_items.append(r.to_dict())

        total = len(results)
        compliant = by_verdict.get("COMPLIANT", 0)
        more_restrictive = by_verdict.get("MORE_RESTRICTIVE", 0)

        return {
            "session": session.to_dict(),
            "summary": {
                "total_comparisons": total,
                "compliant": compliant,
                "more_restrictive": more_restrictive,
                "less_restrictive": by_verdict.get("LESS_RESTRICTIVE", 0),
                "missing_in_mel": by_verdict.get("MISSING_IN_MEL", 0),
                "missing_in_mmel": by_verdict.get("MISSING_IN_MMEL", 0),
                "compliance_rate": round((compliant + more_restrictive) / total * 100, 2) if total > 0 else 0
            },
            "by_severity": by_severity,
            "by_chapter": by_chapter,
            "critical_items": critical_items[:10]  # Top 10 critical
        }
    finally:
        db.close()


@app.post("/api/sessions/{session_id}/step6/hitl/{result_id}")
async def step6_validate_hitl(session_id: str, result_id: int, request: HITLValidation):
    """Step 6: Validate a HITL item"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        result = db.query(AuditResult).filter(
            AuditResult.id == result_id,
            AuditResult.session_id == session.id
        ).first()

        if not result:
            raise HTTPException(status_code=404, detail="Result not found")

        result.hitl_status = request.decision
        result.hitl_validated_by = request.validated_by
        result.hitl_validated_at = datetime.utcnow()
        result.hitl_comments = request.comments

        db.commit()

        return result.to_dict()
    finally:
        db.close()


@app.post("/api/sessions/{session_id}/step6/complete")
async def step6_complete(session_id: str, request: StepValidationRequest):
    """Step 6: Mark audit as complete"""
    db = get_db()
    try:
        session = db.query(AuditSession).filter(
            AuditSession.session_id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Create validation record
        results = db.query(AuditResult).filter(
            AuditResult.session_id == session.id
        ).all()

        hitl_pending = sum(1 for r in results if r.requires_hitl and r.hitl_status == "pending")

        validation = StepValidation(
            session_id=session.id,
            step_number=6,
            step_name="Audit Results Review",
            status="validated",
            validated_at=datetime.utcnow(),
            validated_by=request.validated_by,
            items_count=len(results),
            notes=request.notes
        )
        db.add(validation)

        # Update session
        session.status = "completed"
        session.completed_at = datetime.utcnow()
        session.updated_at = datetime.utcnow()
        db.commit()

        return {
            "message": "Audit completed successfully",
            "session": session.to_dict(),
            "hitl_pending": hitl_pending
        }
    finally:
        db.close()


# ----- Dashboard (SPA entry point) -----

@app.get("/app", response_class=HTMLResponse)
async def serve_app():
    """Serve the React SPA"""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    else:
        # Return inline HTML that loads React
        return """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MoA_MEL Audit</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-gray-100">
    <div id="root"></div>
    <script type="text/babel" src="/static/app.jsx"></script>
</body>
</html>
        """


# ============== Startup ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
