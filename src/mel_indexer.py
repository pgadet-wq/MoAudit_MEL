"""
MoA_MEL_Indexer - Matching MEL ↔ MMEL
======================================
Matching exact (ATA Chapter + Item Number) et sémantique (embeddings)
pour aligner les items MEL avec leur référence MMEL.
"""

import json
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime
import logging
import re
import sqlite3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MoA_MEL_Indexer")


@dataclass
class MatchResult:
    """Résultat d'un matching MEL ↔ MMEL"""
    mel_item_id: str
    mmel_item_id: Optional[str]
    
    # Scores
    exact_match: bool
    exact_score: float
    semantic_score: float
    combined_score: float
    
    # Détails
    match_type: str  # "exact", "semantic", "partial", "none"
    match_confidence: str  # "high", "medium", "low", "no_match"
    
    # Flags
    requires_hitl_review: bool = False
    hitl_reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IndexingResult:
    """Résultat global de l'indexation"""
    mel_document: str
    mmel_document: str
    indexing_timestamp: str
    
    # Statistiques
    total_mel_items: int
    total_mmel_items: int
    matched_items: int
    unmatched_mel_items: int
    unmatched_mmel_items: int
    
    # Détails
    matches: List[MatchResult] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "matches": [m.to_dict() for m in self.matches]
        }


class MistralEmbeddingClient:
    """Client pour les embeddings Mistral"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.mistral.ai/v1"
        self.model = "mistral-embed"
        self._cache = {}
    
    def get_embedding(self, text: str) -> List[float]:
        """Obtient l'embedding d'un texte"""
        # Cache simple
        cache_key = hash(text)
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        import requests
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "input": [text]
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            embedding = result["data"][0]["embedding"]
            self._cache[cache_key] = embedding
            return embedding
        except Exception as e:
            logger.error(f"Erreur embedding: {e}")
            return []
    
    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Obtient les embeddings pour un batch de textes"""
        import requests
        
        # Filtrer les textes vides
        valid_texts = [t for t in texts if t.strip()]
        if not valid_texts:
            return [[] for _ in texts]
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Batch par 32 (limite API)
        all_embeddings = []
        batch_size = 32
        
        for i in range(0, len(valid_texts), batch_size):
            batch = valid_texts[i:i + batch_size]
            payload = {
                "model": self.model,
                "input": batch
            }
            
            try:
                response = requests.post(
                    f"{self.base_url}/embeddings",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                response.raise_for_status()
                result = response.json()
                embeddings = [d["embedding"] for d in result["data"]]
                all_embeddings.extend(embeddings)
            except Exception as e:
                logger.error(f"Erreur embedding batch: {e}")
                all_embeddings.extend([[] for _ in batch])
        
        # Réassigner aux positions originales
        result = []
        valid_idx = 0
        for t in texts:
            if t.strip():
                result.append(all_embeddings[valid_idx] if valid_idx < len(all_embeddings) else [])
                valid_idx += 1
            else:
                result.append([])
        
        return result


class MELIndexer:
    """Indexeur pour matching MEL ↔ MMEL"""
    
    def __init__(self, api_key: str = "", semantic_threshold: float = 0.85,
                 exact_weight: float = 0.6, semantic_weight: float = 0.4):
        self.embedding_client = MistralEmbeddingClient(api_key) if api_key else None
        self.semantic_threshold = semantic_threshold
        self.exact_weight = exact_weight
        self.semantic_weight = semantic_weight
        
        # Index en mémoire
        self.mmel_index = {}  # key: normalized_id, value: item_data
        self.mel_index = {}
        self.mmel_embeddings = {}  # key: item_id, value: embedding
    
    @staticmethod
    def normalize_ata_chapter(ata: str) -> str:
        """Normalise un chapitre ATA pour comparaison"""
        # Enlever espaces et caractères spéciaux
        ata = re.sub(r'[^\d\-]', '', str(ata).strip())
        # Format standard: XX ou XX-XX ou XX-XX-XX
        return ata.upper()
    
    @staticmethod
    def normalize_item_number(item_num: str) -> str:
        """Normalise un numéro d'item pour comparaison"""
        # Enlever espaces et standardiser
        item = re.sub(r'\s+', '', str(item_num).strip())
        return item.upper()
    
    @staticmethod
    def create_item_key(ata_chapter: str, item_number: str) -> str:
        """Crée une clé unique pour un item"""
        ata = MELIndexer.normalize_ata_chapter(ata_chapter)
        item = MELIndexer.normalize_item_number(item_number)
        return f"{ata}|{item}"
    
    @staticmethod
    def create_search_text(item: Dict[str, Any]) -> str:
        """Crée le texte pour la recherche sémantique"""
        parts = [
            item.get("item_description", ""),
            item.get("remarks", ""),
            item.get("exceptions", "")
        ]
        return " ".join(p for p in parts if p).strip()
    
    def cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Calcule la similarité cosinus entre deux vecteurs"""
        if not v1 or not v2:
            return 0.0
        
        a = np.array(v1)
        b = np.array(v2)
        
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(dot / (norm_a * norm_b))
    
    def load_items(self, items: List[Dict[str, Any]], document_type: str):
        """Charge les items dans l'index approprié"""
        index = self.mmel_index if document_type in ["MMEL", "CS-MMEL"] else self.mel_index
        
        for item in items:
            key = self.create_item_key(
                item.get("ata_chapter", ""),
                item.get("item_number", "")
            )
            if key:
                index[key] = item
        
        logger.info(f"Loaded {len(items)} items into {document_type} index")
    
    def build_semantic_index(self, document_type: str = "MMEL"):
        """Construit l'index sémantique pour les items MMEL"""
        if not self.embedding_client:
            logger.warning("No embedding client configured, semantic matching disabled")
            return
        
        index = self.mmel_index if document_type in ["MMEL", "CS-MMEL"] else self.mel_index
        
        # Préparer les textes
        items_list = list(index.items())
        texts = [self.create_search_text(item) for _, item in items_list]
        
        # Obtenir les embeddings
        logger.info(f"Computing embeddings for {len(texts)} items...")
        embeddings = self.embedding_client.get_embeddings_batch(texts)
        
        # Stocker dans l'index
        for (key, _), embedding in zip(items_list, embeddings):
            self.mmel_embeddings[key] = embedding
        
        logger.info(f"Semantic index built with {len(self.mmel_embeddings)} embeddings")
    
    def find_exact_match(self, mel_item: Dict[str, Any]) -> Tuple[Optional[str], float]:
        """Recherche un match exact par ATA + Item Number"""
        key = self.create_item_key(
            mel_item.get("ata_chapter", ""),
            mel_item.get("item_number", "")
        )
        
        if key in self.mmel_index:
            return key, 1.0
        
        # Essayer des variations
        ata = self.normalize_ata_chapter(mel_item.get("ata_chapter", ""))
        item = self.normalize_item_number(mel_item.get("item_number", ""))
        
        # Recherche partielle sur ATA chapter
        for mmel_key in self.mmel_index:
            mmel_ata, mmel_item = mmel_key.split("|", 1)
            
            # Match exact sur item, partiel sur ATA
            if mmel_item == item and (ata.startswith(mmel_ata) or mmel_ata.startswith(ata)):
                return mmel_key, 0.9
        
        return None, 0.0
    
    def find_semantic_match(self, mel_item: Dict[str, Any], top_k: int = 3) -> List[Tuple[str, float]]:
        """Recherche les meilleurs matches sémantiques"""
        if not self.embedding_client or not self.mmel_embeddings:
            return []
        
        # Obtenir l'embedding du MEL item
        mel_text = self.create_search_text(mel_item)
        if not mel_text:
            return []
        
        mel_embedding = self.embedding_client.get_embedding(mel_text)
        if not mel_embedding:
            return []
        
        # Calculer les similarités
        similarities = []
        for mmel_key, mmel_embedding in self.mmel_embeddings.items():
            if mmel_embedding:
                sim = self.cosine_similarity(mel_embedding, mmel_embedding)
                similarities.append((mmel_key, sim))
        
        # Trier par similarité décroissante
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        return similarities[:top_k]
    
    def match_item(self, mel_item: Dict[str, Any]) -> MatchResult:
        """Effectue le matching complet pour un item MEL"""
        mel_key = self.create_item_key(
            mel_item.get("ata_chapter", ""),
            mel_item.get("item_number", "")
        )
        
        # 1. Recherche exacte
        exact_key, exact_score = self.find_exact_match(mel_item)
        
        # 2. Recherche sémantique
        semantic_matches = self.find_semantic_match(mel_item)
        best_semantic_key = semantic_matches[0][0] if semantic_matches else None
        semantic_score = semantic_matches[0][1] if semantic_matches else 0.0
        
        # 3. Combiner les scores
        if exact_key:
            # Match exact trouvé
            mmel_key = exact_key
            combined_score = self.exact_weight * exact_score + self.semantic_weight * semantic_score
            match_type = "exact"
            match_confidence = "high"
        elif semantic_score >= self.semantic_threshold:
            # Match sémantique fort
            mmel_key = best_semantic_key
            combined_score = self.semantic_weight * semantic_score
            match_type = "semantic"
            match_confidence = "high" if semantic_score >= 0.95 else "medium"
        elif semantic_score >= 0.7:
            # Match sémantique partiel
            mmel_key = best_semantic_key
            combined_score = self.semantic_weight * semantic_score
            match_type = "partial"
            match_confidence = "medium"
        else:
            # Pas de match
            mmel_key = None
            combined_score = 0.0
            match_type = "none"
            match_confidence = "no_match"
        
        # 4. Déterminer si HITL requis
        requires_hitl = match_type in ["partial", "none"] or match_confidence == "medium"
        hitl_reason = ""
        if requires_hitl:
            if match_type == "none":
                hitl_reason = "No matching MMEL item found"
            elif match_type == "partial":
                hitl_reason = f"Partial semantic match only (score: {semantic_score:.2f})"
            else:
                hitl_reason = f"Medium confidence match"
        
        return MatchResult(
            mel_item_id=mel_key,
            mmel_item_id=mmel_key,
            exact_match=exact_key is not None,
            exact_score=exact_score,
            semantic_score=semantic_score,
            combined_score=combined_score,
            match_type=match_type,
            match_confidence=match_confidence,
            requires_hitl_review=requires_hitl,
            hitl_reason=hitl_reason
        )
    
    def index_documents(self, mel_items: List[Dict[str, Any]], 
                       mmel_items: List[Dict[str, Any]]) -> IndexingResult:
        """Indexe et matche deux documents MEL et MMEL"""
        
        # Charger les index
        self.load_items(mmel_items, "MMEL")
        self.load_items(mel_items, "MEL")
        
        # Construire l'index sémantique MMEL
        if self.embedding_client:
            self.build_semantic_index("MMEL")
        
        # Matcher chaque item MEL
        matches = []
        matched_mmel_keys = set()
        
        for mel_item in mel_items:
            match = self.match_item(mel_item)
            matches.append(match)
            if match.mmel_item_id:
                matched_mmel_keys.add(match.mmel_item_id)
        
        # Identifier les items MMEL non matchés
        unmatched_mmel = set(self.mmel_index.keys()) - matched_mmel_keys
        
        result = IndexingResult(
            mel_document=mel_items[0].get("source_document", "MEL") if mel_items else "MEL",
            mmel_document=mmel_items[0].get("source_document", "MMEL") if mmel_items else "MMEL",
            indexing_timestamp=datetime.now().isoformat(),
            total_mel_items=len(mel_items),
            total_mmel_items=len(mmel_items),
            matched_items=sum(1 for m in matches if m.mmel_item_id),
            unmatched_mel_items=sum(1 for m in matches if not m.mmel_item_id),
            unmatched_mmel_items=len(unmatched_mmel),
            matches=matches
        )
        
        logger.info(f"Indexing complete: {result.matched_items}/{result.total_mel_items} MEL items matched")
        logger.info(f"Unmatched MMEL items: {result.unmatched_mmel_items}")
        
        return result
    
    def save_indexing_result(self, result: IndexingResult, output_path: str) -> str:
        """Sauvegarde le résultat de l'indexation"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.info(f"Indexing result saved to: {output_path}")
        return str(output_path)
    
    def generate_hitl_log(self, result: IndexingResult, log_path: str) -> str:
        """Génère le log HITL pour les matchings incertains"""
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        hitl_matches = [m for m in result.matches if m.requires_hitl_review]
        
        log_data = {
            "generated_at": datetime.now().isoformat(),
            "mel_document": result.mel_document,
            "mmel_document": result.mmel_document,
            "total_items_for_review": len(hitl_matches),
            "items": []
        }
        
        for match in hitl_matches:
            mel_item = self.mel_index.get(match.mel_item_id, {})
            mmel_item = self.mmel_index.get(match.mmel_item_id, {}) if match.mmel_item_id else {}
            
            log_data["items"].append({
                "mel_item_id": match.mel_item_id,
                "mmel_item_id": match.mmel_item_id,
                "match_type": match.match_type,
                "semantic_score": match.semantic_score,
                "reason": match.hitl_reason,
                "mel_data": {
                    "ata_chapter": mel_item.get("ata_chapter"),
                    "item_number": mel_item.get("item_number"),
                    "description": mel_item.get("item_description"),
                    "category": mel_item.get("category")
                },
                "mmel_data": {
                    "ata_chapter": mmel_item.get("ata_chapter"),
                    "item_number": mmel_item.get("item_number"),
                    "description": mmel_item.get("item_description"),
                    "category": mmel_item.get("category")
                } if mmel_item else None,
                "validation": {
                    "status": "PENDING",
                    "correct_mmel_id": None,
                    "validated_by": None,
                    "validated_at": None,
                    "comments": None
                }
            })
        
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"HITL matching log generated: {log_path}")
        return str(log_path)


# Database helper for persistent storage
class MELDatabase:
    """Stockage SQLite pour le PoC"""
    
    def __init__(self, db_path: str = "data/moa_mel.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialise la base de données"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table des items MEL
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mel_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_name TEXT,
                document_type TEXT,
                ata_chapter TEXT,
                item_number TEXT,
                item_description TEXT,
                category TEXT,
                repair_interval TEXT,
                number_installed TEXT,
                number_required TEXT,
                remarks TEXT,
                exceptions TEXT,
                source_page INTEGER,
                extraction_confidence REAL,
                content_hash TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table des matches
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mel_item_id TEXT,
                mmel_item_id TEXT,
                exact_match BOOLEAN,
                exact_score REAL,
                semantic_score REAL,
                combined_score REAL,
                match_type TEXT,
                match_confidence TEXT,
                requires_hitl BOOLEAN,
                hitl_reason TEXT,
                validated BOOLEAN DEFAULT FALSE,
                validated_by TEXT,
                validated_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Index
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mel_ata ON mel_items(ata_chapter)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mel_doc ON mel_items(document_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_mel ON matches(mel_item_id)")
        
        conn.commit()
        conn.close()
    
    def insert_items(self, items: List[Dict[str, Any]]) -> int:
        """Insère des items en base"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        inserted = 0
        for item in items:
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO mel_items 
                    (document_name, document_type, ata_chapter, item_number, item_description,
                     category, repair_interval, number_installed, number_required, remarks,
                     exceptions, source_page, extraction_confidence, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.get("source_document"),
                    item.get("document_type"),
                    item.get("ata_chapter"),
                    item.get("item_number"),
                    item.get("item_description"),
                    item.get("category"),
                    item.get("repair_interval"),
                    item.get("number_installed"),
                    item.get("number_required"),
                    item.get("remarks"),
                    item.get("exceptions"),
                    item.get("source_page"),
                    item.get("extraction_confidence"),
                    item.get("content_hash")
                ))
                inserted += 1
            except Exception as e:
                logger.error(f"Error inserting item: {e}")
        
        conn.commit()
        conn.close()
        return inserted


if __name__ == "__main__":
    # Test avec données mock
    mel_items = [
        {
            "ata_chapter": "21",
            "item_number": "21-51-01",
            "item_description": "Air Conditioning Pack",
            "category": "C",
            "remarks": "(O) May be inoperative",
            "source_document": "test_mel.pdf"
        },
        {
            "ata_chapter": "24",
            "item_number": "24-10-01",
            "item_description": "Main Battery System",
            "category": "A",
            "remarks": "",
            "source_document": "test_mel.pdf"
        }
    ]
    
    mmel_items = [
        {
            "ata_chapter": "21",
            "item_number": "21-51-01",
            "item_description": "Air Conditioning Pack Assembly",
            "category": "C",
            "remarks": "(O) May be inoperative provided remaining pack operates",
            "source_document": "test_mmel.pdf"
        },
        {
            "ata_chapter": "24",
            "item_number": "24-10-01",
            "item_description": "Main Battery",
            "category": "A",
            "remarks": "",
            "source_document": "test_mmel.pdf"
        },
        {
            "ata_chapter": "32",
            "item_number": "32-40-01",
            "item_description": "Nose Wheel Steering",
            "category": "B",
            "remarks": "",
            "source_document": "test_mmel.pdf"
        }
    ]
    
    indexer = MELIndexer()  # Sans API pour test
    result = indexer.index_documents(mel_items, mmel_items)
    
    print(f"\nIndexing Results:")
    print(f"  MEL items: {result.total_mel_items}")
    print(f"  MMEL items: {result.total_mmel_items}")
    print(f"  Matched: {result.matched_items}")
    print(f"  Unmatched MEL: {result.unmatched_mel_items}")
    print(f"  Unmatched MMEL: {result.unmatched_mmel_items}")
    
    for match in result.matches:
        print(f"\n  {match.mel_item_id} -> {match.mmel_item_id}")
        print(f"    Type: {match.match_type}, Confidence: {match.match_confidence}")
