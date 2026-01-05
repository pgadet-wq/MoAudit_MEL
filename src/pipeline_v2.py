#!/usr/bin/env python3
"""
MoA_MEL Pipeline V2 - Optimized Architecture
=============================================
Pipeline d'audit MEL/MMEL avec:
- Parsing multi-pages (continuité)
- Extraction sémantique LLM
- Validation avec self-healing
- Matching contextuel (MSN/Operation)
- Comparaison Tree-Search

Usage:
    python pipeline_v2.py --mel MEL.pdf --mmel MMEL.pdf --msn 1280 --operation CAT
"""

import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
import logging
import sys
import os

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MoA_MEL_Pipeline_V2")

# Imports des nouveaux modules
MODULES_V2_AVAILABLE = False
MMELVariantTree = None
AircraftContext = None
TreeSearchComparator = None
AuditResultV2 = None
PageContinuityResolver = None
TableRowMerger = None
SemanticMELParser = None
HybridParser = None
IntegrityChecker = None
SelfHealingExtractor = None

try:
    from models.mel_item_v3 import (
        MELItemV3, MSNRange, ParsingResultV3,
        extract_conditions_from_remarks, extract_operation_types, extract_msn_ranges
    )
    from parsers.page_continuity_resolver import PageContinuityResolver, TableRowMerger
    from parsers.semantic_parser import SemanticMELParser, HybridParser
    from validation.integrity_checker import IntegrityChecker, SelfHealingExtractor
    from matching.mmel_variant_tree import MMELVariantTree, AircraftContext
    from comparison.tree_search_comparator import TreeSearchComparator, AuditResultV2
    MODULES_V2_AVAILABLE = True
    logger.info("Modules V2 chargés avec succès")
except ImportError as e:
    logger.warning(f"Modules V2 non disponibles: {e}")
    # Définir des classes factices pour les type hints
    class AircraftContext:
        def __init__(self, msn=0, operation_type="CAT", aircraft_type="", etops_certified=False):
            self.msn = msn
            self.operation_type = operation_type
            self.aircraft_type = aircraft_type
            self.etops_certified = etops_certified
        def describe(self):
            return f"MSN {self.msn}, {self.operation_type}"

# Imports legacy (fallback)
try:
    from mel_parser_docling import parse_document as parse_document_docling
    from mel_indexer import MELIndexer
    from mel_comparator import MELComparator
    LEGACY_AVAILABLE = True
except ImportError:
    LEGACY_AVAILABLE = False


@dataclass
class PipelineConfigV2:
    """Configuration du pipeline V2"""
    # API Mistral
    api_key: str = ""
    llm_model: str = "mistral-large-latest"

    # Contexte avion
    aircraft_msn: int = 0
    operation_type: str = "CAT"  # CAT, SPO, NCO, NCC
    aircraft_type: str = ""
    etops_certified: bool = False

    # Parsing
    use_llm_parser: bool = True
    enable_self_healing: bool = True
    confidence_threshold: float = 0.85

    # Matching
    enable_variant_matching: bool = True
    semantic_threshold: float = 0.85

    # Output
    output_dir: str = "outputs"
    generate_hitl_log: bool = True

    def to_dict(self) -> Dict:
        return asdict(self)


class MoAMELPipelineV2:
    """
    Pipeline V2 avec architecture optimisée.

    Améliorations vs V1:
    - Fusion multi-pages automatique
    - Extraction LLM structurée
    - Validation et self-healing
    - Matching par contexte (MSN, Operation)
    - Comparaison Tree-Search
    """

    def __init__(self, config: PipelineConfigV2):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Initialiser les composants V2
        if MODULES_V2_AVAILABLE:
            self._init_v2_components()
        else:
            self._init_legacy_components()

        # État du pipeline
        self.state = {
            "status": "initialized",
            "version": "v2" if MODULES_V2_AVAILABLE else "v1_legacy",
            "config": config.to_dict(),
            "steps": []
        }

    def _init_v2_components(self):
        """Initialise les composants V2"""
        logger.info("Initialisation des composants V2...")

        # Page continuity resolver
        self.continuity_resolver = PageContinuityResolver()
        self.table_merger = TableRowMerger()

        # Parsers
        if self.config.api_key and self.config.use_llm_parser:
            self.semantic_parser = SemanticMELParser(
                api_key=self.config.api_key,
                model=self.config.llm_model
            )
            self.hybrid_parser = HybridParser(api_key=self.config.api_key)
        else:
            self.semantic_parser = None
            self.hybrid_parser = HybridParser(api_key="")

        # Validation
        self.integrity_checker = IntegrityChecker(auto_fix=True)
        if self.config.enable_self_healing:
            self.self_healer = SelfHealingExtractor(self.integrity_checker)
        else:
            self.self_healer = None

        # Matching
        self.mmel_tree = MMELVariantTree()

        # Comparison
        self.comparator = TreeSearchComparator(self.mmel_tree)

        logger.info("Composants V2 initialisés")

    def _init_legacy_components(self):
        """Initialise les composants legacy (fallback)"""
        logger.warning("Utilisation des composants legacy")

        self.continuity_resolver = None
        self.semantic_parser = None
        self.hybrid_parser = None
        self.integrity_checker = None
        self.self_healer = None
        self.mmel_tree = None
        self.comparator = None

        if LEGACY_AVAILABLE:
            self.legacy_indexer = MELIndexer(self.config.api_key)
            self.legacy_comparator = MELComparator(self.config.api_key)

    def _log_step(self, step_name: str, status: str, details: Dict = None):
        """Enregistre une étape du pipeline"""
        step = {
            "name": step_name,
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "details": details or {}
        }
        self.state["steps"].append(step)
        logger.info(f"[{step_name}] {status}")

    # =========================================================================
    # ÉTAPE 1: Parsing avec Docling + Continuité Multi-Pages
    # =========================================================================

    def parse_document_v2(self, pdf_path: str, doc_type: str = "MEL") -> List[Dict[str, Any]]:
        """
        Parse un document avec le pipeline V2.

        Étapes:
        1. Extraction Docling → Markdown
        2. Fusion multi-pages
        3. Parsing sémantique LLM
        4. Validation et self-healing
        """
        logger.info(f"Parsing V2: {pdf_path} ({doc_type})")

        try:
            # Import Docling
            from docling.document_converter import DocumentConverter

            # 1. Conversion PDF → Document structuré
            self._log_step(f"parse_{doc_type.lower()}", "converting_pdf")
            converter = DocumentConverter()
            result = converter.convert(pdf_path)

            # 2. Export Markdown (préserve le flux de texte)
            self._log_step(f"parse_{doc_type.lower()}", "exporting_markdown")
            markdown_content = result.document.export_to_markdown()

            # 3. Fusion multi-pages si disponible
            if self.continuity_resolver:
                self._log_step(f"parse_{doc_type.lower()}", "resolving_continuity")
                # Diviser par pages (approximation via markers)
                pages = self._split_markdown_by_pages(markdown_content)
                merged_blocks = self.continuity_resolver.process_markdown_pages(pages)

                logger.info(f"Pages fusionnées: {len(pages)} → {len(merged_blocks)} blocs")
            else:
                merged_blocks = [{"content": markdown_content, "source_pages": [0]}]

            # 4. Extraction des items
            all_items = []

            for block in merged_blocks:
                block_content = block.content if hasattr(block, 'content') else block.get('content', '')
                source_pages = block.source_pages if hasattr(block, 'source_pages') else block.get('source_pages', [])

                if self.semantic_parser and self.config.use_llm_parser:
                    # Parsing LLM sémantique
                    self._log_step(f"parse_{doc_type.lower()}", "semantic_extraction")
                    extraction = self.semantic_parser.parse_block(
                        block_content,
                        source_page=source_pages[0] if source_pages else 0
                    )
                    if extraction.success:
                        all_items.extend(extraction.items)
                else:
                    # Parsing hybride (regex + enrichissement)
                    items = self._parse_block_hybrid(block_content, doc_type)
                    all_items.extend(items)

            # 5. Validation et self-healing
            if self.integrity_checker:
                self._log_step(f"parse_{doc_type.lower()}", "validating")
                validation_result = self.integrity_checker.validate_batch(all_items)

                logger.info(f"Validation: {validation_result['valid_items']}/{validation_result['total_items']} valides")

                if validation_result['items_needing_reextraction'] > 0:
                    logger.warning(f"{validation_result['items_needing_reextraction']} items nécessitent ré-extraction")

            # 6. Enrichissement des items
            for item in all_items:
                item['document_type'] = doc_type
                item['source_document'] = Path(pdf_path).name

                # Extraire MSN et operations si pas déjà fait
                if not item.get('applicable_msn'):
                    item['applicable_msn'] = extract_msn_ranges(
                        item.get('item_description', '') + ' ' + item.get('remarks_raw', '')
                    ) if 'extract_msn_ranges' in dir() else []

                if not item.get('operation_scope'):
                    item['operation_scope'] = extract_operation_types(
                        item.get('item_description', '') + ' ' + item.get('remarks_raw', '')
                    ) if 'extract_operation_types' in dir() else []

            # Sauvegarder le résultat
            self._save_parsing_result(all_items, doc_type)

            self._log_step(f"parse_{doc_type.lower()}", "completed", {
                "items_count": len(all_items)
            })

            return all_items

        except Exception as e:
            logger.error(f"Erreur parsing V2: {e}")
            self._log_step(f"parse_{doc_type.lower()}", "failed", {"error": str(e)})

            # Fallback vers parsing legacy
            if LEGACY_AVAILABLE:
                logger.info("Fallback vers parsing legacy...")
                return self._parse_document_legacy(pdf_path, doc_type)
            raise

    def _split_markdown_by_pages(self, markdown: str) -> List[str]:
        """Divise le Markdown par pages (heuristique)"""
        # Les documents Docling incluent souvent des markers de page
        import re

        # Patterns de séparation de page
        page_markers = [
            r'\n---\n',                    # Séparateur horizontal
            r'\n\*{3,}\n',                 # Trois étoiles ou plus
            r'\nPage \d+\n',               # "Page N"
            r'\n\[Page \d+\]',             # "[Page N]"
        ]

        # Essayer de diviser
        for pattern in page_markers:
            parts = re.split(pattern, markdown)
            if len(parts) > 1:
                return [p.strip() for p in parts if p.strip()]

        # Pas de marker trouvé, retourner tout comme une seule page
        return [markdown]

    def _parse_block_hybrid(self, content: str, doc_type: str) -> List[Dict]:
        """Parsing hybride regex + patterns"""
        items = []

        # Pattern ATA
        ata_pattern = r'(\d{2})-(\d{2})-(\d{2,3})([A-Z])?'

        # Rechercher les items dans le contenu
        import re
        for match in re.finditer(ata_pattern, content):
            chapter, section, item_num, suffix = match.groups()

            # Extraire le contexte autour
            start = max(0, match.start() - 50)
            end = min(len(content), match.end() + 500)
            context = content[start:end]

            # Parser basiquement
            item = {
                "ata_chapter": chapter,
                "ata_section": section,
                "item_base": f"{chapter}-{section}-{item_num.zfill(2)}",
                "variant_suffix": suffix or "",
                "item_number": f"{chapter}-{section}-{item_num.zfill(2)}{suffix or ''}",
                "item_description": self._extract_description(context),
                "category": self._extract_category(context),
                "number_installed": "-",
                "number_required": "-",
                "remarks_raw": self._extract_remarks(context),
                "extraction_method": "hybrid_regex"
            }

            items.append(item)

        return items

    def _extract_description(self, context: str) -> str:
        """Extrait la description depuis le contexte"""
        # Simpliste: prendre le texte après le numéro ATA
        import re
        match = re.search(r'\d{2}-\d{2}-\d{2,3}[A-Z]?\s+([^\n|]+)', context)
        return match.group(1).strip() if match else ""

    def _extract_category(self, context: str) -> str:
        """Extrait la catégorie depuis le contexte"""
        import re
        for cat in ['A', 'B', 'C', 'D']:
            if re.search(rf'\b{cat}\b', context[:100]):
                return cat
        return "C"  # Défaut

    def _extract_remarks(self, context: str) -> str:
        """Extrait les remarks depuis le contexte"""
        import re
        # Chercher les patterns (O), (M) et le texte qui suit
        match = re.search(r'\([OM]\)[^|]*', context, re.IGNORECASE)
        return match.group(0).strip() if match else ""

    def _parse_document_legacy(self, pdf_path: str, doc_type: str) -> List[Dict]:
        """Fallback vers parsing legacy"""
        if LEGACY_AVAILABLE:
            result = parse_document_docling(pdf_path, doc_type)
            return result.get("items", [])
        return []

    def _save_parsing_result(self, items: List[Dict], doc_type: str):
        """Sauvegarde le résultat de parsing"""
        output = {
            "document_type": doc_type,
            "parsing_timestamp": datetime.now().isoformat(),
            "parser_version": "v2",
            "statistics": {
                "total_items": len(items),
                "by_chapter": {}
            },
            "items": items
        }

        # Stats par chapitre
        for item in items:
            ch = item.get("ata_chapter", "00")
            output["statistics"]["by_chapter"][ch] = output["statistics"]["by_chapter"].get(ch, 0) + 1

        output_path = self.output_dir / f"parsed_{doc_type.lower()}_{self.run_id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"Parsing sauvegardé: {output_path}")

    # =========================================================================
    # ÉTAPE 2: Chargement de données pré-parsées
    # =========================================================================

    def load_parsed_data(self, json_path: str, doc_type: str) -> List[Dict[str, Any]]:
        """Charge des données déjà parsées"""
        logger.info(f"Chargement {doc_type}: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        items = data.get("items", data) if isinstance(data, dict) else data

        # Enrichir les items
        for item in items:
            item["document_type"] = doc_type

            # Convertir les MSN si nécessaire
            if "applicable_msn" in item and isinstance(item["applicable_msn"], list):
                item["applicable_msn"] = [
                    str(m) if not isinstance(m, str) else m
                    for m in item["applicable_msn"]
                ]

        self._log_step(f"load_{doc_type.lower()}", "completed", {
            "items_count": len(items)
        })

        return items

    # =========================================================================
    # ÉTAPE 3: Construction de l'arbre MMEL
    # =========================================================================

    def build_mmel_tree(self, mmel_items: List[Dict]):
        """Construit l'arbre de variantes MMEL"""
        if not MODULES_V2_AVAILABLE or not self.mmel_tree:
            logger.warning("MMELVariantTree non disponible")
            return None

        self._log_step("build_mmel_tree", "started")

        self.mmel_tree.build_from_items(mmel_items)

        stats = self.mmel_tree.get_statistics()
        self._log_step("build_mmel_tree", "completed", stats)

        return self.mmel_tree

    # =========================================================================
    # ÉTAPE 4: Comparaison Tree-Search
    # =========================================================================

    def run_comparison_v2(self, mel_items: List[Dict], mmel_items: List[Dict]):
        """Exécute la comparaison avec Tree-Search"""

        if not MODULES_V2_AVAILABLE:
            logger.warning("Comparaison V2 non disponible, utilisation legacy")
            return self._run_comparison_legacy(mel_items, mmel_items)

        self._log_step("comparison", "started")

        # Construire l'arbre MMEL si pas déjà fait
        if not self.mmel_tree.total_items:
            self.build_mmel_tree(mmel_items)

        # Créer le contexte avion
        aircraft_context = AircraftContext(
            msn=self.config.aircraft_msn,
            operation_type=self.config.operation_type,
            aircraft_type=self.config.aircraft_type,
            etops_certified=self.config.etops_certified
        )

        logger.info(f"Contexte avion: {aircraft_context.describe()}")

        # Exécuter l'audit
        result = self.comparator.run_audit(
            mel_items=mel_items,
            aircraft_context=aircraft_context,
            mel_document="MEL",
            mmel_document="MMEL"
        )

        # Sauvegarder les résultats
        self._save_audit_result(result)

        self._log_step("comparison", "completed", {
            "total_comparisons": result.total_comparisons,
            "compliant": result.compliant_count,
            "less_restrictive": result.less_restrictive_count,
            "compliance_rate": result.overall_compliance_rate
        })

        return result

    def _run_comparison_legacy(self, mel_items: List[Dict], mmel_items: List[Dict]):
        """Fallback vers comparaison legacy"""
        if LEGACY_AVAILABLE:
            # Indexation
            indexing_result = self.legacy_indexer.index_documents(mel_items, mmel_items)
            matches = [m.to_dict() for m in indexing_result.matches]

            # Comparaison
            return self.legacy_comparator.run_audit(mel_items, mmel_items, matches)
        return None

    def _save_audit_result(self, result: AuditResultV2):
        """Sauvegarde le résultat d'audit"""
        output = {
            "run_id": self.run_id,
            "audit_timestamp": result.audit_timestamp,
            "aircraft_context": result.aircraft_context,
            "statistics": {
                "total_comparisons": result.total_comparisons,
                "compliant": result.compliant_count,
                "more_restrictive": result.more_restrictive_count,
                "less_restrictive": result.less_restrictive_count,
                "missing": result.missing_count,
                "critical_count": result.critical_count,
                "hitl_required": result.hitl_required_count,
                "compliance_rate": result.overall_compliance_rate
            },
            "comparisons": [c.to_dict() for c in result.comparisons]
        }

        output_path = self.output_dir / f"audit_result_v2_{self.run_id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"Audit sauvegardé: {output_path}")

        # Générer le log HITL
        if self.config.generate_hitl_log and result.hitl_required_count > 0:
            self._generate_hitl_log(result)

    def _generate_hitl_log(self, result: AuditResultV2):
        """Génère le log HITL"""
        hitl_items = [c for c in result.comparisons if c.requires_hitl]

        hitl_log = {
            "generated_at": datetime.now().isoformat(),
            "run_id": self.run_id,
            "total_items_for_review": len(hitl_items),
            "by_severity": {
                "critical": sum(1 for c in hitl_items if c.severity.value == "critical"),
                "high": sum(1 for c in hitl_items if c.severity.value == "high"),
                "medium": sum(1 for c in hitl_items if c.severity.value == "medium"),
                "warning": sum(1 for c in hitl_items if c.severity.value == "warning")
            },
            "items": [
                {
                    "mel_item_id": c.mel_item_id,
                    "mmel_item_id": c.mmel_item_id,
                    "verdict": c.verdict.value,
                    "severity": c.severity.value,
                    "sla_hours": c.sla_hours,
                    "reasons": c.hitl_reasons,
                    "validation": {
                        "status": "PENDING",
                        "validated_by": None,
                        "validated_at": None
                    }
                }
                for c in hitl_items
            ]
        }

        hitl_path = self.output_dir / f"hitl_log_{self.run_id}.json"
        with open(hitl_path, "w", encoding="utf-8") as f:
            json.dump(hitl_log, f, indent=2, ensure_ascii=False)

        logger.info(f"Log HITL généré: {hitl_path} ({len(hitl_items)} items)")

    # =========================================================================
    # PIPELINE COMPLET
    # =========================================================================

    def run_full_pipeline(self, mel_source: str, mmel_source: str,
                         mel_is_json: bool = False, mmel_is_json: bool = False) -> Dict[str, Any]:
        """
        Exécute le pipeline complet V2.

        Args:
            mel_source: Chemin vers MEL (PDF ou JSON)
            mmel_source: Chemin vers MMEL (PDF ou JSON)
            mel_is_json: True si MEL déjà parsé (JSON)
            mmel_is_json: True si MMEL déjà parsé (JSON)

        Returns:
            Rapport final avec statistiques et fichiers générés
        """
        logger.info(f"=== Pipeline V2 démarré (Run ID: {self.run_id}) ===")
        logger.info(f"Contexte: MSN {self.config.aircraft_msn}, {self.config.operation_type}")

        self.state["status"] = "running"

        try:
            # 1. Parsing/Chargement MEL
            if mel_is_json:
                mel_items = self.load_parsed_data(mel_source, "MEL")
            else:
                mel_items = self.parse_document_v2(mel_source, "MEL")

            # 2. Parsing/Chargement MMEL
            if mmel_is_json:
                mmel_items = self.load_parsed_data(mmel_source, "MMEL")
            else:
                mmel_items = self.parse_document_v2(mmel_source, "MMEL")

            # 3. Construction arbre MMEL + Comparaison
            audit_result = self.run_comparison_v2(mel_items, mmel_items)

            # 4. Génération du rapport final
            report = self._generate_final_report(audit_result)

            self.state["status"] = "completed"
            self._save_pipeline_state()

            logger.info(f"=== Pipeline V2 terminé avec succès ===")
            logger.info(f"Taux de conformité: {audit_result.overall_compliance_rate}%")

            return report

        except Exception as e:
            logger.error(f"Pipeline V2 échoué: {e}")
            self.state["status"] = "failed"
            self.state["error"] = str(e)
            self._save_pipeline_state()
            raise

    def _generate_final_report(self, audit_result: AuditResultV2) -> Dict[str, Any]:
        """Génère le rapport final"""
        report = {
            "run_id": self.run_id,
            "pipeline_version": "v2",
            "generated_at": datetime.now().isoformat(),
            "aircraft_context": {
                "msn": self.config.aircraft_msn,
                "operation": self.config.operation_type,
                "aircraft_type": self.config.aircraft_type
            },
            "summary": {
                "total_items_compared": audit_result.total_comparisons,
                "compliant": audit_result.compliant_count,
                "more_restrictive": audit_result.more_restrictive_count,
                "less_restrictive_critical": audit_result.less_restrictive_count,
                "missing_items": audit_result.missing_count,
                "compliance_rate": audit_result.overall_compliance_rate,
                "items_requiring_review": audit_result.hitl_required_count
            },
            "severity_breakdown": {
                "critical": audit_result.critical_count,
                "high": audit_result.high_count,
                "medium": audit_result.medium_count,
                "warning": audit_result.warning_count,
                "info": audit_result.info_count
            },
            "critical_findings": [],
            "recommendations": [],
            "output_files": {}
        }

        # Extraire les findings critiques
        for comp in audit_result.comparisons:
            if comp.severity.value == "critical":
                report["critical_findings"].append({
                    "mel_item": comp.mel_item_id,
                    "mmel_item": comp.mmel_item_id,
                    "verdict": comp.verdict.value,
                    "reasons": comp.hitl_reasons,
                    "sla_hours": comp.sla_hours
                })

        # Recommandations
        if audit_result.less_restrictive_count > 0:
            report["recommendations"].append({
                "priority": "CRITICAL",
                "action": f"Revoir immédiatement les {audit_result.less_restrictive_count} items où la MEL est moins restrictive que la MMEL",
                "sla": "48 heures"
            })

        if audit_result.missing_count > 0:
            report["recommendations"].append({
                "priority": "HIGH",
                "action": f"Vérifier les {audit_result.missing_count} items manquants",
                "sla": "1 semaine"
            })

        # Fichiers générés
        report["output_files"] = {
            "audit_result": str(self.output_dir / f"audit_result_v2_{self.run_id}.json"),
            "hitl_log": str(self.output_dir / f"hitl_log_{self.run_id}.json"),
            "final_report": str(self.output_dir / f"final_report_{self.run_id}.json")
        }

        # Sauvegarder
        report_path = self.output_dir / f"final_report_{self.run_id}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        return report

    def _save_pipeline_state(self):
        """Sauvegarde l'état du pipeline"""
        state_path = self.output_dir / f"pipeline_state_{self.run_id}.json"
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False, default=str)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="MoA_MEL Audit Pipeline V2 - Architecture Optimisée",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Avec PDFs
  python pipeline_v2.py --mel MEL.pdf --mmel MMEL.pdf --msn 1280 --operation CAT

  # Avec données pré-parsées
  python pipeline_v2.py --mel mel.json --mmel mmel.json --mel-json --mmel-json --msn 1280 --operation CAT

  # Avec clé API pour parsing LLM
  python pipeline_v2.py --mel MEL.pdf --mmel MMEL.pdf --msn 1280 --api-key $MISTRAL_API_KEY
        """
    )

    # Sources
    parser.add_argument("--mel", required=True, help="Chemin vers MEL (PDF ou JSON)")
    parser.add_argument("--mmel", required=True, help="Chemin vers MMEL (PDF ou JSON)")
    parser.add_argument("--mel-json", action="store_true", help="MEL est un fichier JSON pré-parsé")
    parser.add_argument("--mmel-json", action="store_true", help="MMEL est un fichier JSON pré-parsé")

    # Contexte avion
    parser.add_argument("--msn", type=int, default=0, help="MSN de l'avion (ex: 1280)")
    parser.add_argument("--operation", default="CAT", choices=["CAT", "SPO", "NCO", "NCC"],
                       help="Type d'opération")
    parser.add_argument("--aircraft-type", default="", help="Type d'avion (ex: A320-214)")
    parser.add_argument("--etops", action="store_true", help="Avion certifié ETOPS")

    # API
    parser.add_argument("--api-key", default=os.getenv("MISTRAL_API_KEY", ""),
                       help="Clé API Mistral (ou env MISTRAL_API_KEY)")

    # Options
    parser.add_argument("--output-dir", default="outputs", help="Répertoire de sortie")
    parser.add_argument("--no-llm", action="store_true", help="Désactiver le parsing LLM")
    parser.add_argument("--no-self-healing", action="store_true", help="Désactiver le self-healing")

    args = parser.parse_args()

    # Vérifier les fichiers
    if not Path(args.mel).exists():
        logger.error(f"Fichier MEL non trouvé: {args.mel}")
        sys.exit(1)
    if not Path(args.mmel).exists():
        logger.error(f"Fichier MMEL non trouvé: {args.mmel}")
        sys.exit(1)

    # Configuration
    config = PipelineConfigV2(
        api_key=args.api_key,
        aircraft_msn=args.msn,
        operation_type=args.operation,
        aircraft_type=args.aircraft_type,
        etops_certified=args.etops,
        output_dir=args.output_dir,
        use_llm_parser=not args.no_llm and bool(args.api_key),
        enable_self_healing=not args.no_self_healing
    )

    # Exécuter le pipeline
    pipeline = MoAMELPipelineV2(config)

    result = pipeline.run_full_pipeline(
        mel_source=args.mel,
        mmel_source=args.mmel,
        mel_is_json=args.mel_json,
        mmel_is_json=args.mmel_json
    )

    # Afficher le résumé
    print("\n" + "=" * 60)
    print("AUDIT MEL/MMEL TERMINÉ")
    print("=" * 60)
    print(f"\nContexte: MSN {args.msn}, Opération {args.operation}")
    print(f"\nRésumé:")
    print(json.dumps(result["summary"], indent=2))

    if result["critical_findings"]:
        print(f"\n⚠️  FINDINGS CRITIQUES: {len(result['critical_findings'])}")
        for finding in result["critical_findings"][:5]:
            print(f"   - {finding['mel_item']}: {finding['verdict']}")

    print(f"\nFichiers générés: {result['output_files']}")


if __name__ == "__main__":
    main()
