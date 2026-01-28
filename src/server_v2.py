"""
MoA_MEL API Server V2
=====================
API FastAPI pour le pipeline d'audit MEL/MMEL V2.
Supporte l'interface web d'audit.
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
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
import logging
import sys
import os

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Import pipeline V2
from pipeline_v2 import MoAMELPipelineV2, PipelineConfigV2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MoA_MEL_API_V2")

app = FastAPI(
    title="MoA_MEL Audit API V2",
    description="API pour l'audit automatise MEL/MMEL avec pipeline V2",
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

# State storage (in-memory pour PoC)
audit_jobs: Dict[str, Dict] = {}


# ============== Pydantic Models ==============

class AuditRequestV2(BaseModel):
    """Requete d'audit V2"""
    mel_path: str
    mmel_path: str
    mel_is_json: bool = False
    mmel_is_json: bool = False
    msn: int = 0
    # Nouveau: liste d'operations au lieu d'une seule
    operations: List[str] = ["CAT"]
    # Retrocompatibilite: ancien champ single operation (deprecated)
    operation: Optional[str] = None
    aircraft_type: str = ""
    etops: bool = False
    api_key: Optional[str] = ""

    def get_operations(self) -> List[str]:
        """Retourne la liste d'operations, avec retrocompatibilite"""
        # Si operation (ancien format) est fourni et operations est default
        if self.operation and self.operations == ["CAT"]:
            return [self.operation]
        return self.operations


class AuditStatusV2(BaseModel):
    """Statut d'un audit"""
    job_id: str
    status: str
    progress: int
    message: str
    result: Optional[Dict[str, Any]] = None


# ============== Static Files ==============

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============== API Endpoints ==============

@app.get("/")
async def root():
    """Page d'accueil - redirige vers l'interface d'audit"""
    return FileResponse(str(STATIC_DIR / "audit_ui.html"))


@app.get("/audit")
async def audit_page():
    """Page d'audit"""
    return FileResponse(str(STATIC_DIR / "audit_ui.html"))


@app.get("/health")
async def health_check():
    """Health check pour monitoring"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "pipeline": "v2",
        "timestamp": datetime.now().isoformat()
    }


# ============== Upload Endpoints ==============

@app.post("/api/v2/upload/{doc_type}")
async def upload_document(doc_type: str, file: UploadFile = File(...)):
    """Upload un document MEL ou MMEL"""
    if doc_type not in ["mel", "mmel"]:
        raise HTTPException(status_code=400, detail="doc_type must be 'mel' or 'mmel'")

    # Generer un nom unique
    file_ext = Path(file.filename).suffix
    unique_name = f"{doc_type}_{uuid.uuid4().hex[:8]}{file_ext}"
    file_path = UPLOAD_DIR / unique_name

    # Sauvegarder le fichier
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    logger.info(f"File uploaded: {unique_name} ({file_path.stat().st_size} bytes)")

    return {
        "filename": unique_name,
        "original_name": file.filename,
        "path": str(file_path),
        "doc_type": doc_type,
        "size": file_path.stat().st_size
    }


# ============== Audit Endpoints ==============

@app.post("/api/v2/audit/start")
async def start_audit_v2(request: AuditRequestV2, background_tasks: BackgroundTasks):
    """Demarre un audit V2 en arriere-plan"""
    job_id = uuid.uuid4().hex[:12]

    # Verifier les fichiers
    mel_path = Path(request.mel_path)
    mmel_path = Path(request.mmel_path)

    if not mel_path.exists():
        raise HTTPException(status_code=404, detail=f"MEL file not found: {request.mel_path}")
    if not mmel_path.exists():
        raise HTTPException(status_code=404, detail=f"MMEL file not found: {request.mmel_path}")

    # Recuperer les operations (avec retrocompatibilite)
    operations = request.get_operations()

    # Initialiser le job
    audit_jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Audit en attente",
        "result": None,
        "started_at": datetime.now().isoformat(),
        "config": {
            "msn": request.msn,
            "operations": operations,  # Liste d'operations
            "aircraft_type": request.aircraft_type,
            "etops": request.etops
        }
    }

    # Lancer en background
    background_tasks.add_task(
        run_audit_task_v2,
        job_id,
        str(mel_path),
        str(mmel_path),
        request.mel_is_json,
        request.mmel_is_json,
        request.msn,
        operations,  # Liste d'operations
        request.aircraft_type,
        request.etops,
        request.api_key or ""
    )

    logger.info(f"Audit started: {job_id}")

    return {"job_id": job_id, "status": "started"}


async def run_audit_task_v2(
    job_id: str,
    mel_path: str,
    mmel_path: str,
    mel_is_json: bool,
    mmel_is_json: bool,
    msn: int,
    operations: List[str],  # Liste d'operations
    aircraft_type: str,
    etops: bool,
    api_key: str
):
    """Tache d'audit V2 en arriere-plan"""
    try:
        audit_jobs[job_id]["status"] = "running"
        audit_jobs[job_id]["progress"] = 10
        audit_jobs[job_id]["message"] = "Initialisation du pipeline V2..."

        # Configuration
        config = PipelineConfigV2(
            api_key=api_key,
            aircraft_msn=msn,
            operation_types=operations,  # Liste d'operations
            aircraft_type=aircraft_type,
            etops_certified=etops,
            output_dir=str(OUTPUT_DIR),
            use_llm_parser=bool(api_key),
            enable_self_healing=True
        )

        pipeline = MoAMELPipelineV2(config)

        audit_jobs[job_id]["progress"] = 20
        audit_jobs[job_id]["message"] = "Parsing du document MEL..."

        # Executer le pipeline
        result = pipeline.run_full_pipeline(
            mel_source=mel_path,
            mmel_source=mmel_path,
            mel_is_json=mel_is_json,
            mmel_is_json=mmel_is_json
        )

        # Charger les comparaisons detaillees
        audit_result_path = OUTPUT_DIR / f"audit_result_v2_{pipeline.run_id}.json"
        if audit_result_path.exists():
            with open(audit_result_path, "r", encoding="utf-8") as f:
                detailed_result = json.load(f)
                result["comparisons"] = detailed_result.get("comparisons", [])

        audit_jobs[job_id]["status"] = "completed"
        audit_jobs[job_id]["progress"] = 100
        audit_jobs[job_id]["message"] = "Audit termine avec succes"
        audit_jobs[job_id]["result"] = result
        audit_jobs[job_id]["completed_at"] = datetime.now().isoformat()

        logger.info(f"Audit completed: {job_id}")

    except Exception as e:
        logger.error(f"Audit failed for job {job_id}: {e}")
        import traceback
        traceback.print_exc()
        audit_jobs[job_id]["status"] = "failed"
        audit_jobs[job_id]["message"] = str(e)


@app.get("/api/v2/audit/status/{job_id}")
async def get_audit_status_v2(job_id: str):
    """Recupere le statut d'un audit"""
    if job_id not in audit_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    return audit_jobs[job_id]


@app.get("/api/v2/audit/result/{job_id}")
async def get_audit_result_v2(job_id: str):
    """Recupere le resultat complet d'un audit"""
    if job_id not in audit_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = audit_jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Audit not completed: {job['status']}")

    return job["result"]


@app.get("/api/v2/audit/demo")
async def get_demo_audit():
    """Retourne des donnees de demonstration"""
    # Chercher le dernier fichier d'audit
    audit_files = list(OUTPUT_DIR.glob("audit_result_v2_*.json"))

    if audit_files:
        # Trier par date de modification et prendre le plus recent
        latest = max(audit_files, key=lambda p: p.stat().st_mtime)
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Charger aussi le rapport final si disponible
        run_id = latest.stem.replace("audit_result_v2_", "")
        final_report = OUTPUT_DIR / f"final_report_{run_id}.json"

        if final_report.exists():
            with open(final_report, "r", encoding="utf-8") as f:
                report = json.load(f)
                data["summary"] = report.get("summary", data.get("statistics", {}))
                data["critical_findings"] = report.get("critical_findings", [])

        return data

    # Donnees de demo par defaut
    return {
        "run_id": "demo_20260127",
        "audit_timestamp": datetime.now().isoformat(),
        "aircraft_context": {"msn": 1280, "operation": "CAT"},
        "summary": {
            "total_items_compared": 584,
            "compliant": 269,
            "more_restrictive": 9,
            "less_restrictive_critical": 121,
            "missing_items": 185,
            "compliance_rate": 47.6,
            "items_requiring_review": 305
        },
        "comparisons": [
            {
                "mel_item_id": "21-10-01A",
                "mmel_item_id": "21-10-01A",
                "verdict": "LESS_RESTRICTIVE",
                "severity": "critical",
                "match_confidence": "exact",
                "compliance_score": 0.0,
                "requires_hitl": True,
                "hitl_reasons": ["CRITIQUE: MEL moins restrictive que MMEL"],
                "sla_hours": 48
            },
            {
                "mel_item_id": "21-50-01A",
                "mmel_item_id": "21-50-01A",
                "verdict": "COMPLIANT",
                "severity": "info",
                "match_confidence": "exact",
                "compliance_score": 1.0,
                "requires_hitl": False,
                "hitl_reasons": [],
                "sla_hours": 0
            }
        ]
    }


@app.get("/api/v2/audits")
async def list_audits_v2():
    """Liste tous les audits"""
    return {
        "audits": [
            {
                "job_id": job_id,
                "status": job["status"],
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "config": job.get("config", {})
            }
            for job_id, job in audit_jobs.items()
        ]
    }


# ============== HITL Endpoints ==============

@app.get("/api/v2/hitl/{job_id}")
async def get_hitl_items_v2(job_id: str):
    """Recupere les items necessitant review HITL"""
    if job_id not in audit_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = audit_jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Audit not completed")

    result = job.get("result", {})
    comparisons = result.get("comparisons", [])

    hitl_items = [c for c in comparisons if c.get("requires_hitl")]

    return {
        "total": len(hitl_items),
        "items": hitl_items
    }


@app.post("/api/v2/hitl/{job_id}/validate/{item_id}")
async def validate_hitl_item_v2(
    job_id: str,
    item_id: str,
    decision: str,
    comments: Optional[str] = None,
    validated_by: Optional[str] = None
):
    """Valide un item HITL"""
    if decision not in ["ACCEPT", "REJECT", "ESCALATE"]:
        raise HTTPException(status_code=400, detail="Invalid decision")

    # TODO: Implémenter la persistance
    return {
        "job_id": job_id,
        "item_id": item_id,
        "decision": decision,
        "validated_by": validated_by,
        "validated_at": datetime.now().isoformat(),
        "comments": comments
    }


# ============== Fichiers de resultat ==============

@app.get("/api/v2/files/{filename}")
async def get_result_file(filename: str):
    """Telecharge un fichier de resultat"""
    file_path = OUTPUT_DIR / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(str(file_path))


# ============== Demarrage ==============

if __name__ == "__main__":
    import uvicorn

    print("""
    ================================================
    MoA_MEL Audit Server V2
    ================================================
    Interface web:  http://localhost:8080/
    API docs:       http://localhost:8080/docs
    Health check:   http://localhost:8080/health
    ================================================
    """)

    uvicorn.run(app, host="0.0.0.0", port=8080)
