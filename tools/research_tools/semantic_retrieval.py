"""Semantic retrieval with optional embedding models and lexical fallback."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from utils.logger import get_logger

logger = get_logger("research.semantic")


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-ZğüşöçıİĞÜŞÖÇ0-9]+", _normalize_text(text).lower())


def _term_weights(tokens: list[str]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for token in tokens:
        if len(token) < 3:
            continue
        weights[token] = weights.get(token, 0.0) + 1.0
    return weights


def _cosine_sparse(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(left.get(token, 0.0) * right.get(token, 0.0) for token in set(left) & set(right))
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _char_overlap_score(query: str, passage: str) -> float:
    q_terms = set(_tokenize(query))
    p_terms = set(_tokenize(passage))
    if not q_terms or not p_terms:
        return 0.0
    return len(q_terms & p_terms) / max(len(q_terms), 1)


@dataclass
class RankedPassage:
    text: str
    score: float
    stage: str


class SemanticRetriever:
    """Hybrid retrieval: embeddings when available, lexical fallback otherwise."""

    def __init__(
        self,
        *,
        bi_encoder_name: str = "BAAI/bge-m3",
        cross_encoder_name: str = "BAAI/bge-reranker-v2-m3",
    ) -> None:
        self.bi_encoder_name = bi_encoder_name
        self.cross_encoder_name = cross_encoder_name
        self._bi_encoder = None
        self._cross_encoder = None
        self._model_error = ""

    @property
    def available(self) -> bool:
        self._ensure_models_loaded()
        return self._bi_encoder is not None and self._cross_encoder is not None

    def _ensure_models_loaded(self) -> None:
        if self._bi_encoder is not None and self._cross_encoder is not None:
            return
        if self._model_error:
            return
        try:
            from sentence_transformers import CrossEncoder, SentenceTransformer

            self._bi_encoder = SentenceTransformer(self.bi_encoder_name)
            self._cross_encoder = CrossEncoder(self.cross_encoder_name)
        except Exception as exc:  # pragma: no cover - dependency dependent
            self._bi_encoder = None
            self._cross_encoder = None
            self._model_error = str(exc)
            logger.debug("semantic_models_unavailable: %s", exc)

    @staticmethod
    @lru_cache(maxsize=2048)
    def _lexical_vector(cache_key: str, text: str) -> dict[str, float]:
        _ = cache_key
        return _term_weights(_tokenize(text))

    def _lexical_rank(
        self,
        query: str,
        passages: list[str],
        *,
        top_k: int,
        candidate_pool: int,
    ) -> list[RankedPassage]:
        query_vec = self._lexical_vector(hashlib.sha1(query.encode("utf-8")).hexdigest(), query)
        ranked: list[RankedPassage] = []
        for passage in passages:
            p_vec = self._lexical_vector(hashlib.sha1(passage.encode("utf-8")).hexdigest(), passage)
            sparse_score = _cosine_sparse(query_vec, p_vec)
            overlap = _char_overlap_score(query, passage)
            score = (sparse_score * 0.75) + (overlap * 0.25)
            ranked.append(RankedPassage(text=passage, score=score, stage="lexical"))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[: max(1, min(top_k, candidate_pool, len(ranked)))]

    def rank_passages(
        self,
        query: str,
        passages: list[str],
        *,
        top_k: int = 15,
        candidate_pool: int = 50,
    ) -> list[RankedPassage]:
        clean_passages = []
        seen: set[str] = set()
        for passage in list(passages or []):
            clean = _normalize_text(passage)
            if not clean or clean in seen:
                continue
            seen.add(clean)
            clean_passages.append(clean)
        if not clean_passages:
            return []

        self._ensure_models_loaded()
        if not self.available:
            return self._lexical_rank(query, clean_passages, top_k=top_k, candidate_pool=candidate_pool)

        try:  # pragma: no cover - exercised only when dependency is installed
            query_vector = self._bi_encoder.encode([query], normalize_embeddings=True)
            passage_vectors = self._bi_encoder.encode(clean_passages, normalize_embeddings=True)
            dense_scores = []
            for index, passage in enumerate(clean_passages):
                vector = passage_vectors[index]
                score = 0.0
                try:
                    score = float(sum(float(a) * float(b) for a, b in zip(query_vector[0], vector)))
                except Exception:
                    score = _char_overlap_score(query, passage)
                dense_scores.append((score, passage))
            dense_scores.sort(key=lambda item: item[0], reverse=True)
            candidates = [passage for _, passage in dense_scores[: max(5, min(candidate_pool, len(dense_scores)))]]
            rerank_pairs = [[query, passage] for passage in candidates]
            rerank_scores = self._cross_encoder.predict(rerank_pairs)
            ranked = [
                RankedPassage(text=passage, score=float(score), stage="semantic")
                for passage, score in zip(candidates, rerank_scores)
            ]
            ranked.sort(key=lambda item: item.score, reverse=True)
            return ranked[: max(1, min(top_k, len(ranked)))]
        except Exception as exc:  # pragma: no cover - dependency dependent
            logger.debug("semantic_rerank_failed:%s", exc)
            return self._lexical_rank(query, clean_passages, top_k=top_k, candidate_pool=candidate_pool)


__all__ = ["RankedPassage", "SemanticRetriever"]
