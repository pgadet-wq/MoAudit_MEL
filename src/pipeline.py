"""
MoA_MEL Pipeline Orchestrator
==============================
Orchestration complète du workflow d'audit MEL/MMEL.
Peut être exécuté en standalone ou appelé depuis n8n.
"""

import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
import sys

# Import des modules
from .mel_parser import MELParser, create_mock_parsing_result
from .mel_indexer import MELIndexer, IndexingResult
from .mel_comparator import MELComparator, AuditResult

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MoA_MEL_Pipeline")


class MoAMELPipeline:
    """Pipeline complet d'audit MEL/MMEL"""
    
    def __init__(self, api_key: str = "", output_dir: str = "outputs"):
        self.api_key = api_key
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialiser les composants
        self.parser = MELParser(api_key) if api_key else None
        self.indexer = MELIndexer(api_key)
        self.comparator = MELComparator(api_key)
        
        # État du pipeline
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.state = {
            "status": "initialized",
            "mel_parsed": False,
            "mmel_parsed": False,
            "indexed": False,
            "compared": False,
            "mel_items": [],
            "mmel_items": [],
            "matches": [],
            "audit_result": None
        }
    
    def _save_state(self):
        """Sauvegarde l'état du pipeline"""
        state_path = self.output_dir / f"pipeline_state_{self.run_id}.json"
        # Convertir les objets en dict pour la sérialisation
        state_copy = {**self.state}
        if state_copy.get("audit_result"):
            state_copy["audit_result"] = state_copy["audit_result"].get_summary()
        with open(state_path, "w") as f:
            json.dump(state_copy, f, indent=2, default=str)
    
    def parse_document(self, pdf_path: str, doc_type: str) -> List[Dict[str, Any]]:
        """Parse un document MEL ou MMEL"""
        logger.info(f"Parsing {doc_type}: {pdf_path}")
        
        if self.parser:
            result = self.parser.parse_pdf(pdf_path)
            items = [item.to_dict() for item in result.items]
            
            # Ajouter le type de document
            for item in items:
                item["document_type"] = doc_type
            
            # Sauvegarder le résultat du parsing
            output_path = self.output_dir / f"parsed_{doc_type.lower()}_{self.run_id}.json"
            self.parser.save_parsing_result(result, str(output_path))
            
            # Générer le log HITL si nécessaire
            if result.hitl_required_items > 0:
                hitl_path = self.output_dir / f"hitl_parsing_{doc_type.lower()}_{self.run_id}.json"
                self.parser.generate_hitl_log(result, str(hitl_path))
            
            logger.info(f"Parsed {len(items)} items from {doc_type}")
            return items
        else:
            logger.warning("No parser available, using mock data")
            result = create_mock_parsing_result(pdf_path, doc_type)
            return [item.to_dict() for item in result.items]
    
    def load_parsed_data(self, json_path: str, doc_type: str) -> List[Dict[str, Any]]:
        """Charge des données déjà parsées depuis un fichier JSON"""
        logger.info(f"Loading parsed {doc_type} from: {json_path}")
        
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        items = data.get("items", data) if isinstance(data, dict) else data
        
        # Ajouter le type de document si absent
        for item in items:
            if "document_type" not in item:
                item["document_type"] = doc_type
        
        logger.info(f"Loaded {len(items)} items from {doc_type}")
        return items
    
    def run_indexing(self, mel_items: List[Dict], mmel_items: List[Dict]) -> IndexingResult:
        """Exécute l'indexation et le matching"""
        logger.info("Running MEL/MMEL indexing and matching...")
        
        result = self.indexer.index_documents(mel_items, mmel_items)
        
        # Sauvegarder les résultats
        output_path = self.output_dir / f"indexing_result_{self.run_id}.json"
        self.indexer.save_indexing_result(result, str(output_path))
        
        # Générer le log HITL
        hitl_items = [m for m in result.matches if m.requires_hitl_review]
        if hitl_items:
            hitl_path = self.output_dir / f"hitl_matching_{self.run_id}.json"
            self.indexer.generate_hitl_log(result, str(hitl_path))
        
        return result
    
    def run_comparison(self, mel_items: List[Dict], mmel_items: List[Dict],
                      matches: List[Dict]) -> AuditResult:
        """Exécute la comparaison et génère le rapport d'audit"""
        logger.info("Running MEL/MMEL comparison audit...")
        
        result = self.comparator.run_audit(mel_items, mmel_items, matches)
        
        # Sauvegarder les résultats
        output_path = self.output_dir / f"audit_result_{self.run_id}.json"
        self.comparator.save_audit_result(result, str(output_path))
        
        # Générer le log HITL
        if result.hitl_required_count > 0:
            hitl_path = self.output_dir / f"hitl_audit_{self.run_id}.json"
            self.comparator.generate_hitl_log(result, str(hitl_path))
        
        return result
    
    def run_full_pipeline(self, mel_source: str, mmel_source: str,
                         mel_is_json: bool = False, mmel_is_json: bool = False) -> Dict[str, Any]:
        """Exécute le pipeline complet"""
        logger.info(f"Starting full MoA_MEL pipeline - Run ID: {self.run_id}")
        self.state["status"] = "running"
        
        try:
            # 1. Parsing MEL
            if mel_is_json:
                mel_items = self.load_parsed_data(mel_source, "MEL")
            else:
                mel_items = self.parse_document(mel_source, "MEL")
            self.state["mel_items"] = mel_items
            self.state["mel_parsed"] = True
            self._save_state()
            
            # 2. Parsing MMEL
            if mmel_is_json:
                mmel_items = self.load_parsed_data(mmel_source, "MMEL")
            else:
                mmel_items = self.parse_document(mmel_source, "MMEL")
            self.state["mmel_items"] = mmel_items
            self.state["mmel_parsed"] = True
            self._save_state()
            
            # 3. Indexation et Matching
            indexing_result = self.run_indexing(mel_items, mmel_items)
            self.state["matches"] = [m.to_dict() for m in indexing_result.matches]
            self.state["indexed"] = True
            self._save_state()
            
            # 4. Comparaison et Audit
            audit_result = self.run_comparison(
                mel_items, 
                mmel_items,
                self.state["matches"]
            )
            self.state["audit_result"] = audit_result
            self.state["compared"] = True
            self.state["status"] = "completed"
            self._save_state()
            
            # 5. Générer le rapport final
            final_report = self._generate_final_report(audit_result)
            
            logger.info(f"Pipeline completed successfully")
            return final_report
            
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            self.state["status"] = "failed"
            self.state["error"] = str(e)
            self._save_state()
            raise
    
    def _generate_final_report(self, audit_result: AuditResult) -> Dict[str, Any]:
        """Génère le rapport final consolidé"""
        report = {
            "run_id": self.run_id,
            "generated_at": datetime.now().isoformat(),
            "status": "completed",
            "summary": audit_result.get_summary(),
            "critical_findings": [],
            "recommendations": [],
            "output_files": {
                "audit_result": str(self.output_dir / f"audit_result_{self.run_id}.json"),
                "hitl_logs": str(self.output_dir / f"hitl_audit_{self.run_id}.json")
            }
        }
        
        # Extraire les findings critiques
        for comp in audit_result.comparisons:
            if comp.severity == "critical":
                report["critical_findings"].append({
                    "item": f"{comp.ata_chapter}-{comp.item_number}",
                    "description": comp.item_description,
                    "verdict": comp.verdict,
                    "details": comp.hitl_reason,
                    "mel_category": comp.mel_category,
                    "mmel_category": comp.mmel_category
                })
        
        # Générer des recommandations
        if audit_result.less_restrictive_count > 0:
            report["recommendations"].append({
                "priority": "HIGH",
                "action": f"Review {audit_result.less_restrictive_count} items where MEL is less restrictive than MMEL",
                "deadline": "48 hours"
            })
        
        if audit_result.missing_in_mel_count > 0:
            report["recommendations"].append({
                "priority": "MEDIUM",
                "action": f"Verify {audit_result.missing_in_mel_count} MMEL items not found in MEL",
                "deadline": "1 week"
            })
        
        # Sauvegarder le rapport
        report_path = self.output_dir / f"final_report_{self.run_id}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        report["output_files"]["final_report"] = str(report_path)
        
        return report


def main():
    """Point d'entrée CLI"""
    parser = argparse.ArgumentParser(description="MoA_MEL Audit Pipeline")
    
    parser.add_argument("--mel", required=True, help="Path to MEL document (PDF or JSON)")
    parser.add_argument("--mmel", required=True, help="Path to MMEL document (PDF or JSON)")
    parser.add_argument("--api-key", default="", help="Mistral API key")
    parser.add_argument("--output-dir", default="outputs", help="Output directory")
    parser.add_argument("--mel-json", action="store_true", help="MEL source is JSON")
    parser.add_argument("--mmel-json", action="store_true", help="MMEL source is JSON")
    
    args = parser.parse_args()
    
    # Vérifier les fichiers
    if not Path(args.mel).exists():
        logger.error(f"MEL file not found: {args.mel}")
        sys.exit(1)
    if not Path(args.mmel).exists():
        logger.error(f"MMEL file not found: {args.mmel}")
        sys.exit(1)
    
    # Exécuter le pipeline
    pipeline = MoAMELPipeline(
        api_key=args.api_key,
        output_dir=args.output_dir
    )
    
    result = pipeline.run_full_pipeline(
        mel_source=args.mel,
        mmel_source=args.mmel,
        mel_is_json=args.mel_json,
        mmel_is_json=args.mmel_json
    )
    
    print("\n" + "="*60)
    print("AUDIT COMPLETE")
    print("="*60)
    print(json.dumps(result["summary"], indent=2))
    print(f"\nOutput files: {result['output_files']}")


# API pour n8n (webhook endpoint)
def run_pipeline_api(mel_path: str, mmel_path: str, api_key: str = "",
                    mel_is_json: bool = False, mmel_is_json: bool = False) -> Dict[str, Any]:
    """Interface API pour n8n"""
    pipeline = MoAMELPipeline(api_key=api_key)
    return pipeline.run_full_pipeline(mel_path, mmel_path, mel_is_json, mmel_is_json)


if __name__ == "__main__":
    main()
