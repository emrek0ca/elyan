"""
Document Knowledge Base System
Extracts and indexes content from documents for semantic search
"""

import asyncio
import json
from typing import Dict, List, Optional, Any, Set
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("knowledge_base")


@dataclass
class DocumentIndex:
    """Indexed document content"""
    document_id: str
    file_path: str
    file_type: str
    indexed_at: str
    content_length: int
    chunks: List[str] = field(default_factory=list)
    keywords: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "file_path": self.file_path,
            "file_type": self.file_type,
            "indexed_at": self.indexed_at,
            "content_length": self.content_length,
            "chunk_count": len(self.chunks),
            "keyword_count": len(self.keywords),
            "metadata": self.metadata
        }


class DocumentKnowledgeBase:
    """Indexes documents and provides semantic search"""

    CHUNK_SIZE = 500  # Characters per chunk
    MIN_CHUNK_SIZE = 100

    def __init__(self, max_documents: int = 100):
        self.documents: Dict[str, DocumentIndex] = {}
        self.max_documents = max_documents
        self.embedder = None

    async def initialize(self):
        """Initialize embedder if available (v17.0 Shared)"""
        from .model_manager import get_shared_embedder
        self.embedder = await get_shared_embedder()
        if self.embedder:
            logger.info("Knowledge base linked to shared embedder")
        else:
            logger.warning("Shared embedder not available for KB")

    async def index_document(self, file_path: str, content: str) -> Optional[DocumentIndex]:
        """Index a document"""
        import hashlib

        path = Path(file_path)
        file_type = path.suffix[1:] if path.suffix else "txt"

        # Generate document ID
        doc_id = hashlib.md5(f"{file_path}{len(content)}".encode()).hexdigest()[:8]

        if doc_id in self.documents:
            logger.info(f"Document already indexed: {file_path}")
            return self.documents[doc_id]

        # Split into chunks
        chunks = self._create_chunks(content)

        # Extract keywords
        keywords = self._extract_keywords(content)

        # Create index
        doc_index = DocumentIndex(
            document_id=doc_id,
            file_path=str(file_path),
            file_type=file_type,
            indexed_at=datetime.now().isoformat(),
            content_length=len(content),
            chunks=chunks,
            keywords=keywords,
            metadata={
                "file_size": path.stat().st_size if path.exists() else 0,
                "chunk_count": len(chunks)
            }
        )

        self.documents[doc_id] = doc_index
        logger.info(f"Indexed document {doc_id}: {path.name} ({len(chunks)} chunks)")

        # Cleanup old documents if exceeding limit
        if len(self.documents) > self.max_documents:
            self._cleanup_oldest()

        return doc_index

    async def search_documents(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search indexed documents"""
        if not self.documents:
            return []

        results = []

        for doc_id, doc_index in self.documents.items():
            # Match score based on keywords
            query_words = set(query.lower().split())
            matching_keywords = len(query_words & doc_index.keywords)

            if matching_keywords > 0:
                # Find best matching chunk
                best_chunk = self._find_best_chunk(query, doc_index.chunks)

                relevance = matching_keywords / max(len(query_words), len(doc_index.keywords))

                results.append({
                    "document_id": doc_id,
                    "file_path": doc_index.file_path,
                    "file_type": doc_index.file_type,
                    "relevance": relevance,
                    "matching_keywords": matching_keywords,
                    "preview": best_chunk[:200] + "..." if best_chunk else "",
                    "metadata": doc_index.metadata
                })

        # Sort by relevance
        results.sort(key=lambda x: x["relevance"], reverse=True)
        return results[:top_k]

    async def extract_chunk(self, document_id: str, chunk_index: int) -> Optional[str]:
        """Extract specific chunk from document"""
        doc_index = self.documents.get(document_id)
        if doc_index and 0 <= chunk_index < len(doc_index.chunks):
            return doc_index.chunks[chunk_index]
        return None

    async def get_document_summary(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get summary of indexed document"""
        doc_index = self.documents.get(document_id)
        if not doc_index:
            return None

        return {
            "document_id": document_id,
            "file_path": doc_index.file_path,
            "file_type": doc_index.file_type,
            "content_length": doc_index.content_length,
            "chunks": len(doc_index.chunks),
            "keywords": sorted(list(doc_index.keywords))[:20],
            "indexed_at": doc_index.indexed_at,
            "metadata": doc_index.metadata
        }

    def _create_chunks(self, content: str) -> List[str]:
        """Split content into overlapping chunks"""
        chunks = []
        sentences = content.replace("\n", " ").split(". ")

        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk) + len(sentence) < self.CHUNK_SIZE:
                current_chunk += sentence + ". "
            else:
                if len(current_chunk) >= self.MIN_CHUNK_SIZE:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence + ". "

        if len(current_chunk) >= self.MIN_CHUNK_SIZE:
            chunks.append(current_chunk.strip())

        return chunks if chunks else [content]

    def _extract_keywords(self, content: str, top_k: int = 20) -> Set[str]:
        """Extract keywords from content"""
        # Simple keyword extraction - filter stop words
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "is", "are", "be", "been", "have", "has",
            "that", "this", "these", "those", "what", "which", "who", "why", "how"
        }

        words = content.lower().split()
        keywords = set()

        for word in words:
            clean_word = word.strip(".,!?;:()").strip()
            if len(clean_word) > 3 and clean_word not in stop_words:
                keywords.add(clean_word)

        return keywords

    def _find_best_chunk(self, query: str, chunks: List[str]) -> Optional[str]:
        """Find chunk most relevant to query"""
        query_words = set(query.lower().split())
        best_chunk = None
        best_score = 0

        for chunk in chunks:
            chunk_words = set(chunk.lower().split())
            matching = len(query_words & chunk_words)
            if matching > best_score:
                best_score = matching
                best_chunk = chunk

        return best_chunk

    def _cleanup_oldest(self):
        """Remove oldest indexed document"""
        if not self.documents:
            return

        oldest_id = min(
            self.documents.keys(),
            key=lambda k: self.documents[k].indexed_at
        )
        del self.documents[oldest_id]
        logger.info(f"Cleaned up oldest document: {oldest_id}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        total_keywords = set()
        total_content = 0

        for doc_index in self.documents.values():
            total_keywords.update(doc_index.keywords)
            total_content += doc_index.content_length

        return {
            "indexed_documents": len(self.documents),
            "total_keywords": len(total_keywords),
            "total_content_length": total_content,
            "average_document_size": total_content // max(len(self.documents), 1),
            "documents": [doc_index.to_dict() for doc_index in self.documents.values()]
        }

    async def clear(self):
        """Clear all indexed documents"""
        count = len(self.documents)
        self.documents.clear()
        logger.info(f"Cleared knowledge base, removed {count} documents")


# Global instance
_knowledge_base: Optional[DocumentKnowledgeBase] = None


async def get_knowledge_base() -> DocumentKnowledgeBase:
    """Get or create knowledge base"""
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = DocumentKnowledgeBase()
        await _knowledge_base.initialize()
    return _knowledge_base
