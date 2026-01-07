"""
MoA_MEL API Server
==================
API FastAPI pour le pipeline d'audit MEL/MMEL.
Endpoints pour n8n et interface web.
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
import asyncio
import logging

# Import pipeline V2
from pipeline_v2 import MoAMELPipelineV2, PipelineConfigV2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MoA_MEL_API")

app = FastAPI(
    title="MoA_MEL Audit API",
    description="API pour l'audit automatisé MEL/MMEL avec contexte avion (MSN, Operation)",
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
UPLOAD_DIR = Path("data/uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# State storage (in-memory pour PoC)
audit_jobs = {}


class AuditRequest(BaseModel):
    """Requête d'audit V2 avec contexte avion"""
    mel_path: str
    mmel_path: str
    api_key: Optional[str] = ""
    mel_is_json: bool = False
    mmel_is_json: bool = False
    # Paramètres V2 - Contexte avion
    aircraft_msn: int = 0
    operation_type: str = "CAT"  # CAT, SPO, NCO, NCC
    aircraft_type: str = ""
    etops_certified: bool = False


class AuditStatus(BaseModel):
    """Statut d'un audit"""
    job_id: str
    status: str
    progress: int
    message: str
    result: Optional[Dict[str, Any]] = None


# ============== API Endpoints ==============

@app.get("/")
async def root():
    """Page d'accueil - redirige vers le dashboard"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard")


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
    
    # Lancer en background avec paramètres V2
    background_tasks.add_task(
        run_audit_task,
        job_id,
        str(mel_path),
        str(mmel_path),
        request.api_key,
        request.mel_is_json,
        request.mmel_is_json,
        request.aircraft_msn,
        request.operation_type,
        request.aircraft_type,
        request.etops_certified
    )

    return {"job_id": job_id, "status": "started", "aircraft_context": {
        "msn": request.aircraft_msn,
        "operation": request.operation_type
    }}


async def run_audit_task(job_id: str, mel_path: str, mmel_path: str,
                        api_key: str, mel_is_json: bool, mmel_is_json: bool,
                        aircraft_msn: int = 0, operation_type: str = "CAT",
                        aircraft_type: str = "", etops_certified: bool = False):
    """Tâche d'audit V2 en arrière-plan avec contexte avion"""
    try:
        audit_jobs[job_id]["status"] = "running"
        audit_jobs[job_id]["progress"] = 10
        audit_jobs[job_id]["message"] = "Initializing pipeline V2..."

        # Configuration V2 avec contexte avion
        config = PipelineConfigV2(
            api_key=api_key,
            aircraft_msn=aircraft_msn,
            operation_type=operation_type,
            aircraft_type=aircraft_type,
            etops_certified=etops_certified,
            output_dir=str(OUTPUT_DIR)
        )

        pipeline = MoAMELPipelineV2(config)

        audit_jobs[job_id]["progress"] = 20
        audit_jobs[job_id]["message"] = f"Parsing documents (MSN: {aircraft_msn}, Op: {operation_type})..."

        # Exécuter le pipeline V2
        result = pipeline.run_full_pipeline(
            mel_source=mel_path,
            mmel_source=mmel_path,
            mel_is_json=mel_is_json,
            mmel_is_json=mmel_is_json
        )

        audit_jobs[job_id]["status"] = "completed"
        audit_jobs[job_id]["progress"] = 100
        audit_jobs[job_id]["message"] = "Audit V2 completed successfully"
        audit_jobs[job_id]["result"] = result
        audit_jobs[job_id]["completed_at"] = datetime.now().isoformat()
        audit_jobs[job_id]["aircraft_context"] = {
            "msn": aircraft_msn,
            "operation": operation_type,
            "aircraft_type": aircraft_type,
            "etops": etops_certified
        }

    except Exception as e:
        logger.error(f"Audit V2 failed for job {job_id}: {e}")
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
    """Webhook pour parser un document depuis n8n (utilise UnifiedParser)"""
    from parsers import UnifiedParser

    if not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Utiliser le UnifiedParser consolidé
    parser = UnifiedParser.create(api_key=api_key)
    result = parser.parse_document(file_path, doc_type=doc_type.upper())

    # Sauvegarder le résultat
    output_path = OUTPUT_DIR / f"parsed_{doc_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    result.to_json(str(output_path))

    return {
        "output_path": str(output_path),
        "items_count": result.total_items,
        "backend": result.parser_backend,
        "statistics": result.statistics
    }


# ============== Interface Web ==============

# Servir les fichiers statiques
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Sert le dashboard React intégré"""
    dashboard_path = STATIC_DIR / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(dashboard_path, media_type="text/html")
    else:
        # Fallback si le fichier n'existe pas
        return HTMLResponse("""
        <!DOCTYPE html>
        <html><head><title>MoA_MEL Dashboard</title></head>
        <body style="font-family: sans-serif; padding: 40px; text-align: center;">
            <h1>Dashboard non disponible</h1>
            <p>Le fichier static/dashboard.html n'a pas été trouvé.</p>
            <p><a href="/docs">Accéder à l'API →</a></p>
        </body></html>
        """)


@app.get("/api/demo-data")
async def get_demo_data():
    """
    Génère des données de démonstration depuis les fichiers sample.
    Compare sample_mel.json avec sample_mmel.json pour produire un audit réaliste.
    """
    # Chemins des fichiers sample
    data_dir = Path(__file__).parent.parent / "data"
    mel_path = data_dir / "sample_mel.json"
    mmel_path = data_dir / "sample_mmel.json"

    # Charger les fichiers sample
    try:
        with open(mel_path, "r", encoding="utf-8") as f:
            mel_data = json.load(f)
        with open(mmel_path, "r", encoding="utf-8") as f:
            mmel_data = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Sample data files not found")

    mel_items = mel_data.get("items", [])
    mmel_items = mmel_data.get("items", [])

    # Indexer MMEL par item_number
    mmel_index = {item["item_number"]: item for item in mmel_items}

    # Générer les comparaisons
    comparisons = []
    stats = {
        "compliant": 0, "more_restrictive": 0, "less_restrictive": 0,
        "missing_in_mel": 0, "missing_in_mmel": 0
    }
    severity_breakdown = {"critical": 0, "high": 0, "medium": 0, "warning": 0, "info": 0}

    # Ordre des catégories (A=plus restrictif, D=moins restrictif)
    category_order = {"A": 0, "B": 1, "C": 2, "D": 3, "": 4, "-": 4}

    for mel_item in mel_items:
        item_num = mel_item["item_number"]
        mmel_item = mmel_index.get(item_num)

        if not mmel_item:
            comparisons.append({
                "mel_item_id": f"{mel_item['ata_chapter']}|{item_num}",
                "mmel_item_id": "",
                "ata_chapter": mel_item["ata_chapter"],
                "item_number": item_num,
                "item_description": mel_item["item_description"],
                "verdict": "MISSING_IN_MMEL",
                "severity": "info",
                "mel_category": mel_item.get("category", ""),
                "mmel_category": "",
                "mel_remarks": mel_item.get("remarks", ""),
                "mmel_remarks": ""
            })
            stats["missing_in_mmel"] += 1
            severity_breakdown["info"] += 1
            continue

        mel_cat = mel_item.get("category", "")
        mmel_cat = mmel_item.get("category", "")
        mel_order = category_order.get(mel_cat, 4)
        mmel_order = category_order.get(mmel_cat, 4)

        if mel_cat == mmel_cat:
            verdict, severity = "COMPLIANT", "info"
            stats["compliant"] += 1
            severity_breakdown["info"] += 1
        elif mel_order < mmel_order:
            verdict, severity = "MORE_RESTRICTIVE", "info"
            stats["more_restrictive"] += 1
            severity_breakdown["info"] += 1
        else:
            verdict, severity = "LESS_RESTRICTIVE", "critical"
            stats["less_restrictive"] += 1
            severity_breakdown["critical"] += 1

        comparisons.append({
            "mel_item_id": f"{mel_item['ata_chapter']}|{item_num}",
            "mmel_item_id": f"{mmel_item['ata_chapter']}|{item_num}",
            "ata_chapter": mel_item["ata_chapter"],
            "item_number": item_num,
            "item_description": mel_item["item_description"],
            "verdict": verdict,
            "severity": severity,
            "mel_category": mel_cat,
            "mmel_category": mmel_cat,
            "mel_remarks": mel_item.get("remarks", ""),
            "mmel_remarks": mmel_item.get("remarks", ""),
            "hitl_reason": f"MEL category {mel_cat} vs MMEL {mmel_cat}" if verdict == "LESS_RESTRICTIVE" else None
        })
        del mmel_index[item_num]

    # Items MMEL non trouvés dans MEL
    for item_num, mmel_item in mmel_index.items():
        comparisons.append({
            "mel_item_id": "",
            "mmel_item_id": f"{mmel_item['ata_chapter']}|{item_num}",
            "ata_chapter": mmel_item["ata_chapter"],
            "item_number": item_num,
            "item_description": mmel_item["item_description"],
            "verdict": "MISSING_IN_MEL",
            "severity": "warning",
            "mel_category": "",
            "mmel_category": mmel_item.get("category", ""),
            "mel_remarks": "",
            "mmel_remarks": mmel_item.get("remarks", ""),
            "hitl_reason": "MMEL item not found in MEL"
        })
        stats["missing_in_mel"] += 1
        severity_breakdown["warning"] += 1

    # Trier par sévérité
    severity_order = {"critical": 0, "high": 1, "medium": 2, "warning": 3, "info": 4}
    comparisons.sort(key=lambda x: severity_order.get(x["severity"], 5))

    total = len(comparisons)
    compliant_count = stats["compliant"] + stats["more_restrictive"]
    compliance_rate = round((compliant_count / total * 100) if total > 0 else 0, 2)

    return {
        "run_id": f"demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "mel_document": mel_data.get("document_name", "sample_mel.json"),
        "mmel_document": mmel_data.get("document_name", "sample_mmel.json"),
        "audit_timestamp": datetime.now().isoformat(),
        "aircraft_context": {
            "aircraft_type": mel_data.get("aircraft_type", ""),
            "operator": mel_data.get("operator", "Sample Airlines")
        },
        "summary": {
            "total": total,
            "compliant": stats["compliant"],
            "more_restrictive": stats["more_restrictive"],
            "less_restrictive": stats["less_restrictive"],
            "missing_in_mel": stats["missing_in_mel"],
            "missing_in_mmel": stats["missing_in_mmel"],
            "hitl_required": stats["less_restrictive"] + stats["missing_in_mel"],
            "compliance_rate": compliance_rate
        },
        "severity_breakdown": severity_breakdown,
        "comparisons": comparisons
    }


# ============== Démarrage ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
