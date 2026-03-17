"""
Semantic Knowledge Base - Domain expertise and knowledge graphs
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """Knowledge base entity"""

    entity_id: str
    name: str
    entity_type: str  # concept, object, action, attribute
    description: str
    attributes: Dict
    related_entities: List[str]
    confidence: float


@dataclass
class Relationship:
    """Relationship between entities"""

    source_id: str
    target_id: str
    relationship_type: str  # related_to, causes, requires, similar_to, etc
    strength: float  # 0-1
    context: str


class SemanticKnowledgeBase:
    """Manages semantic knowledge and ontologies"""

    def __init__(self, storage_path: str = ".elyan/semantic_kb"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
        self.ontologies: Dict[str, List[str]] = {}
        self.domain_concepts: Dict[str, float] = {}

        self._load_kb()

    def _load_kb(self):
        """Load knowledge base from storage"""
        try:
            kb_file = self.storage_path / "kb.json"
            if kb_file.exists():
                with open(kb_file) as f:
                    data = json.load(f)
                    # Load entities, relationships, etc.
                    logger.info("Knowledge base loaded")
        except Exception as e:
            logger.error(f"Failed to load KB: {e}")

    def add_entity(self, entity_id: str, name: str, entity_type: str,
                   description: str = "", attributes: Dict = None) -> str:
        """Add entity to knowledge base"""
        entity = Entity(
            entity_id=entity_id,
            name=name,
            entity_type=entity_type,
            description=description,
            attributes=attributes or {},
            related_entities=[],
            confidence=1.0
        )
        self.entities[entity_id] = entity
        return entity_id

    def add_relationship(self, source_id: str, target_id: str,
                       relationship_type: str, strength: float = 1.0,
                       context: str = ""):
        """Add relationship between entities"""
        rel = Relationship(
            source_id=source_id,
            target_id=target_id,
            relationship_type=relationship_type,
            strength=strength,
            context=context
        )
        self.relationships.append(rel)

        # Update related entities
        if source_id in self.entities:
            self.entities[source_id].related_entities.append(target_id)

    def build_ontology(self, domain: str, concepts: List[str]):
        """Build domain ontology"""
        self.ontologies[domain] = concepts
        for concept in concepts:
            self.domain_concepts[concept] = 1.0 / len(concepts)

    def find_related_entities(self, entity_id: str, rel_type: str = None) -> List[Entity]:
        """Find related entities"""
        results = []

        for rel in self.relationships:
            if rel.source_id == entity_id:
                if rel_type is None or rel.relationship_type == rel_type:
                    if rel.target_id in self.entities:
                        results.append(self.entities[rel.target_id])

        return results

    def get_entity_properties(self, entity_id: str) -> Dict:
        """Get all properties of an entity"""
        if entity_id not in self.entities:
            return {"error": "Entity not found"}

        entity = self.entities[entity_id]
        related = [self.entities[eid].name for eid in entity.related_entities if eid in self.entities]

        return {
            "id": entity.entity_id,
            "name": entity.name,
            "type": entity.entity_type,
            "description": entity.description,
            "attributes": entity.attributes,
            "related": related,
            "confidence": entity.confidence
        }

    def semantic_similarity(self, entity1_id: str, entity2_id: str) -> float:
        """Calculate semantic similarity between entities"""
        if entity1_id not in self.entities or entity2_id not in self.entities:
            return 0.0

        e1 = self.entities[entity1_id]
        e2 = self.entities[entity2_id]

        # Check if directly related
        for rel in self.relationships:
            if (rel.source_id == entity1_id and rel.target_id == entity2_id):
                if rel.relationship_type in ["similar_to", "related_to"]:
                    return rel.strength

        # Check type similarity
        if e1.entity_type == e2.entity_type:
            return 0.5

        return 0.0

    def query_entities(self, query: str, limit: int = 5) -> List[Entity]:
        """Query entities by name or description"""
        results = []

        for entity in self.entities.values():
            score = 0.0
            if query.lower() in entity.name.lower():
                score += 1.0
            if query.lower() in entity.description.lower():
                score += 0.5

            if score > 0:
                results.append((score, entity))

        results.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in results[:limit]]

    def get_knowledge_graph(self) -> Dict:
        """Get knowledge graph representation"""
        return {
            "entities": len(self.entities),
            "relationships": len(self.relationships),
            "ontologies": list(self.ontologies.keys()),
            "domain_concepts": self.domain_concepts
        }

    def export_kb(self) -> Dict:
        """Export knowledge base"""
        return {
            "entities": {k: v.__dict__ for k, v in self.entities.items()},
            "relationships": [r.__dict__ for r in self.relationships],
            "ontologies": self.ontologies,
            "domain_concepts": self.domain_concepts,
            "exported_at": datetime.now().isoformat()
        }
