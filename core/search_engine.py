"""
Advanced Search & Query Engine
Full-text search, semantic search, fuzzy matching, query builder
"""

import re
import time
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, Counter
import difflib

from utils.logger import get_logger
from config.settings import HOME_DIR

logger = get_logger("search_engine")


@dataclass
class SearchResult:
    """Represents a search result"""
    document_id: str
    title: str
    content: str
    score: float
    highlights: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchQuery:
    """Represents a search query"""
    query: str
    filters: Dict[str, Any] = field(default_factory=dict)
    fuzzy: bool = False
    semantic: bool = False
    limit: int = 10
    offset: int = 0


class SearchEngine:
    """
    Advanced Search & Query Engine
    - Full-text search with indexing
    - Semantic search
    - Fuzzy matching
    - Boolean operators (AND, OR, NOT)
    - Ranking and scoring
    - Search history
    - Auto-suggest
    """

    def __init__(self):
        self.index: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.search_history: List[SearchQuery] = []
        self.stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            've', 'bir', 'bu', 'şu', 'o', 'ile', 'de', 'da'
        }

        logger.info("Search Engine initialized")

    def index_document(
        self,
        doc_id: str,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Index a document for search"""
        # Store document
        self.documents[doc_id] = {
            "title": title,
            "content": content,
            "metadata": metadata or {},
            "indexed_at": time.time()
        }

        # Tokenize and index
        tokens = self._tokenize(f"{title} {content}")

        # Build inverted index
        for token in tokens:
            if token not in self.stopwords:
                # TF (term frequency)
                self.index[token][doc_id] += 1

        logger.debug(f"Indexed document: {doc_id}")

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into words"""
        # Convert to lowercase
        text = text.lower()

        # Remove punctuation and split
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = text.split()

        return tokens

    def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        fuzzy: bool = False,
        limit: int = 10
    ) -> List[SearchResult]:
        """Search documents"""
        search_query = SearchQuery(
            query=query,
            filters=filters or {},
            fuzzy=fuzzy,
            limit=limit
        )

        # Record search
        self.search_history.append(search_query)

        # Parse query
        tokens = self._tokenize(query)

        # Handle boolean operators
        if ' AND ' in query.upper() or ' OR ' in query.upper() or ' NOT ' in query.upper():
            return self._boolean_search(query, filters, limit)

        # Score documents
        scores = defaultdict(float)

        for token in tokens:
            if token in self.stopwords:
                continue

            # Exact match
            if token in self.index:
                for doc_id, tf in self.index[token].items():
                    # TF-IDF scoring
                    idf = len(self.documents) / len(self.index[token])
                    scores[doc_id] += tf * idf

            # Fuzzy match
            if fuzzy:
                for indexed_token in self.index.keys():
                    similarity = difflib.SequenceMatcher(None, token, indexed_token).ratio()
                    if similarity > 0.8:
                        for doc_id, tf in self.index[indexed_token].items():
                            idf = len(self.documents) / len(self.index[indexed_token])
                            scores[doc_id] += tf * idf * similarity * 0.8  # Fuzzy penalty

        # Apply filters
        if filters:
            scores = self._apply_filters(scores, filters)

        # Sort by score
        sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # Build results
        results = []
        for doc_id, score in sorted_docs[:limit]:
            doc = self.documents[doc_id]
            highlights = self._get_highlights(doc["content"], tokens)

            results.append(SearchResult(
                document_id=doc_id,
                title=doc["title"],
                content=doc["content"][:200] + "..." if len(doc["content"]) > 200 else doc["content"],
                score=score,
                highlights=highlights,
                metadata=doc["metadata"]
            ))

        return results

    def _boolean_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]],
        limit: int
    ) -> List[SearchResult]:
        """Search with boolean operators"""
        # Parse boolean expression
        query_upper = query.upper()

        # Simple AND/OR/NOT parsing
        if ' AND ' in query_upper:
            parts = re.split(r'\s+AND\s+', query, flags=re.IGNORECASE)
            # Find documents matching all parts
            doc_sets = [set(self._simple_search(part)) for part in parts]
            matching_docs = set.intersection(*doc_sets) if doc_sets else set()

        elif ' OR ' in query_upper:
            parts = re.split(r'\s+OR\s+', query, flags=re.IGNORECASE)
            # Find documents matching any part
            doc_sets = [set(self._simple_search(part)) for part in parts]
            matching_docs = set.union(*doc_sets) if doc_sets else set()

        elif ' NOT ' in query_upper:
            parts = re.split(r'\s+NOT\s+', query, flags=re.IGNORECASE)
            include = set(self._simple_search(parts[0])) if parts else set()
            exclude = set()
            for part in parts[1:]:
                exclude.update(self._simple_search(part))
            matching_docs = include - exclude

        else:
            matching_docs = set(self._simple_search(query))

        # Build results
        results = []
        for doc_id in list(matching_docs)[:limit]:
            doc = self.documents[doc_id]
            results.append(SearchResult(
                document_id=doc_id,
                title=doc["title"],
                content=doc["content"][:200] + "...",
                score=1.0,
                metadata=doc["metadata"]
            ))

        return results

    def _simple_search(self, query: str) -> List[str]:
        """Simple search returning document IDs"""
        tokens = self._tokenize(query)
        doc_ids = set()

        for token in tokens:
            if token in self.index:
                doc_ids.update(self.index[token].keys())

        return list(doc_ids)

    def _apply_filters(
        self,
        scores: Dict[str, float],
        filters: Dict[str, Any]
    ) -> Dict[str, float]:
        """Apply metadata filters to scores"""
        filtered_scores = {}

        for doc_id, score in scores.items():
            doc = self.documents[doc_id]
            metadata = doc["metadata"]

            # Check all filters
            match = True
            for key, value in filters.items():
                if key not in metadata or metadata[key] != value:
                    match = False
                    break

            if match:
                filtered_scores[doc_id] = score

        return filtered_scores

    def _get_highlights(self, content: str, tokens: List[str]) -> List[str]:
        """Get highlighted snippets from content"""
        highlights = []
        content_lower = content.lower()

        for token in tokens:
            if token in self.stopwords:
                continue

            # Find token in content
            start = content_lower.find(token)
            if start != -1:
                # Extract snippet around token
                snippet_start = max(0, start - 50)
                snippet_end = min(len(content), start + len(token) + 50)
                snippet = content[snippet_start:snippet_end]

                # Add ellipsis
                if snippet_start > 0:
                    snippet = "..." + snippet
                if snippet_end < len(content):
                    snippet = snippet + "..."

                highlights.append(snippet)

        return highlights[:3]  # Max 3 highlights

    def semantic_search(
        self,
        query: str,
        limit: int = 10
    ) -> List[SearchResult]:
        """Semantic search using keyword expansion"""
        # Simple semantic expansion (in production, use word embeddings)
        expansions = {
            'fast': ['quick', 'rapid', 'speedy'],
            'slow': ['sluggish', 'delayed'],
            'error': ['bug', 'issue', 'problem', 'fault'],
            'fix': ['repair', 'resolve', 'correct'],
            'hızlı': ['çabuk', 'süratli'],
            'yavaş': ['ağır', 'gecikmeli'],
            'hata': ['sorun', 'problem', 'bug'],
        }

        # Expand query
        expanded_tokens = self._tokenize(query)
        for token in expanded_tokens[:]:
            if token in expansions:
                expanded_tokens.extend(expansions[token])

        # Search with expanded query
        expanded_query = ' '.join(expanded_tokens)
        return self.search(expanded_query, limit=limit)

    def suggest(self, partial_query: str, limit: int = 5) -> List[str]:
        """Auto-suggest based on partial query"""
        suggestions = []

        # Find matching indexed terms
        for token in self.index.keys():
            if token.startswith(partial_query.lower()):
                suggestions.append(token)

        # Sort by frequency
        suggestions.sort(key=lambda t: sum(self.index[t].values()), reverse=True)

        return suggestions[:limit]

    def get_popular_queries(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Get most popular search queries"""
        query_counts = Counter([q.query for q in self.search_history])
        return query_counts.most_common(limit)

    def build_query(
        self,
        must_have: Optional[List[str]] = None,
        should_have: Optional[List[str]] = None,
        must_not_have: Optional[List[str]] = None
    ) -> str:
        """Build a boolean query from components"""
        parts = []

        if must_have:
            parts.append(' AND '.join(must_have))

        if should_have:
            if parts:
                parts.append(' OR ')
            parts.append(' OR '.join(should_have))

        if must_not_have:
            parts.append(' NOT ' + ' NOT '.join(must_not_have))

        return ''.join(parts)

    def delete_document(self, doc_id: str):
        """Remove document from index"""
        if doc_id in self.documents:
            # Remove from inverted index
            for token in self.index:
                if doc_id in self.index[token]:
                    del self.index[token][doc_id]

            # Remove document
            del self.documents[doc_id]
            logger.info(f"Deleted document: {doc_id}")

    def reindex_all(self):
        """Rebuild entire index"""
        # Clear index
        self.index.clear()

        # Reindex all documents
        for doc_id, doc in list(self.documents.items()):
            self.index_document(
                doc_id,
                doc["title"],
                doc["content"],
                doc["metadata"]
            )

        logger.info(f"Reindexed {len(self.documents)} documents")

    def export_index(self, file_path: str):
        """Export index to file"""
        data = {
            "documents": self.documents,
            "index": {k: dict(v) for k, v in self.index.items()}
        }

        with open(file_path, 'w') as f:
            json.dump(data, f)

        logger.info(f"Exported index to {file_path}")

    def import_index(self, file_path: str):
        """Import index from file"""
        with open(file_path, 'r') as f:
            data = json.load(f)

        self.documents = data["documents"]
        self.index = defaultdict(lambda: defaultdict(float))

        for token, docs in data["index"].items():
            for doc_id, score in docs.items():
                self.index[token][doc_id] = score

        logger.info(f"Imported index from {file_path}")

    def get_summary(self) -> Dict[str, Any]:
        """Get search engine summary"""
        return {
            "total_documents": len(self.documents),
            "total_terms": len(self.index),
            "total_searches": len(self.search_history),
            "average_doc_size": sum(len(d["content"]) for d in self.documents.values()) / len(self.documents) if self.documents else 0
        }


# Global instance
_search_engine: Optional[SearchEngine] = None


def get_search_engine() -> SearchEngine:
    """Get or create global search engine instance"""
    global _search_engine
    if _search_engine is None:
        _search_engine = SearchEngine()
    return _search_engine
