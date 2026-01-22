"""
MoA_MEL API Server
==================
API FastAPI pour le pipeline d'audit MEL/MMEL.
Endpoints pour n8n et interface web.
Support complet du parsing PDF avec Docling + Mistral AI.
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from pathlib import Path
import json
import shutil
import uuid
from datetime import datetime
import asyncio
import logging
import os
import traceback
import base64

# Import pipeline
from .pipeline import MoAMELPipeline

# Try to import PDF parsing modules
PDF_PARSING_AVAILABLE = False
MISTRAL_CLIENT = None
try:
    from mistralai import Mistral
    PDF_PARSING_AVAILABLE = True
except ImportError:
    logger.warning("mistralai not available - PDF parsing disabled")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MoA_MEL_API")

# Get API key from environment
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")

app = FastAPI(
    title="MoA_MEL Audit API",
    description="API pour l'audit automatisé MEL/MMEL",
    version="1.0.0-poc"
)

# CORS pour l'interface web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
UPLOAD_DIR = Path("data/uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# State storage (in-memory pour PoC)
audit_jobs = {}


class AuditRequest(BaseModel):
    """Requête d'audit"""
    mel_path: str
    mmel_path: str
    api_key: Optional[str] = ""
    mel_is_json: bool = False
    mmel_is_json: bool = False


class AuditStatus(BaseModel):
    """Statut d'un audit"""
    job_id: str
    status: str
    progress: int
    message: str
    result: Optional[Dict[str, Any]] = None


class FullAuditRequest(BaseModel):
    """Requête d'audit complet avec chemins de fichiers uploadés"""
    mel_file_path: str
    mmel_file_path: str
    aircraft_msn: Optional[int] = 0
    operation_type: Optional[str] = "CAT"
    aircraft_type: Optional[str] = ""


# State storage for parsing jobs
parsing_jobs = {}


# ============== PDF Parsing Functions ==============

def encode_pdf_to_base64(file_path: str) -> str:
    """Encode a PDF file to base64 string"""
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def parse_pdf_with_mistral(file_path: str, doc_type: str) -> Dict[str, Any]:
    """Parse a PDF using Mistral AI vision capabilities"""
    global MISTRAL_CLIENT

    if not PDF_PARSING_AVAILABLE:
        raise Exception("Mistral AI library not installed")

    if not MISTRAL_API_KEY:
        raise Exception("MISTRAL_API_KEY not configured")

    if MISTRAL_CLIENT is None:
        MISTRAL_CLIENT = Mistral(api_key=MISTRAL_API_KEY)

    # Read PDF and convert pages to images using PyMuPDF
    import fitz  # PyMuPDF

    pdf_doc = fitz.open(file_path)
    all_items = []

    logger.info(f"Parsing {doc_type} PDF with {len(pdf_doc)} pages")

    # Process each page
    for page_num in range(min(len(pdf_doc), 50)):  # Limit to 50 pages for PoC
        page = pdf_doc[page_num]

        # Convert page to image
        mat = fitz.Matrix(2, 2)  # 2x zoom for better quality
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")

        # Call Mistral with vision
        prompt = f"""Analyze this {doc_type.upper()} ({"Minimum Equipment List" if doc_type == "mel" else "Master Minimum Equipment List"}) page.

Extract ALL equipment items from this page in JSON format. For each item found, provide:
- ata_chapter: The ATA chapter number (e.g., "24", "27")
- item_number: The item number (e.g., "24-10-01")
- item_description: Equipment name/description
- category: Dispatch category (A, B, C, or D)
- remarks: Any remarks, conditions, or notes (include (O), (M) symbols)
- quantity_installed: Number installed if shown
- quantity_required: Number required for dispatch if shown

Return a JSON object with format:
{{"items": [{{...}}, {{...}}], "page_number": {page_num + 1}, "has_more_items": true/false}}

If this page has no MEL/MMEL items (e.g., cover page, TOC), return: {{"items": [], "page_number": {page_num + 1}, "has_more_items": false}}
"""

        try:
            response = MISTRAL_CLIENT.chat.complete(
                model="pixtral-12b-2409",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": f"data:image/png;base64,{img_base64}"}
                        ]
                    }
                ]
            )

            result_text = response.choices[0].message.content

            # Try to parse JSON from response
            try:
                # Find JSON in response
                import re
                json_match = re.search(r'\{[\s\S]*\}', result_text)
                if json_match:
                    page_data = json.loads(json_match.group())
                    items = page_data.get("items", [])
                    for item in items:
                        item["source_page"] = page_num + 1
                        item["doc_type"] = doc_type
                    all_items.extend(items)
                    logger.info(f"Page {page_num + 1}: extracted {len(items)} items")
            except json.JSONDecodeError as e:
                logger.warning(f"Could not parse JSON from page {page_num + 1}: {e}")

        except Exception as e:
            logger.error(f"Error processing page {page_num + 1}: {e}")
            continue

    pdf_doc.close()

    return {
        "doc_type": doc_type,
        "file_path": file_path,
        "total_pages": len(pdf_doc),
        "total_items": len(all_items),
        "items": all_items,
        "parsed_at": datetime.now().isoformat()
    }


async def run_parsing_task(job_id: str, file_path: str, doc_type: str):
    """Background task for PDF parsing"""
    try:
        parsing_jobs[job_id]["status"] = "running"
        parsing_jobs[job_id]["progress"] = 10
        parsing_jobs[job_id]["message"] = f"Starting {doc_type.upper()} parsing..."

        # Run parsing in executor to not block
        import concurrent.futures
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(
                pool, parse_pdf_with_mistral, file_path, doc_type
            )

        # Save result to file
        output_path = OUTPUT_DIR / f"parsed_{doc_type}_{job_id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        parsing_jobs[job_id]["status"] = "completed"
        parsing_jobs[job_id]["progress"] = 100
        parsing_jobs[job_id]["message"] = f"Parsed {result['total_items']} items"
        parsing_jobs[job_id]["result"] = {
            "output_path": str(output_path),
            "total_items": result["total_items"],
            "total_pages": result["total_pages"]
        }
        parsing_jobs[job_id]["completed_at"] = datetime.now().isoformat()

    except Exception as e:
        logger.error(f"Parsing failed for job {job_id}: {e}\n{traceback.format_exc()}")
        parsing_jobs[job_id]["status"] = "failed"
        parsing_jobs[job_id]["message"] = str(e)


# ============== API Endpoints ==============

@app.get("/")
async def root():
    """Page d'accueil"""
    return {"message": "MoA_MEL Audit API", "version": "1.0.0-poc"}


@app.get("/health")
async def health_check():
    """Health check pour monitoring"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/api/upload/{doc_type}")
async def upload_document(doc_type: str, file: UploadFile = File(...)):
    """Upload un document MEL ou MMEL"""
    if doc_type not in ["mel", "mmel"]:
        raise HTTPException(status_code=400, detail="doc_type must be 'mel' or 'mmel'")
    
    # Générer un nom unique
    file_ext = Path(file.filename).suffix
    unique_name = f"{doc_type}_{uuid.uuid4().hex[:8]}{file_ext}"
    file_path = UPLOAD_DIR / unique_name
    
    # Sauvegarder le fichier
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    return {
        "filename": unique_name,
        "path": str(file_path),
        "doc_type": doc_type,
        "size": file_path.stat().st_size
    }


@app.get("/api/capabilities")
async def get_capabilities():
    """Returns the API capabilities including PDF parsing availability"""
    return {
        "pdf_parsing_available": PDF_PARSING_AVAILABLE,
        "mistral_configured": bool(MISTRAL_API_KEY),
        "supported_formats": ["pdf", "json"],
        "max_pdf_pages": 50,
        "version": "1.0.0-poc"
    }


@app.post("/api/parse/{doc_type}")
async def start_parsing(
    doc_type: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """Upload and parse a PDF document (MEL or MMEL)"""
    if doc_type not in ["mel", "mmel"]:
        raise HTTPException(status_code=400, detail="doc_type must be 'mel' or 'mmel'")

    if not PDF_PARSING_AVAILABLE:
        raise HTTPException(status_code=503, detail="PDF parsing not available - mistralai not installed")

    if not MISTRAL_API_KEY:
        raise HTTPException(status_code=503, detail="MISTRAL_API_KEY not configured")

    # Check file extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Save uploaded file
    job_id = uuid.uuid4().hex[:12]
    unique_name = f"{doc_type}_{job_id}{file_ext}"
    file_path = UPLOAD_DIR / unique_name

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Initialize parsing job
    parsing_jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Parsing queued",
        "doc_type": doc_type,
        "filename": file.filename,
        "file_path": str(file_path),
        "result": None,
        "started_at": datetime.now().isoformat()
    }

    # Start background parsing
    background_tasks.add_task(run_parsing_task, job_id, str(file_path), doc_type)

    return {
        "job_id": job_id,
        "status": "started",
        "doc_type": doc_type,
        "filename": file.filename
    }


@app.get("/api/parse/status/{job_id}")
async def get_parsing_status(job_id: str):
    """Get the status of a parsing job"""
    if job_id not in parsing_jobs:
        raise HTTPException(status_code=404, detail="Parsing job not found")

    return parsing_jobs[job_id]


@app.get("/api/parse/result/{job_id}")
async def get_parsing_result(job_id: str):
    """Get the full result of a completed parsing job"""
    if job_id not in parsing_jobs:
        raise HTTPException(status_code=404, detail="Parsing job not found")

    job = parsing_jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Parsing not completed: {job['status']}")

    # Load the parsed data
    output_path = job["result"]["output_path"]
    if Path(output_path).exists():
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return job["result"]


@app.post("/api/audit/full")
async def start_full_audit(
    background_tasks: BackgroundTasks,
    mel_file: UploadFile = File(...),
    mmel_file: UploadFile = File(...),
    aircraft_msn: int = Form(0),
    operation_type: str = Form("CAT")
):
    """Start a full audit with PDF upload, parsing, and comparison"""
    if not PDF_PARSING_AVAILABLE:
        raise HTTPException(status_code=503, detail="PDF parsing not available")

    if not MISTRAL_API_KEY:
        raise HTTPException(status_code=503, detail="MISTRAL_API_KEY not configured")

    job_id = uuid.uuid4().hex[:12]

    # Save uploaded files
    mel_path = UPLOAD_DIR / f"mel_{job_id}.pdf"
    mmel_path = UPLOAD_DIR / f"mmel_{job_id}.pdf"

    with open(mel_path, "wb") as f:
        shutil.copyfileobj(mel_file.file, f)
    with open(mmel_path, "wb") as f:
        shutil.copyfileobj(mmel_file.file, f)

    # Initialize audit job
    audit_jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Full audit queued - will parse then compare",
        "mel_filename": mel_file.filename,
        "mmel_filename": mmel_file.filename,
        "aircraft_msn": aircraft_msn,
        "operation_type": operation_type,
        "result": None,
        "started_at": datetime.now().isoformat()
    }

    # Start background full audit
    background_tasks.add_task(
        run_full_audit_task,
        job_id,
        str(mel_path),
        str(mmel_path),
        aircraft_msn,
        operation_type
    )

    return {
        "job_id": job_id,
        "status": "started",
        "message": "Full audit started - parsing PDFs then comparing"
    }


async def run_full_audit_task(
    job_id: str,
    mel_path: str,
    mmel_path: str,
    aircraft_msn: int,
    operation_type: str
):
    """Background task for full audit (parse + compare)"""
    try:
        import concurrent.futures
        loop = asyncio.get_event_loop()

        # Phase 1: Parse MEL
        audit_jobs[job_id]["status"] = "running"
        audit_jobs[job_id]["progress"] = 5
        audit_jobs[job_id]["message"] = "Parsing MEL document..."

        with concurrent.futures.ThreadPoolExecutor() as pool:
            mel_result = await loop.run_in_executor(
                pool, parse_pdf_with_mistral, mel_path, "mel"
            )

        mel_json_path = OUTPUT_DIR / f"parsed_mel_{job_id}.json"
        with open(mel_json_path, "w", encoding="utf-8") as f:
            json.dump(mel_result, f, indent=2, ensure_ascii=False)

        audit_jobs[job_id]["progress"] = 35
        audit_jobs[job_id]["message"] = f"MEL parsed: {mel_result['total_items']} items. Parsing MMEL..."

        # Phase 2: Parse MMEL
        with concurrent.futures.ThreadPoolExecutor() as pool:
            mmel_result = await loop.run_in_executor(
                pool, parse_pdf_with_mistral, mmel_path, "mmel"
            )

        mmel_json_path = OUTPUT_DIR / f"parsed_mmel_{job_id}.json"
        with open(mmel_json_path, "w", encoding="utf-8") as f:
            json.dump(mmel_result, f, indent=2, ensure_ascii=False)

        audit_jobs[job_id]["progress"] = 70
        audit_jobs[job_id]["message"] = f"MMEL parsed: {mmel_result['total_items']} items. Running comparison..."

        # Phase 3: Run comparison
        try:
            pipeline = MoAMELPipeline(api_key=MISTRAL_API_KEY, output_dir=str(OUTPUT_DIR))
            comparison_result = pipeline.run_full_pipeline(
                mel_source=str(mel_json_path),
                mmel_source=str(mmel_json_path),
                mel_is_json=True,
                mmel_is_json=True
            )
        except Exception as comp_error:
            # Fallback: create a basic comparison result
            logger.warning(f"Pipeline comparison failed, creating basic result: {comp_error}")
            comparison_result = create_basic_comparison(mel_result, mmel_result, job_id)

        audit_jobs[job_id]["status"] = "completed"
        audit_jobs[job_id]["progress"] = 100
        audit_jobs[job_id]["message"] = "Full audit completed"
        audit_jobs[job_id]["result"] = {
            "run_id": job_id,
            "mel_items": mel_result["total_items"],
            "mmel_items": mmel_result["total_items"],
            "mel_parsed_path": str(mel_json_path),
            "mmel_parsed_path": str(mmel_json_path),
            **comparison_result
        }
        audit_jobs[job_id]["completed_at"] = datetime.now().isoformat()

    except Exception as e:
        logger.error(f"Full audit failed for job {job_id}: {e}\n{traceback.format_exc()}")
        audit_jobs[job_id]["status"] = "failed"
        audit_jobs[job_id]["message"] = str(e)


def create_basic_comparison(mel_result: Dict, mmel_result: Dict, job_id: str) -> Dict:
    """Create a basic comparison when the pipeline fails"""
    mel_items = {item.get("item_number"): item for item in mel_result.get("items", [])}
    mmel_items = {item.get("item_number"): item for item in mmel_result.get("items", [])}

    comparisons = []
    compliant = 0
    less_restrictive = 0
    more_restrictive = 0
    missing_in_mel = 0

    # Compare MMEL items against MEL
    for item_num, mmel_item in mmel_items.items():
        mel_item = mel_items.get(item_num)

        if not mel_item:
            comparisons.append({
                "item_number": item_num,
                "item_description": mmel_item.get("item_description", ""),
                "ata_chapter": mmel_item.get("ata_chapter", ""),
                "verdict": "MISSING_IN_MEL",
                "severity": "warning",
                "mel_category": "",
                "mmel_category": mmel_item.get("category", ""),
                "mel_remarks": "",
                "mmel_remarks": mmel_item.get("remarks", "")
            })
            missing_in_mel += 1
        else:
            mel_cat = mel_item.get("category", "")
            mmel_cat = mmel_item.get("category", "")

            # Compare categories (A is most restrictive, D is least)
            cat_order = {"A": 1, "B": 2, "C": 3, "D": 4}
            mel_order = cat_order.get(mel_cat, 5)
            mmel_order = cat_order.get(mmel_cat, 5)

            if mel_order == mmel_order:
                verdict = "COMPLIANT"
                severity = "info"
                compliant += 1
            elif mel_order > mmel_order:
                verdict = "LESS_RESTRICTIVE"
                severity = "critical"
                less_restrictive += 1
            else:
                verdict = "MORE_RESTRICTIVE"
                severity = "info"
                more_restrictive += 1

            comparisons.append({
                "item_number": item_num,
                "item_description": mel_item.get("item_description", ""),
                "ata_chapter": mel_item.get("ata_chapter", ""),
                "verdict": verdict,
                "severity": severity,
                "mel_category": mel_cat,
                "mmel_category": mmel_cat,
                "mel_remarks": mel_item.get("remarks", ""),
                "mmel_remarks": mmel_item.get("remarks", "")
            })

    total = len(comparisons)

    return {
        "summary": {
            "total": total,
            "compliant": compliant,
            "more_restrictive": more_restrictive,
            "less_restrictive": less_restrictive,
            "missing_in_mel": missing_in_mel,
            "missing_in_mmel": len(mel_items) - (total - missing_in_mel),
            "compliance_rate": round((compliant + more_restrictive) / total * 100, 2) if total > 0 else 0
        },
        "severity_breakdown": {
            "critical": less_restrictive,
            "high": 0,
            "medium": 0,
            "warning": missing_in_mel,
            "info": compliant + more_restrictive
        },
        "comparisons": comparisons[:100]  # Limit for response size
    }


@app.post("/api/audit/start")
async def start_audit(request: AuditRequest, background_tasks: BackgroundTasks):
    """Démarre un audit en arrière-plan"""
    job_id = uuid.uuid4().hex[:12]
    
    # Vérifier les fichiers
    mel_path = Path(request.mel_path)
    mmel_path = Path(request.mmel_path)
    
    if not mel_path.exists():
        raise HTTPException(status_code=404, detail=f"MEL file not found: {request.mel_path}")
    if not mmel_path.exists():
        raise HTTPException(status_code=404, detail=f"MMEL file not found: {request.mmel_path}")
    
    # Initialiser le job
    audit_jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Audit queued",
        "result": None,
        "started_at": datetime.now().isoformat()
    }
    
    # Lancer en background
    background_tasks.add_task(
        run_audit_task,
        job_id,
        str(mel_path),
        str(mmel_path),
        request.api_key,
        request.mel_is_json,
        request.mmel_is_json
    )
    
    return {"job_id": job_id, "status": "started"}


async def run_audit_task(job_id: str, mel_path: str, mmel_path: str,
                        api_key: str, mel_is_json: bool, mmel_is_json: bool):
    """Tâche d'audit en arrière-plan"""
    try:
        audit_jobs[job_id]["status"] = "running"
        audit_jobs[job_id]["progress"] = 10
        audit_jobs[job_id]["message"] = "Initializing pipeline..."
        
        pipeline = MoAMELPipeline(api_key=api_key, output_dir=str(OUTPUT_DIR))
        
        audit_jobs[job_id]["progress"] = 20
        audit_jobs[job_id]["message"] = "Parsing MEL document..."
        
        # Exécuter le pipeline
        result = pipeline.run_full_pipeline(
            mel_source=mel_path,
            mmel_source=mmel_path,
            mel_is_json=mel_is_json,
            mmel_is_json=mmel_is_json
        )
        
        audit_jobs[job_id]["status"] = "completed"
        audit_jobs[job_id]["progress"] = 100
        audit_jobs[job_id]["message"] = "Audit completed successfully"
        audit_jobs[job_id]["result"] = result
        audit_jobs[job_id]["completed_at"] = datetime.now().isoformat()
        
    except Exception as e:
        logger.error(f"Audit failed for job {job_id}: {e}")
        audit_jobs[job_id]["status"] = "failed"
        audit_jobs[job_id]["message"] = str(e)


@app.get("/api/audit/status/{job_id}")
async def get_audit_status(job_id: str):
    """Récupère le statut d'un audit"""
    if job_id not in audit_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return audit_jobs[job_id]


@app.get("/api/audit/result/{job_id}")
async def get_audit_result(job_id: str):
    """Récupère le résultat complet d'un audit"""
    if job_id not in audit_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = audit_jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Audit not completed: {job['status']}")
    
    # Charger le résultat complet depuis le fichier
    result_path = job["result"].get("output_files", {}).get("audit_result")
    if result_path and Path(result_path).exists():
        with open(result_path, "r") as f:
            return json.load(f)
    
    return job["result"]


@app.get("/api/audits")
async def list_audits():
    """Liste tous les audits"""
    return {
        "audits": [
            {
                "job_id": job_id,
                "status": job["status"],
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at")
            }
            for job_id, job in audit_jobs.items()
        ]
    }


@app.get("/api/hitl/{job_id}")
async def get_hitl_items(job_id: str):
    """Récupère les items nécessitant review HITL"""
    if job_id not in audit_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = audit_jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Audit not completed")
    
    # Charger le fichier HITL
    result = job.get("result", {})
    run_id = result.get("run_id", "")
    hitl_path = OUTPUT_DIR / f"hitl_audit_{run_id}.json"
    
    if hitl_path.exists():
        with open(hitl_path, "r") as f:
            return json.load(f)
    
    return {"items": []}


@app.post("/api/hitl/{job_id}/validate/{item_id}")
async def validate_hitl_item(job_id: str, item_id: str, 
                            decision: str, 
                            comments: Optional[str] = None,
                            validated_by: Optional[str] = None):
    """Valide un item HITL"""
    if decision not in ["ACCEPT", "REJECT", "ESCALATE"]:
        raise HTTPException(status_code=400, detail="Invalid decision")
    
    # TODO: Implémenter la persistance
    return {
        "item_id": item_id,
        "decision": decision,
        "validated_by": validated_by,
        "validated_at": datetime.now().isoformat(),
        "comments": comments
    }


# ============== Webhooks pour n8n ==============

@app.post("/webhook/n8n/audit")
async def n8n_audit_webhook(request: AuditRequest, background_tasks: BackgroundTasks):
    """Webhook pour déclencher un audit depuis n8n"""
    return await start_audit(request, background_tasks)


@app.post("/webhook/n8n/parse")
async def n8n_parse_webhook(doc_type: str, file_path: str, api_key: str = ""):
    """Webhook pour parser un document depuis n8n"""
    from mel_parser import MELParser, create_mock_parsing_result
    
    if not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    if api_key:
        parser = MELParser(api_key)
        result = parser.parse_pdf(file_path)
        output_path = OUTPUT_DIR / f"parsed_{doc_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        parser.save_parsing_result(result, str(output_path))
        return {"output_path": str(output_path), "items_count": result.total_items}
    else:
        result = create_mock_parsing_result(file_path, doc_type.upper())
        return {"items_count": result.total_items, "items": [i.to_dict() for i in result.items]}


# ============== Interface Web ==============

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Page du dashboard (servi depuis le build React)"""
    # Pour le PoC, servir une page HTML simple qui charge le React bundle
    return """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MoA_MEL Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
        <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    </head>
    <body>
        <div id="root"></div>
        <script>
            // Pour le PoC, les données sont intégrées
            // En production, charger depuis l'API
            console.log("Dashboard loading...");
            // Le composant React sera monté ici
        </script>
    </body>
    </html>
    """


@app.get("/api/demo-data")
async def get_demo_data():
    """Données de démonstration pour le dashboard"""
    return {
        "run_id": "20260102_143052",
        "mel_document": "Air_France_A320_MEL.pdf",
        "mmel_document": "A320_MMEL_Rev42.pdf",
        "audit_timestamp": datetime.now().isoformat(),
        "summary": {
            "total": 487,
            "compliant": 412,
            "more_restrictive": 35,
            "less_restrictive": 8,
            "missing_in_mel": 22,
            "missing_in_mmel": 5,
            "other_deviations": 5,
            "hitl_required": 40,
            "compliance_rate": 91.78
        },
        "severity_breakdown": {
            "critical": 8,
            "high": 15,
            "medium": 12,
            "warning": 22,
            "info": 430
        },
        "comparisons": [
            {
                "mel_item_id": "24|24-10-01",
                "mmel_item_id": "24|24-10-01",
                "ata_chapter": "24",
                "item_number": "24-10-01",
                "item_description": "Main Battery",
                "verdict": "LESS_RESTRICTIVE",
                "severity": "critical",
                "mel_category": "B",
                "mmel_category": "A",
                "mel_remarks": "May be inoperative",
                "mmel_remarks": "Go item - must be operative",
                "hitl_reason": "CRITICAL: MEL less restrictive than MMEL"
            },
            {
                "mel_item_id": "21|21-51-01",
                "mmel_item_id": "21|21-51-01",
                "ata_chapter": "21",
                "item_number": "21-51-01",
                "item_description": "Air Conditioning Pack",
                "verdict": "COMPLIANT",
                "severity": "info",
                "mel_category": "C",
                "mmel_category": "C",
                "mel_remarks": "(O) May be inoperative provided remaining pack operates normally",
                "mmel_remarks": "(O) May be inoperative provided remaining pack operates normally"
            },
            {
                "mel_item_id": "32|32-40-01",
                "mmel_item_id": "32|32-40-01",
                "ata_chapter": "32",
                "item_number": "32-40-01",
                "item_description": "Nose Wheel Steering System",
                "verdict": "MORE_RESTRICTIVE",
                "severity": "info",
                "mel_category": "B",
                "mmel_category": "C",
                "mel_remarks": "(M) Requires maintenance before dispatch",
                "mmel_remarks": "May be inoperative"
            }
        ]
    }


# ============== Démarrage ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
