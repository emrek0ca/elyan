from __future__ import annotations

import time
from typing import Any

from config.elyan_config import elyan_config

from .memory import PersonalMemoryStore


def _tokenize(text: str) -> set[str]:
    return {part.strip().lower() for part in str(text or "").replace("\n", " ").split() if part.strip()}


class MemoryIndexer:
    def __init__(self, store: PersonalMemoryStore):
        self.store = store

    def index_interaction(self, **kwargs: Any) -> dict[str, Any]:
        return self.store.write_interaction(**kwargs)


class MemoryReranker:
    def rerank(self, candidates: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        query_tokens = _tokenize(query)
        ranked: list[dict[str, Any]] = []
        for row in list(candidates or []):
            merged = dict(row)
            haystack = " ".join(
                [
                    str(row.get("user_input") or ""),
                    str(row.get("assistant_output") or ""),
                    str(row.get("action") or ""),
                    str(row.get("intent") or ""),
                ]
            )
            overlap = len(query_tokens & _tokenize(haystack))
            base_score = float(row.get("score", 0.0) or 0.0)
            merged["rerank_score"] = round(base_score + (overlap * 0.05), 6)
            ranked.append(merged)
        ranked.sort(key=lambda item: (-float(item.get("rerank_score", 0.0)), -float(item.get("created_at", 0.0) or 0.0)))
        return ranked


class MemoryRetriever:
    def __init__(self, store: PersonalMemoryStore, reranker: MemoryReranker | None = None):
        self.store = store
        self.reranker = reranker or MemoryReranker()

    def retrieve(self, query: str, user_id: str, budget: int, *, k: int = 5) -> dict[str, Any]:
        result = self.store.retrieve_context(user_id, query, k=k, token_budget=budget)
        retrieval_cfg = dict(elyan_config.get("retrieval", {}) or {})
        stale_window_days = int(retrieval_cfg.get("stale_window_days", 30) or 30)
        rerank_top_k = max(1, int(retrieval_cfg.get("rerank_top_k", k) or k))
        hits = list(result.get("vector_hits") or [])
        if stale_window_days > 0:
            cutoff = time.time() - float(stale_window_days * 86400)
            fresh_hits = [row for row in hits if float(row.get("created_at", 0.0) or 0.0) >= cutoff]
            if fresh_hits:
                hits = fresh_hits
        result["vector_hits"] = self.reranker.rerank(hits[: max(k, rerank_top_k)], query)[:k]
        return result
