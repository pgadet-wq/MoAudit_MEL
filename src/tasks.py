"""
MoAudit MEL - Celery Task Definitions
=====================================
Asynchronous task processing for PDF parsing and audit workflows.
"""

import os
import json
import tempfile
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from celery import Celery, states
from celery.exceptions import SoftTimeLimitExceeded

from .config import config, load_config_from_env

# Load configuration
load_config_from_env()

# Celery app configuration
celery_app = Celery(
    "moaudit",
    broker=config.redis.url,
    backend=config.redis.url,
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,  # 10 minutes hard limit
    task_soft_time_limit=540,  # 9 minutes soft limit
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    result_expires=86400,  # 24 hours

    # Task routes
    task_routes={
        "moaudit.parse_document": {"queue": "parsing"},
        "moaudit.run_audit": {"queue": "audit"},
        "moaudit.generate_report": {"queue": "reports"},
    },

    # Rate limiting
    task_annotations={
        "moaudit.parse_document": {"rate_limit": "10/m"},
        "moaudit.run_audit": {"rate_limit": "5/m"},
    }
)


def get_parser():
    """Lazy load parser to avoid circular imports"""
    from .mel_parser_docling import get_parser
    return get_parser()


def get_storage():
    """Lazy load storage to avoid circular imports"""
    from .storage import get_storage_backend
    return get_storage_backend()


@celery_app.task(
    bind=True,
    name="moaudit.parse_document",
    max_retries=3,
    default_retry_delay=30,
)
def parse_document(
    self,
    file_path: str,
    document_type: str,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Parse a PDF document (MEL or MMEL) asynchronously.

    Args:
        file_path: Path to the PDF file (local or S3 key)
        document_type: "MEL" or "MMEL"
        options: Additional parsing options
            - aircraft_type: Aircraft type (e.g., "A320")
            - operator: Operator name
            - use_vlm: Whether to use VLM enhancement

    Returns:
        Dict with parsing results including items and metadata
    """
    options = options or {}
    storage = get_storage()
    parser = get_parser()

    try:
        # Update task state
        self.update_state(
            state="PARSING",
            meta={
                "step": "downloading",
                "document_type": document_type,
                "progress": 10
            }
        )

        # Download file from storage if needed
        if file_path.startswith("s3://") or config.storage.backend != "local":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                storage.download(file_path, tmp.name)
                local_path = tmp.name
        else:
            local_path = file_path

        # Update state
        self.update_state(
            state="PARSING",
            meta={
                "step": "extracting",
                "document_type": document_type,
                "progress": 30
            }
        )

        # Parse the document
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                parser.parse(local_path, document_type)
            )
        finally:
            loop.close()

        # Update state
        self.update_state(
            state="PARSING",
            meta={
                "step": "processing",
                "document_type": document_type,
                "progress": 70
            }
        )

        # Process result
        items_data = []
        for item in result.items:
            items_data.append({
                "ata_chapter": item.get("ata_chapter", ""),
                "item_number": item.get("item_number", ""),
                "description": item.get("description", ""),
                "category": item.get("category", ""),
                "repair_interval": item.get("repair_interval", ""),
                "number_installed": item.get("number_installed", ""),
                "number_required": item.get("number_required", ""),
                "remarks": item.get("remarks", ""),
                "exceptions": item.get("exceptions", ""),
                "confidence": item.get("confidence", 0.0),
            })

        # Clean up temp file if created
        if local_path != file_path and os.path.exists(local_path):
            os.unlink(local_path)

        return {
            "status": "success",
            "document_type": document_type,
            "items_count": len(items_data),
            "items": items_data,
            "hitl_required": result.hitl_items,
            "metadata": {
                "source": file_path,
                "parsed_at": datetime.utcnow().isoformat(),
                "backend": result.backend_used,
                "aircraft_type": options.get("aircraft_type"),
                "operator": options.get("operator"),
            }
        }

    except SoftTimeLimitExceeded:
        return {
            "status": "error",
            "error": "Task exceeded time limit",
            "document_type": document_type
        }

    except Exception as exc:
        # Retry on transient errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        return {
            "status": "error",
            "error": str(exc),
            "document_type": document_type
        }


@celery_app.task(
    bind=True,
    name="moaudit.run_audit",
    max_retries=2,
    default_retry_delay=60,
)
def run_audit(
    self,
    mel_task_id: str,
    mmel_task_id: str,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Run MEL/MMEL comparison audit after both documents are parsed.

    Args:
        mel_task_id: Celery task ID of MEL parsing task
        mmel_task_id: Celery task ID of MMEL parsing task
        options: Additional audit options
            - aircraft_type: Aircraft type
            - msn: Manufacturer Serial Number
            - operator: Operator name

    Returns:
        Dict with audit results including verdicts and deviations
    """
    from .mel_comparator_v2 import MELComparatorV2

    options = options or {}

    try:
        # Wait for parsing tasks to complete
        self.update_state(
            state="WAITING",
            meta={"step": "waiting_for_parsing", "progress": 10}
        )

        # Get results from parsing tasks
        mel_result = celery_app.AsyncResult(mel_task_id)
        mmel_result = celery_app.AsyncResult(mmel_task_id)

        # Wait with timeout
        mel_data = mel_result.get(timeout=300)
        mmel_data = mmel_result.get(timeout=300)

        if mel_data.get("status") != "success":
            return {
                "status": "error",
                "error": f"MEL parsing failed: {mel_data.get('error')}",
            }

        if mmel_data.get("status") != "success":
            return {
                "status": "error",
                "error": f"MMEL parsing failed: {mmel_data.get('error')}",
            }

        # Update state
        self.update_state(
            state="COMPARING",
            meta={"step": "running_comparison", "progress": 50}
        )

        # Run comparison
        comparator = MELComparatorV2()

        comparison_result = comparator.compare(
            mel_items=mel_data["items"],
            mmel_items=mmel_data["items"]
        )

        # Update state
        self.update_state(
            state="ANALYZING",
            meta={"step": "analyzing_deviations", "progress": 80}
        )

        # Categorize results
        verdicts = {
            "COMPLIANT": 0,
            "MORE_RESTRICTIVE": 0,
            "LESS_RESTRICTIVE": 0,
            "MISSING_IN_MEL": 0,
            "MISSING_IN_MMEL": 0,
            "CATEGORY_MISMATCH": 0,
            "REMARKS_DEVIATION": 0,
        }

        deviations = []
        hitl_items = []

        for item in comparison_result.get("comparisons", []):
            verdict = item.get("verdict", "COMPLIANT")
            verdicts[verdict] = verdicts.get(verdict, 0) + 1

            if verdict not in ["COMPLIANT", "MORE_RESTRICTIVE"]:
                deviations.append(item)

            if item.get("requires_review", False):
                hitl_items.append(item)

        # Determine overall status
        critical_count = verdicts["LESS_RESTRICTIVE"]
        warning_count = verdicts["MISSING_IN_MEL"] + verdicts["CATEGORY_MISMATCH"]

        if critical_count > 0:
            overall_status = "CRITICAL"
        elif warning_count > 0:
            overall_status = "WARNING"
        else:
            overall_status = "PASS"

        return {
            "status": "success",
            "audit_status": overall_status,
            "summary": {
                "total_mel_items": mel_data["items_count"],
                "total_mmel_items": mmel_data["items_count"],
                "verdicts": verdicts,
                "critical_deviations": critical_count,
                "requires_review": len(hitl_items),
            },
            "deviations": deviations,
            "hitl_items": hitl_items,
            "metadata": {
                "mel_source": mel_data["metadata"]["source"],
                "mmel_source": mmel_data["metadata"]["source"],
                "aircraft_type": options.get("aircraft_type"),
                "msn": options.get("msn"),
                "operator": options.get("operator"),
                "audited_at": datetime.utcnow().isoformat(),
            }
        }

    except SoftTimeLimitExceeded:
        return {
            "status": "error",
            "error": "Audit task exceeded time limit"
        }

    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        return {
            "status": "error",
            "error": str(exc)
        }


@celery_app.task(
    bind=True,
    name="moaudit.generate_report",
)
def generate_report(
    self,
    audit_task_id: str,
    report_format: str = "json",
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generate audit report in specified format.

    Args:
        audit_task_id: Celery task ID of audit task
        report_format: Output format (json, html, pdf)
        options: Additional report options

    Returns:
        Dict with report file path and metadata
    """
    options = options or {}
    storage = get_storage()

    try:
        # Get audit results
        self.update_state(
            state="GENERATING",
            meta={"step": "fetching_results", "progress": 10}
        )

        audit_result = celery_app.AsyncResult(audit_task_id)
        audit_data = audit_result.get(timeout=60)

        if audit_data.get("status") != "success":
            return {
                "status": "error",
                "error": f"Audit failed: {audit_data.get('error')}"
            }

        # Generate report
        self.update_state(
            state="GENERATING",
            meta={"step": "creating_report", "progress": 50}
        )

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_filename = f"audit_report_{timestamp}.{report_format}"

        if report_format == "json":
            report_content = json.dumps(audit_data, indent=2, ensure_ascii=False)

        elif report_format == "html":
            report_content = _generate_html_report(audit_data)

        else:
            return {
                "status": "error",
                "error": f"Unsupported report format: {report_format}"
            }

        # Save report
        self.update_state(
            state="GENERATING",
            meta={"step": "saving_report", "progress": 80}
        )

        report_path = f"reports/{report_filename}"

        if config.storage.backend == "local":
            full_path = Path(config.output.output_directory) / report_filename
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(report_content)
            final_path = str(full_path)
        else:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=f".{report_format}") as tmp:
                tmp.write(report_content)
                tmp_path = tmp.name
            storage.upload(tmp_path, report_path)
            os.unlink(tmp_path)
            final_path = report_path

        return {
            "status": "success",
            "report_path": final_path,
            "format": report_format,
            "metadata": {
                "generated_at": datetime.utcnow().isoformat(),
                "audit_status": audit_data.get("audit_status"),
            }
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc)
        }


def _generate_html_report(audit_data: Dict[str, Any]) -> str:
    """Generate HTML report from audit data"""

    status = audit_data.get("audit_status", "UNKNOWN")
    summary = audit_data.get("summary", {})
    metadata = audit_data.get("metadata", {})
    deviations = audit_data.get("deviations", [])

    status_colors = {
        "PASS": "#28a745",
        "WARNING": "#ffc107",
        "CRITICAL": "#dc3545",
    }

    deviations_html = ""
    for dev in deviations[:50]:  # Limit to 50 for performance
        deviations_html += f"""
        <tr>
            <td>{dev.get('ata_chapter', '-')}</td>
            <td>{dev.get('item_number', '-')}</td>
            <td>{dev.get('description', '-')[:100]}</td>
            <td><span class="badge verdict-{dev.get('verdict', '').lower()}">{dev.get('verdict', '-')}</span></td>
            <td>{dev.get('details', '-')}</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MEL/MMEL Audit Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
        .status {{ font-size: 24px; font-weight: bold; padding: 10px 20px; border-radius: 4px; display: inline-block; color: white; background: {status_colors.get(status, '#6c757d')}; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }}
        .summary-card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; }}
        .summary-card h3 {{ margin: 0 0 10px 0; color: #666; font-size: 14px; text-transform: uppercase; }}
        .summary-card .value {{ font-size: 32px; font-weight: bold; color: #333; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }}
        .verdict-less_restrictive {{ background: #dc3545; color: white; }}
        .verdict-missing_in_mel {{ background: #ffc107; color: black; }}
        .verdict-category_mismatch {{ background: #fd7e14; color: white; }}
        .verdict-remarks_deviation {{ background: #17a2b8; color: white; }}
        .metadata {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>MEL/MMEL Audit Report</h1>

        <p><span class="status">{status}</span></p>

        <div class="summary">
            <div class="summary-card">
                <h3>MEL Items</h3>
                <div class="value">{summary.get('total_mel_items', 0)}</div>
            </div>
            <div class="summary-card">
                <h3>MMEL Items</h3>
                <div class="value">{summary.get('total_mmel_items', 0)}</div>
            </div>
            <div class="summary-card">
                <h3>Critical Deviations</h3>
                <div class="value" style="color: #dc3545;">{summary.get('critical_deviations', 0)}</div>
            </div>
            <div class="summary-card">
                <h3>Requires Review</h3>
                <div class="value" style="color: #ffc107;">{summary.get('requires_review', 0)}</div>
            </div>
        </div>

        <h2>Deviations</h2>
        <table>
            <thead>
                <tr>
                    <th>ATA Chapter</th>
                    <th>Item</th>
                    <th>Description</th>
                    <th>Verdict</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
                {deviations_html if deviations_html else '<tr><td colspan="5" style="text-align: center; color: #666;">No deviations found</td></tr>'}
            </tbody>
        </table>

        <div class="metadata">
            <p><strong>Aircraft:</strong> {metadata.get('aircraft_type', 'N/A')} | <strong>MSN:</strong> {metadata.get('msn', 'N/A')} | <strong>Operator:</strong> {metadata.get('operator', 'N/A')}</p>
            <p><strong>MEL Source:</strong> {metadata.get('mel_source', 'N/A')}</p>
            <p><strong>MMEL Source:</strong> {metadata.get('mmel_source', 'N/A')}</p>
            <p><strong>Audited:</strong> {metadata.get('audited_at', 'N/A')}</p>
        </div>
    </div>
</body>
</html>"""

    return html


# Workflow orchestration
@celery_app.task(bind=True, name="moaudit.full_audit_workflow")
def full_audit_workflow(
    self,
    mel_file_path: str,
    mmel_file_path: str,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Complete audit workflow: parse both documents, compare, and generate report.

    Args:
        mel_file_path: Path to MEL PDF
        mmel_file_path: Path to MMEL PDF
        options: Workflow options

    Returns:
        Dict with final results and report path
    """
    from celery import chain, group

    options = options or {}

    # Create workflow chain
    workflow = chain(
        # Parse both documents in parallel
        group(
            parse_document.s(mel_file_path, "MEL", options),
            parse_document.s(mmel_file_path, "MMEL", options),
        ),
        # Run audit (receives list of [mel_result, mmel_result])
        _audit_from_results.s(options),
        # Generate report
        _report_from_audit.s(options.get("report_format", "json"), options),
    )

    # Execute workflow
    result = workflow.apply_async()

    return {
        "workflow_id": result.id,
        "status": "started",
    }


@celery_app.task(name="moaudit._audit_from_results")
def _audit_from_results(parsing_results: list, options: Dict[str, Any]) -> Dict[str, Any]:
    """Internal task to run audit from parsing results"""
    from .mel_comparator_v2 import MELComparatorV2

    mel_data, mmel_data = parsing_results

    if mel_data.get("status") != "success":
        return {"status": "error", "error": f"MEL parsing failed: {mel_data.get('error')}"}

    if mmel_data.get("status") != "success":
        return {"status": "error", "error": f"MMEL parsing failed: {mmel_data.get('error')}"}

    comparator = MELComparatorV2()
    comparison_result = comparator.compare(
        mel_items=mel_data["items"],
        mmel_items=mmel_data["items"]
    )

    # Same processing as run_audit
    verdicts = {v: 0 for v in ["COMPLIANT", "MORE_RESTRICTIVE", "LESS_RESTRICTIVE",
                                "MISSING_IN_MEL", "MISSING_IN_MMEL", "CATEGORY_MISMATCH", "REMARKS_DEVIATION"]}

    deviations = []
    hitl_items = []

    for item in comparison_result.get("comparisons", []):
        verdict = item.get("verdict", "COMPLIANT")
        verdicts[verdict] = verdicts.get(verdict, 0) + 1

        if verdict not in ["COMPLIANT", "MORE_RESTRICTIVE"]:
            deviations.append(item)

        if item.get("requires_review", False):
            hitl_items.append(item)

    critical_count = verdicts["LESS_RESTRICTIVE"]
    warning_count = verdicts["MISSING_IN_MEL"] + verdicts["CATEGORY_MISMATCH"]

    overall_status = "CRITICAL" if critical_count > 0 else ("WARNING" if warning_count > 0 else "PASS")

    return {
        "status": "success",
        "audit_status": overall_status,
        "summary": {
            "total_mel_items": mel_data["items_count"],
            "total_mmel_items": mmel_data["items_count"],
            "verdicts": verdicts,
            "critical_deviations": critical_count,
            "requires_review": len(hitl_items),
        },
        "deviations": deviations,
        "hitl_items": hitl_items,
        "metadata": {
            "mel_source": mel_data["metadata"]["source"],
            "mmel_source": mmel_data["metadata"]["source"],
            "aircraft_type": options.get("aircraft_type"),
            "msn": options.get("msn"),
            "operator": options.get("operator"),
            "audited_at": datetime.utcnow().isoformat(),
        }
    }


@celery_app.task(name="moaudit._report_from_audit")
def _report_from_audit(audit_data: Dict[str, Any], report_format: str, options: Dict[str, Any]) -> Dict[str, Any]:
    """Internal task to generate report from audit results"""

    if audit_data.get("status") != "success":
        return audit_data

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_filename = f"audit_report_{timestamp}.{report_format}"

    if report_format == "json":
        report_content = json.dumps(audit_data, indent=2, ensure_ascii=False)
    elif report_format == "html":
        report_content = _generate_html_report(audit_data)
    else:
        report_content = json.dumps(audit_data, indent=2)

    # Save locally
    output_dir = Path(config.output.output_directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / report_filename
    report_path.write_text(report_content)

    return {
        "status": "success",
        "report_path": str(report_path),
        "format": report_format,
        "audit_status": audit_data.get("audit_status"),
        "summary": audit_data.get("summary"),
    }
