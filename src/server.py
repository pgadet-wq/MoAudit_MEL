"""
MoA_MEL API Server v2.0
=======================
API FastAPI pour le pipeline d'audit MEL/MMEL.
Supporte services distants Docling/Granite-Docling.
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from pathlib import Path
import json
import shutil
import uuid
from datetime import datetime
import asyncio
import logging
import httpx

# Import configuration
try:
    from config import config, load_config_from_env, get_service_urls
    load_config_from_env()
except ImportError:
    config = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MoA_MEL_API")

app = FastAPI(
    title="MoA_MEL Audit API",
    description="API pour l'audit automatise MEL/MMEL avec Docling + Granite-Docling",
    version="2.0.0"
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
BASE_DIR = Path(__file__).parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# State storage (in-memory pour PoC)
audit_jobs: Dict[str, Dict[str, Any]] = {}


# ============== Request/Response Models ==============

class AuditRequest(BaseModel):
    """Requete d'audit"""
    mel_file: str = Field(..., description="Nom du fichier MEL uploade")
    mmel_file: str = Field(..., description="Nom du fichier MMEL uploade")
    aircraft_type: Optional[str] = Field(None, description="Type aeronef (ex: A320-214)")
    msn: Optional[str] = Field(None, description="MSN si applicable")
    operation_type: Optional[str] = Field("CAT", description="Type operation: CAT, SPO, NCO, NCC")
    operator: Optional[str] = Field(None, description="Nom operateur")
    api_key: Optional[str] = Field(None, description="API key Mistral (optionnel)")


class AuditStatus(BaseModel):
    """Statut d'un audit"""
    job_id: str
    status: str
    progress: int
    message: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class HITLValidation(BaseModel):
    """Validation HITL"""
    action: str = Field(..., description="approve, reject, escalate")
    comments: Optional[str] = None
    validated_by: Optional[str] = None


# ============== Health & Status Endpoints ==============

@app.get("/")
async def root():
    """Page d'accueil - redirige vers dashboard"""
    return FileResponse(str(STATIC_DIR / "dashboard.html"))


@app.get("/health")
async def health_check():
    """Health check pour monitoring"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "services": get_service_urls() if config else {}
    }


@app.get("/api/services/docling/health")
async def docling_health_proxy():
    """Proxy health check vers service Docling"""
    try:
        docling_url = config.docling.service_url if config else "http://localhost:8001"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{docling_url}/health")
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Docling service unavailable: {str(e)}")


@app.get("/api/services/granite/health")
async def granite_health_proxy():
    """Proxy health check vers service Granite-Docling"""
    try:
        granite_url = config.granite_docling.service_url if config else "http://localhost:8000/v1"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{granite_url}/models")
            return {"status": "healthy", "models": response.json()}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Granite-Docling service unavailable: {str(e)}")


@app.get("/api/config")
async def get_config():
    """Retourne la configuration actuelle (sans secrets)"""
    if not config:
        return {"error": "Configuration not loaded"}
    return {
        "parsing_backend": config.parsing_backend.value,
        "docling_url": config.docling.service_url,
        "granite_url": config.granite_docling.service_url,
        "storage_backend": config.storage.backend,
        "redis_enabled": config.redis.enabled
    }


# ============== Upload Endpoints ==============

@app.post("/api/upload/{doc_type}")
async def upload_document(doc_type: str, file: UploadFile = File(...)):
    """Upload un document MEL ou MMEL"""
    doc_type = doc_type.upper()
    if doc_type not in ["MEL", "MMEL"]:
        raise HTTPException(status_code=400, detail="doc_type must be 'MEL' or 'MMEL'")

    # Valider le fichier
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Generer un nom unique
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in [".pdf", ".json"]:
        raise HTTPException(status_code=400, detail="File must be PDF or JSON")

    unique_name = f"{doc_type.lower()}_{uuid.uuid4().hex[:8]}{file_ext}"
    file_path = UPLOAD_DIR / unique_name

    # Sauvegarder le fichier
    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    return {
        "filename": unique_name,
        "original_name": file.filename,
        "path": str(file_path),
        "doc_type": doc_type,
        "size": file_path.stat().st_size
    }


# ============== Audit Endpoints ==============

@app.post("/api/audit/start")
async def start_audit(request: AuditRequest, background_tasks: BackgroundTasks):
    """Demarre un audit en arriere-plan"""
    job_id = uuid.uuid4().hex[:12]

    # Verifier les fichiers
    mel_path = UPLOAD_DIR / request.mel_file
    mmel_path = UPLOAD_DIR / request.mmel_file

    if not mel_path.exists():
        raise HTTPException(status_code=404, detail=f"MEL file not found: {request.mel_file}")
    if not mmel_path.exists():
        raise HTTPException(status_code=404, detail=f"MMEL file not found: {request.mmel_file}")

    # Initialiser le job
    audit_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "progress": 0,
        "message": "Audit queued",
        "result": None,
        "error": None,
        "mel_file": request.mel_file,
        "mmel_file": request.mmel_file,
        "aircraft_type": request.aircraft_type,
        "msn": request.msn,
        "operation_type": request.operation_type,
        "operator": request.operator,
        "started_at": datetime.now().isoformat()
    }

    # Lancer en background
    background_tasks.add_task(
        run_audit_task,
        job_id,
        str(mel_path),
        str(mmel_path),
        request
    )

    return {"job_id": job_id, "status": "started"}


async def run_audit_task(job_id: str, mel_path: str, mmel_path: str, request: AuditRequest):
    """Tache d'audit en arriere-plan"""
    try:
        audit_jobs[job_id]["status"] = "processing"
        audit_jobs[job_id]["progress"] = 10
        audit_jobs[job_id]["message"] = "Parsing MEL document..."

        # Import parser
        from mel_parser_docling import parse_document_async, get_parser

        # Parse MEL
        logger.info(f"[{job_id}] Parsing MEL: {mel_path}")
        parser = get_parser()
        mel_result = await parser.parse(mel_path, "MEL")

        audit_jobs[job_id]["progress"] = 40
        audit_jobs[job_id]["message"] = "Parsing MMEL document..."

        # Parse MMEL
        logger.info(f"[{job_id}] Parsing MMEL: {mmel_path}")
        mmel_result = await parser.parse(mmel_path, "MMEL")

        audit_jobs[job_id]["progress"] = 70
        audit_jobs[job_id]["message"] = "Comparing MEL/MMEL..."

        # Import et executer la comparaison
        from mel_comparator import MELComparator

        comparator = MELComparator()

        # Convertir les resultats en format attendu
        mel_items = [item.to_dict() for item in mel_result.items]
        mmel_items = [item.to_dict() for item in mmel_result.items]

        comparisons = comparator.compare_all(mel_items, mmel_items)

        audit_jobs[job_id]["progress"] = 90
        audit_jobs[job_id]["message"] = "Generating report..."

        # Calculer les statistiques
        summary = calculate_summary(comparisons)

        # Construire le resultat
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        result = {
            "run_id": run_id,
            "mel_document": request.mel_file,
            "mmel_document": request.mmel_file,
            "aircraft_type": request.aircraft_type,
            "msn": request.msn,
            "operation_type": request.operation_type,
            "operator": request.operator,
            "audit_timestamp": datetime.now().isoformat(),
            "summary": summary,
            "severity_breakdown": calculate_severity_breakdown(comparisons),
            "comparisons": comparisons,
            "mel_statistics": mel_result.statistics,
            "mmel_statistics": mmel_result.statistics
        }

        # Sauvegarder le resultat
        output_file = OUTPUT_DIR / f"audit_{run_id}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        audit_jobs[job_id]["status"] = "completed"
        audit_jobs[job_id]["progress"] = 100
        audit_jobs[job_id]["message"] = "Audit completed successfully"
        audit_jobs[job_id]["result"] = result
        audit_jobs[job_id]["completed_at"] = datetime.now().isoformat()

        logger.info(f"[{job_id}] Audit completed: {len(comparisons)} comparisons")

    except Exception as e:
        logger.error(f"[{job_id}] Audit failed: {e}", exc_info=True)
        audit_jobs[job_id]["status"] = "failed"
        audit_jobs[job_id]["error"] = str(e)
        audit_jobs[job_id]["message"] = f"Audit failed: {str(e)}"


def calculate_summary(comparisons: List[Dict]) -> Dict:
    """Calcule les statistiques de resume"""
    total = len(comparisons)
    compliant = sum(1 for c in comparisons if c.get("verdict") == "COMPLIANT")
    more_restrictive = sum(1 for c in comparisons if c.get("verdict") == "MORE_RESTRICTIVE")
    less_restrictive = sum(1 for c in comparisons if c.get("verdict") == "LESS_RESTRICTIVE")
    missing_mel = sum(1 for c in comparisons if c.get("verdict") == "MISSING_IN_MEL")
    missing_mmel = sum(1 for c in comparisons if c.get("verdict") == "MISSING_IN_MMEL")
    other = total - compliant - more_restrictive - less_restrictive - missing_mel - missing_mmel

    hitl_required = sum(1 for c in comparisons if c.get("needs_hitl", False))

    compliance_rate = ((compliant + more_restrictive) / total * 100) if total > 0 else 0

    return {
        "total": total,
        "compliant": compliant,
        "more_restrictive": more_restrictive,
        "less_restrictive": less_restrictive,
        "missing_in_mel": missing_mel,
        "missing_in_mmel": missing_mmel,
        "other_deviations": other,
        "hitl_required": hitl_required,
        "compliance_rate": round(compliance_rate, 2)
    }


def calculate_severity_breakdown(comparisons: List[Dict]) -> Dict:
    """Calcule la repartition par severite"""
    breakdown = {"critical": 0, "high": 0, "medium": 0, "warning": 0, "info": 0}
    for c in comparisons:
        severity = c.get("severity", "info")
        if severity in breakdown:
            breakdown[severity] += 1
    return breakdown


@app.get("/api/audit/status/{job_id}", response_model=AuditStatus)
async def get_audit_status(job_id: str):
    """Recupere le statut d'un audit"""
    if job_id not in audit_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = audit_jobs[job_id]
    return AuditStatus(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        message=job["message"],
        result=job.get("result"),
        error=job.get("error")
    )


@app.get("/api/audit/result/{job_id}")
async def get_audit_result(job_id: str):
    """Recupere le resultat complet d'un audit"""
    if job_id not in audit_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = audit_jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Audit not completed: {job['status']}")

    return job.get("result", {})


@app.get("/api/audits")
async def list_audits():
    """Liste tous les audits"""
    return {
        "audits": [
            {
                "job_id": job_id,
                "status": job["status"],
                "mel_file": job.get("mel_file"),
                "mmel_file": job.get("mmel_file"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at")
            }
            for job_id, job in audit_jobs.items()
        ]
    }


# ============== HITL Endpoints ==============

@app.get("/api/hitl/{job_id}")
async def get_hitl_items(job_id: str):
    """Recupere les items necessitant review HITL"""
    if job_id not in audit_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = audit_jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Audit not completed")

    result = job.get("result", {})
    comparisons = result.get("comparisons", [])

    hitl_items = [c for c in comparisons if c.get("needs_hitl", False)]

    return {"job_id": job_id, "items": hitl_items, "count": len(hitl_items)}


@app.post("/api/hitl/{job_id}/validate/{item_id}")
async def validate_hitl_item(job_id: str, item_id: str, validation: HITLValidation):
    """Valide un item HITL"""
    if validation.action not in ["approve", "reject", "escalate"]:
        raise HTTPException(status_code=400, detail="Invalid action")

    # TODO: Persister dans Redis/DB
    logger.info(f"HITL validation: job={job_id}, item={item_id}, action={validation.action}")

    return {
        "job_id": job_id,
        "item_id": item_id,
        "action": validation.action,
        "validated_by": validation.validated_by,
        "validated_at": datetime.now().isoformat(),
        "comments": validation.comments
    }


# ============== Demo/Test Endpoints ==============

@app.get("/api/demo-data")
async def get_demo_data():
    """Donnees de demonstration pour le dashboard"""
    return {
        "run_id": "DEMO_20260122",
        "mel_document": "Sample_Airline_A320_MEL_Rev15.pdf",
        "mmel_document": "A320_MMEL_Rev42_EASA.pdf",
        "audit_timestamp": datetime.now().isoformat(),
        "summary": {
            "total": 12,
            "compliant": 5,
            "more_restrictive": 2,
            "less_restrictive": 2,
            "missing_in_mel": 2,
            "missing_in_mmel": 0,
            "other_deviations": 1,
            "hitl_required": 5,
            "compliance_rate": 58.33
        },
        "severity_breakdown": {
            "critical": 2,
            "high": 1,
            "medium": 1,
            "warning": 2,
            "info": 6
        },
        "comparisons": [
            {
                "ata_chapter": "24",
                "item_number": "24-10-01",
                "item_description": "Main Battery",
                "verdict": "LESS_RESTRICTIVE",
                "severity": "critical",
                "mel_category": "B",
                "mmel_category": "A",
                "mel_remarks": "(M) Maintenance verification required.",
                "mmel_remarks": "Go item - must be operative for dispatch.",
                "hitl_reason": "CRITICAL: MEL category B is less restrictive than MMEL A",
                "needs_hitl": True
            },
            {
                "ata_chapter": "21",
                "item_number": "21-51-01",
                "item_description": "Air Conditioning Pack",
                "verdict": "COMPLIANT",
                "severity": "info",
                "mel_category": "C",
                "mmel_category": "C",
                "mel_remarks": "(O) May be inoperative provided remaining pack operates normally.",
                "mmel_remarks": "(O) May be inoperative provided: (a) remaining pack operates normally, (b) APU bleed available.",
                "needs_hitl": False
            },
            {
                "ata_chapter": "32",
                "item_number": "32-40-01",
                "item_description": "Nose Wheel Steering System",
                "verdict": "MORE_RESTRICTIVE",
                "severity": "info",
                "mel_category": "B",
                "mmel_category": "C",
                "mel_remarks": "(M)(O) May be inoperative provided aircraft is not operated on contaminated runway.",
                "mmel_remarks": "(M)(O) May be inoperative provided: (a) runway not contaminated, (b) pushback used.",
                "needs_hitl": False
            }
        ]
    }


# ============== Startup ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
