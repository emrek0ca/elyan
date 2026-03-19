"""Local document RAG engine for Elyan.

This module provides:
- recursive text splitting with chunk overlap
- persistent SQLite metadata and chunk storage
- optional FAISS-backed vector search with numpy fallback
- semantic reranking via the existing SemanticRetriever
- extractive + optional abstractive summarization
- source-grounded question answering with citations and hallucination guard

It is intentionally dependency-safe. If optional ML packages are missing, the
engine falls back to deterministic local hashing embeddings and lexical
ranking/summarization.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from core.embedding_codec import deserialize_embedding, serialize_embedding
from core.model_manager import LocalHashingEmbedder, get_model_manager
from core.storage_paths import resolve_elyan_data_dir
from tools.research_tools.semantic_retrieval import SemanticRetriever
from utils.logger import get_logger

logger = get_logger("research.document_rag")

DEFAULT_EMBEDDING_MODEL = os.getenv("ELYAN_RAG_EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
DEFAULT_CHUNK_TOKENS = max(128, int(os.getenv("ELYAN_RAG_CHUNK_TOKENS", "512")))
DEFAULT_CHUNK_OVERLAP = max(0, int(os.getenv("ELYAN_RAG_CHUNK_OVERLAP", "72")))
DEFAULT_CONTEXT_CHARS = max(4096, int(os.getenv("ELYAN_RAG_CONTEXT_CHARS", "12000")))
DEFAULT_STORAGE_DIR = (resolve_elyan_data_dir() / "rag").resolve()
DEFAULT_SUMMARY_SOURCES = 6
DEFAULT_SEARCH_TOP_K = 5

_TOKEN_RE = re.compile(r"[A-Za-z0-9ğüşöçıİĞÜŞÖÇ]+", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|(?:\r?\n)+")
_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+.+|[A-ZÇĞİÖŞÜ0-9][A-ZÇĞİÖŞÜ0-9 \-_]{4,}|(?:[A-Za-zÇĞİÖŞÜ0-9][\w\s\-/]{1,70}):)$"
)

_STOPWORDS = {
    "ve",
    "ile",
    "bir",
    "bu",
    "için",
    "olan",
    "de",
    "da",
    "the",
    "and",
    "is",
    "of",
    "to",
    "in",
    "a",
    "veya",
    "daha",
    "çok",
    "gibi",
    "ama",
    "fakat",
    "hem",
    "şu",
    "o",
    "mi",
    "mı",
    "mu",
    "mü",
    "neden",
    "nasıl",
    "ne",
    "hangi",
    "içinde",
    "üzerinde",
    "olarak",
}

_POSITIVE_WORDS = {
    "iyi",
    "güçlü",
    "yararlı",
    "başarılı",
    "olumlu",
    "verimli",
    "sağlam",
    "hızlı",
    "yüksek",
    "gelişmiş",
    "doğru",
    "faydalı",
    "güvenilir",
}

_NEGATIVE_WORDS = {
    "kötü",
    "zayıf",
    "hata",
    "sorun",
    "risk",
    "eksik",
    "belirsiz",
    "yavaş",
    "başarısız",
    "uyumsuz",
    "yanlış",
    "saçma",
    "çelişkili",
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(_normalize_text(text))]


def _word_list(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(_normalize_text(text))]


def _token_count(text: str) -> int:
    return max(0, len(_tokenize(text)))


def _split_sentences(text: str) -> list[str]:
    raw = [part.strip() for part in _SENTENCE_RE.split(_normalize_text(text)) if part and part.strip()]
    if raw:
        return raw
    fallback = [part.strip() for part in re.split(r"[;•\n]", _normalize_text(text)) if part and part.strip()]
    return fallback or ([str(text).strip()] if str(text or "").strip() else [])


def _is_heading_line(text: str) -> bool:
    candidate = _normalize_text(text)
    if not candidate:
        return False
    if candidate.startswith("#"):
        return True
    if len(candidate) > 80:
        return False
    return bool(_HEADING_RE.match(candidate))


def _safe_text_excerpt(text: str, limit: int = 280) -> str:
    clean = _normalize_text(text)
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"


def _strip_research_annotation(text: str) -> str:
    clean = _normalize_text(text)
    if not clean:
        return ""
    clean = re.sub(r"^\s*[•\-\u2022]+\s*", "", clean)
    clean = re.sub(r"\s*\((?:Kaynak|Source|Ref|Güven|Guven|Confidence)\s*:\s*[^)]*\)\s*$", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s*\[(?:Kaynak|Source|Ref)[^\]]*\]\s*$", "", clean, flags=re.IGNORECASE)
    return _normalize_text(clean)


def _strip_research_meta_lines(text: str) -> str:
    clean = _normalize_text(text)
    if not clean:
        return ""
    lines = []
    for line in re.split(r"\r?\n", clean):
        lowered = line.strip().lower()
        if not lowered:
            continue
        if lowered.startswith("operasyonel öneriler"):
            continue
        if lowered.startswith("önerilen devam adımı"):
            continue
        if lowered.startswith("metodoloji"):
            continue
        if lowered.startswith("kaynak matrisi"):
            continue
        lines.append(line.strip())
    return " ".join(lines).strip()


def _sentence_vectors(sentences: Sequence[str]) -> np.ndarray:
    if not sentences:
        return np.zeros((0, 0), dtype=np.float32)
    embedder = LocalHashingEmbedder()
    vectors = embedder.encode(list(sentences), convert_to_numpy=True, normalize_embeddings=True)
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim == 1:
        vectors = vectors.reshape(1, -1)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return (vectors / norms).astype(np.float32, copy=False)


def _ordered_unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = _normalize_text(item)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0:
        return 0.0
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0.0:
        return 0.0
    return float(np.dot(left, right) / denom)


def _pagerank(similarity: np.ndarray, *, damping: float = 0.85, iterations: int = 30) -> np.ndarray:
    if similarity.size == 0:
        return np.array([], dtype=np.float32)
    matrix = similarity.astype(np.float32, copy=True)
    np.fill_diagonal(matrix, 0.0)
    row_sums = matrix.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0.0] = 1.0
    transition = matrix / row_sums
    scores = np.ones(matrix.shape[0], dtype=np.float32) / max(1, matrix.shape[0])
    teleport = np.ones(matrix.shape[0], dtype=np.float32) / max(1, matrix.shape[0])
    for _ in range(max(1, iterations)):
        scores = (1.0 - damping) * teleport + damping * transition.T @ scores
        total = float(scores.sum())
        if total > 0.0:
            scores /= total
    return scores


def _topic_terms(topic: str) -> list[str]:
    tokens = [token for token in _tokenize(topic) if len(token) >= 3]
    return _ordered_unique(tokens)


def _topic_overlap_score(topic: str, text: str) -> float:
    topic_terms = set(_topic_terms(topic))
    if not topic_terms:
        return 0.0
    tokens = set(_tokenize(text))
    if not tokens:
        return 0.0
    return len(topic_terms & tokens) / max(len(topic_terms), 1)


def _sentence_frequency_score(sentences: list[str]) -> list[float]:
    token_counts: Counter[str] = Counter()
    tokenized: list[list[str]] = []
    for sentence in sentences:
        tokens = [token for token in _tokenize(sentence) if len(token) >= 3 and token not in _STOPWORDS]
        tokenized.append(tokens)
        token_counts.update(tokens)

    scores: list[float] = []
    for idx, tokens in enumerate(tokenized):
        if not tokens:
            scores.append(0.0)
            continue
        base = sum(token_counts[token] for token in tokens) / len(tokens)
        position_bonus = 1.0 / (1.0 + idx)
        scores.append(float(base) + position_bonus)
    return scores


def _text_hash(text: str) -> str:
    return hashlib.sha1(_normalize_text(text).encode("utf-8")).hexdigest()


def _document_hash(*parts: str) -> str:
    joined = "\n".join(_normalize_text(part) for part in parts if _normalize_text(part))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _split_long_sentence(sentence: str, *, max_tokens: int, overlap_tokens: int) -> list[str]:
    words = _word_list(sentence)
    if not words:
        return []
    if len(words) <= max_tokens:
        return [sentence.strip()]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + max_tokens)
        part = " ".join(words[start:end]).strip()
        if part:
            chunks.append(part)
        if end >= len(words):
            break
        start = max(end - overlap_tokens, start + 1)
    return chunks


def split_text_recursive(text: str, *, max_tokens: int = DEFAULT_CHUNK_TOKENS, overlap_tokens: int = DEFAULT_CHUNK_OVERLAP) -> list[dict[str, Any]]:
    """Split text recursively by headings, paragraphs, sentences, then token windows."""
    clean_text = _normalize_text(text)
    if not clean_text:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", clean_text) if part and part.strip()]
    chunks: list[dict[str, Any]] = []
    current_section = ""
    current_words: list[str] = []
    current_para_words: list[str] = []
    chunk_start = 0
    chunk_index = 0

    def _flush_current() -> None:
        nonlocal current_words, chunk_index, chunk_start
        if not current_words:
            return
        chunk_text = " ".join(current_words).strip()
        if chunk_text:
            chunks.append(
                {
                    "chunk_index": chunk_index,
                    "section": current_section,
                    "text": chunk_text,
                    "token_count": len(current_words),
                    "char_count": len(chunk_text),
                    "start_char": chunk_start,
                    "end_char": chunk_start + len(chunk_text),
                }
            )
            chunk_index += 1
            chunk_start += len(chunk_text)
        current_words = []

    def _append_words(words: list[str]) -> None:
        nonlocal current_words, chunk_start
        if not words:
            return
        if not current_words:
            current_words = list(words)
            return
        if len(current_words) + len(words) <= max_tokens:
            current_words.extend(words)
            return
        # Flush current chunk and keep an overlap window.
        previous = list(current_words)
        _flush_current()
        if overlap_tokens > 0 and previous:
            allowed_overlap = max(0, max_tokens - len(words))
            overlap_size = min(overlap_tokens, allowed_overlap, len(previous))
            current_words = previous[-overlap_size:] if overlap_size > 0 else []
        else:
            current_words = []
        if len(words) > max_tokens:
            # Split oversized unit recursively.
            for part in _split_long_sentence(" ".join(words), max_tokens=max_tokens, overlap_tokens=overlap_tokens):
                _append_words(_word_list(part))
            return
        current_words.extend(words)

    for paragraph in paragraphs:
        if _is_heading_line(paragraph):
            _flush_current()
            current_section = _normalize_text(paragraph).lstrip("#").strip()
            continue

        para_words = _word_list(paragraph)
        if not para_words:
            continue

        if len(para_words) <= max_tokens:
            _append_words(para_words)
            continue

        _flush_current()
        sentence_parts = _split_sentences(paragraph)
        for sentence in sentence_parts:
            sentence_words = _word_list(sentence)
            if not sentence_words:
                continue
            if len(sentence_words) > max_tokens:
                for part in _split_long_sentence(sentence, max_tokens=max_tokens, overlap_tokens=overlap_tokens):
                    _append_words(_word_list(part))
            else:
                _append_words(sentence_words)
        _flush_current()

    _flush_current()

    # Recompute token counts / offsets cleanly.
    normalized: list[dict[str, Any]] = []
    cursor = 0
    for chunk in chunks:
        text_chunk = _normalize_text(chunk.get("text"))
        if not text_chunk:
            continue
        token_count = _token_count(text_chunk)
        normalized.append(
            {
                "chunk_index": len(normalized),
                "section": _normalize_text(chunk.get("section")),
                "text": text_chunk,
                "token_count": token_count,
                "char_count": len(text_chunk),
                "start_char": cursor,
                "end_char": cursor + len(text_chunk),
            }
        )
        cursor += len(text_chunk) + 1
    return normalized


def _pick_summary_sentences(sentences: list[str], *, topic: str = "", max_sentences: int = 5) -> list[str]:
    clean_sentences = _ordered_unique(sentences)
    if not clean_sentences:
        return []
    if len(clean_sentences) <= max_sentences:
        return clean_sentences[:]

    frequency_scores = _sentence_frequency_score(clean_sentences)
    topic_scores = [_topic_overlap_score(topic, sentence) for sentence in clean_sentences] if topic else [0.0] * len(clean_sentences)

    try:
        vectors = _sentence_vectors(clean_sentences)
        if vectors.size > 0:
            similarity = np.matmul(vectors, vectors.T)
            pagerank = _pagerank(similarity)
        else:
            pagerank = np.array([], dtype=np.float32)
    except Exception:
        pagerank = np.array([], dtype=np.float32)

    combined_scores: list[float] = []
    for idx, sentence in enumerate(clean_sentences):
        score = float(frequency_scores[idx])
        score += float(topic_scores[idx]) * 2.0
        score += 0.25 if idx < 2 else 0.0
        if pagerank.size == len(clean_sentences):
            score += float(pagerank[idx]) * 3.0
        combined_scores.append(score)

    ranked = sorted(range(len(clean_sentences)), key=lambda i: combined_scores[i], reverse=True)
    chosen = sorted(ranked[:max_sentences])
    return [clean_sentences[idx] for idx in chosen]


def _extract_key_topics(text: str, *, limit: int = 8) -> list[str]:
    tokens = [token for token in _tokenize(text) if len(token) >= 4 and token not in _STOPWORDS]
    if not tokens:
        return []
    counts = Counter(tokens)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _ in ranked[:limit]]


def _sentiment_score(text: str) -> dict[str, Any]:
    tokens = _tokenize(text)
    if not tokens:
        return {"label": "neutral", "score": 0.0}
    positive = sum(1 for token in tokens if token in _POSITIVE_WORDS)
    negative = sum(1 for token in tokens if token in _NEGATIVE_WORDS)
    score = (positive - negative) / max(len(tokens), 1)
    label = "neutral"
    if score > 0.01:
        label = "positive"
    elif score < -0.01:
        label = "negative"
    return {"label": label, "score": round(score, 4), "positive_hits": positive, "negative_hits": negative}


def _format_bullet_list(items: Sequence[str]) -> str:
    lines = [f"- {_normalize_text(item)}" for item in items if _normalize_text(item)]
    return "\n".join(lines)


def build_research_narrative(
    topic: str,
    findings: list[str] | None = None,
    sources: list[dict[str, Any]] | None = None,
    *,
    brief: str = "",
    summary: str = "",
    include_bibliography: bool = True,
    max_paragraphs: int = 7,
) -> list[str]:
    """Create a narrative research body from findings/sources.

    This is used by the research delivery flow to keep Word/PDF/Markdown output
    full and readable even when an LLM is unavailable or returns a thin draft.
    """

    clean_topic = _normalize_text(topic) or "Araştırma"
    clean_findings = _ordered_unique(_strip_research_annotation(f) for f in list(findings or []))
    clean_sources = [src for src in list(sources or []) if isinstance(src, dict)]

    narrative: list[str] = []
    intro = _strip_research_meta_lines(_extract_summary_seed(summary, clean_findings, clean_topic))
    if not intro:
        intro = f"{clean_topic} konusu için doğrulanmış bulgular bir araya getirilerek okunabilir bir araştırma metni oluşturuldu."
    narrative.append(intro)

    if brief and _normalize_text(brief) not in _normalize_text(intro):
        narrative.append(f"İstenen odağa göre belge şu çerçevede hazırlandı: {brief}.")

    if clean_findings:
        narrative.append(
            f"Bu çalışmada {len(clean_findings)} ana bulgu değerlendirildi ve tekrarlayan ifadeler ayıklanarak konuya doğrudan değinen noktalar seçildi."
        )
        selected = _pick_summary_sentences(clean_findings, topic=clean_topic, max_sentences=min(max_paragraphs, 5))
        intro_norm = _normalize_text(intro)
        if intro_norm:
            selected = [
                sentence
                for sentence in selected
                if _normalize_text(sentence) != intro_norm and _normalize_text(sentence) not in intro_norm
            ]
        if selected:
            grouped: list[str] = []
            for idx in range(0, len(selected), 2):
                chunk = selected[idx : idx + 2]
                grouped.append(" ".join(chunk))
            narrative.extend(grouped[: max(2, min(4, len(grouped)))])
    else:
        narrative.append("Doğrudan kullanılabilir bulgu sınırlı kaldığı için konuya genel bir çerçeve sunuluyor.")

    if clean_sources:
        high_quality = [src for src in clean_sources if _safe_float(src.get("reliability_score", 0.0)) >= 0.7]
        source_count = len(clean_sources)
        reliability_ratio = len(high_quality) / max(source_count, 1)
        narrative.append(
            f"Kaynak setinde {source_count} referans yer aldı; bunların yaklaşık %{round(reliability_ratio * 100)}'u yüksek güvenilirlik eşiklerini geçti."
        )

        source_lines: list[str] = []
        for idx, src in enumerate(clean_sources[:6], start=1):
            title = _normalize_text(src.get("title") or src.get("name") or "Kaynak")
            url = _normalize_text(src.get("url"))
            rel = _safe_float(src.get("reliability_score", 0.0))
            line = f"{idx}. {title}"
            if url:
                line += f" — {url}"
            line += f" (güven: {rel:.2f})"
            source_lines.append(line)
        if include_bibliography and source_lines:
            narrative.append("Kaynakça:\n" + _format_bullet_list(source_lines))
    else:
        narrative.append("Kaynakça sınırlı olduğundan bulgu odaklı anlatım tercih edildi.")

    conclusion = (
        f"Sonuç olarak {clean_topic.lower()} başlığı, temel kavramsal çerçevesi, kullanım bağlamı ve destekleyici referanslarıyla birlikte düzenli bir belge yapısına oturtuldu."
    )
    if clean_findings:
        conclusion += " Metin, tekrar eden cümlelerden arındırılarak kullanıcıya doğrudan karar verebileceği bir özet sunacak şekilde kurgulandı."
    narrative.append(conclusion)

    if len(narrative) > max_paragraphs:
        narrative = narrative[:max_paragraphs]
    return [paragraph.strip() for paragraph in narrative if paragraph and paragraph.strip()]


def _extract_summary_seed(summary: str, findings: list[str], topic: str) -> str:
    clean_summary = _normalize_text(summary)
    if clean_summary:
        return clean_summary
    if findings:
        selected = _pick_summary_sentences(findings, topic=topic, max_sentences=3)
        if selected:
            return " ".join(selected)
    return ""


def _sectioned_summary_from_paragraphs(
    *,
    title: str,
    paragraphs: list[str],
    highlights: list[str],
    citations: list[dict[str, Any]],
    style: str,
    summary_kind: str,
) -> dict[str, Any]:
    sectioned = [
        {
            "title": "Kısa Özet",
            "paragraphs": [{"text": paragraph, "claim_ids": []} for paragraph in paragraphs[:2] if _normalize_text(paragraph)],
        }
    ]
    if highlights:
        sectioned.append(
            {
                "title": "Temel Noktalar",
                "paragraphs": [{"text": point, "claim_ids": []} for point in highlights if _normalize_text(point)],
            }
        )
    if citations:
        sectioned.append(
            {
                "title": "Kaynak Notu",
                "paragraphs": [{"text": _citation_line(citation), "claim_ids": []} for citation in citations[:6]],
            }
        )
    return {
        "title": title,
        "sections": sectioned,
        "style": style,
        "summary_kind": summary_kind,
    }


def _citation_line(citation: dict[str, Any]) -> str:
    title = _normalize_text(citation.get("source_name") or citation.get("title") or "Kaynak")
    path = _normalize_text(citation.get("source_path") or citation.get("url") or "")
    score = _safe_float(citation.get("score", 0.0))
    line = f"{title}"
    if path:
        line += f" — {path}"
    line += f" (skor: {score:.2f})"
    return line


@dataclass(slots=True)
class DocumentChunkRecord:
    chunk_id: int | None
    document_id: str
    source_name: str
    source_path: str
    chunk_index: int
    section: str
    text: str
    token_count: int
    char_count: int
    start_char: int
    end_char: int
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.embedding is not None:
            payload["embedding"] = list(self.embedding)
        return payload


@dataclass(slots=True)
class RetrievedChunk:
    citation_id: str
    chunk_id: int
    document_id: str
    source_name: str
    source_path: str
    chunk_index: int
    section: str
    text: str
    score: float
    token_count: int
    char_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RAGSummaryResult:
    success: bool
    title: str
    summary: str
    style: str
    summary_kind: str
    source_name: str
    source_path: str = ""
    original_length: int = 0
    summary_length: int = 0
    source_count: int = 0
    chunk_count: int = 0
    highlights: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    key_topics: list[str] = field(default_factory=list)
    quality_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    answer: str = ""
    confidence: float = 0.0
    answer_mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DocumentRAGEngine:
    """Local document store + retrieval engine."""

    def __init__(
        self,
        storage_dir: str | Path | None = None,
        *,
        embedding_model_name: str | None = None,
        chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        context_chars: int = DEFAULT_CONTEXT_CHARS,
        allow_remote_models: bool | None = None,
    ) -> None:
        self.storage_dir = Path(storage_dir or DEFAULT_STORAGE_DIR).expanduser().resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "document_rag.db"
        self.index_path = self.storage_dir / "document_rag.faiss"
        self.matrix_path = self.storage_dir / "document_rag.npz"
        self.embedding_model_name = embedding_model_name or DEFAULT_EMBEDDING_MODEL
        self.chunk_tokens = int(chunk_tokens)
        self.chunk_overlap = int(chunk_overlap)
        self.context_chars = int(context_chars)
        self.allow_remote_models = bool(
            allow_remote_models if allow_remote_models is not None else not bool(os.getenv("ELYAN_RAG_OFFLINE"))
        )
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._index_lock = asyncio.Lock()
        self._embedder: Any | None = None
        self._embedder_name: str = ""
        self._semantic_retriever = SemanticRetriever()
        self._chunk_cache: list[dict[str, Any]] = []
        self._embedding_matrix: np.ndarray = np.zeros((0, 0), dtype=np.float32)
        self._matrix_ids: list[int] = []
        self._vector_dim: int = 0
        self._faiss = None
        self._faiss_index: Any | None = None
        self._faiss_available = False
        self._cache_loaded = False
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    title TEXT,
                    metadata_json TEXT,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    char_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    source_path TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    section TEXT,
                    text TEXT NOT NULL,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    char_count INTEGER NOT NULL DEFAULT 0,
                    start_char INTEGER NOT NULL DEFAULT 0,
                    end_char INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT,
                    embedding_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, chunk_index)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_path)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_path)")

    async def _get_embedder(self) -> Any:
        if self._embedder is not None:
            return self._embedder
        async with self._index_lock:
            if self._embedder is not None:
                return self._embedder
            if self.allow_remote_models and self.embedding_model_name:
                try:
                    manager = get_model_manager()
                    self._embedder = await manager.get_embedding_model(self.embedding_model_name)
                    self._embedder_name = self.embedding_model_name
                    logger.info("document_rag_embedder_loaded:%s", self.embedding_model_name)
                    return self._embedder
                except Exception as exc:
                    logger.debug("document_rag_remote_embedder_failed:%s", exc)
            try:
                self._embedder = await get_model_manager().get_embedding_model()
                self._embedder_name = getattr(self._embedder, "model_name", "shared_embedder")
            except Exception as exc:
                logger.debug("document_rag_shared_embedder_failed:%s", exc)
                self._embedder = LocalHashingEmbedder()
                self._embedder_name = "local-hashing-embedder"
            return self._embedder

    def _prefix_text(self, text: str, *, kind: str) -> str:
        normalized = _normalize_text(text)
        if not normalized:
            return ""
        model_name = (self._embedder_name or self.embedding_model_name or "").lower()
        if "e5" in model_name or "bge" in model_name:
            prefix = "query: " if kind == "query" else "passage: "
            return prefix + normalized
        return normalized

    async def _embed_texts(self, texts: Sequence[str], *, kind: str) -> np.ndarray:
        cleaned = [_normalize_text(text) for text in texts if _normalize_text(text)]
        if not cleaned:
            return np.zeros((0, 0), dtype=np.float32)
        embedder = await self._get_embedder()
        prefixed = [self._prefix_text(text, kind=kind) for text in cleaned]
        try:
            vectors = embedder.encode(prefixed, convert_to_numpy=True, normalize_embeddings=True)
        except TypeError:
            vectors = embedder.encode(prefixed)
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        if vectors.size == 0:
            return np.zeros((0, 0), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        vectors = vectors / norms
        return vectors.astype(np.float32, copy=False)

    def _rebuild_cache_from_db(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT c.*, d.source_type, d.content_hash
            FROM chunks c
            JOIN documents d ON d.document_id = c.document_id
            ORDER BY c.id ASC
            """
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self._chunk_cache = rows
        self._matrix_ids = []
        vectors: list[np.ndarray] = []
        for row in rows:
            embedding = deserialize_embedding(row.get("embedding_json"))
            if embedding is None:
                continue
            vector = np.asarray(embedding, dtype=np.float32)
            if vector.ndim != 1:
                continue
            norm = float(np.linalg.norm(vector))
            if norm > 0.0:
                vector = vector / norm
            vectors.append(vector.astype(np.float32, copy=False))
            self._matrix_ids.append(_safe_int(row.get("id"), 0))
        if vectors:
            self._embedding_matrix = np.vstack(vectors).astype(np.float32, copy=False)
            self._vector_dim = int(self._embedding_matrix.shape[1])
        else:
            self._embedding_matrix = np.zeros((0, 0), dtype=np.float32)
            self._vector_dim = 0
        self._cache_loaded = True
        self._faiss_index = None
        self._faiss_available = False
        self._load_optional_faiss_index()

    def _load_optional_faiss_index(self) -> None:
        try:
            import faiss  # type: ignore
        except Exception:
            self._faiss = None
            self._faiss_available = False
            return

        self._faiss = faiss
        if self._embedding_matrix.size == 0:
            self._faiss_index = None
            self._faiss_available = False
            return

        if self.index_path.exists():
            try:
                self._faiss_index = faiss.read_index(str(self.index_path))
                self._faiss_available = True
                return
            except Exception as exc:
                logger.debug("document_rag_faiss_load_failed:%s", exc)

        dim = int(self._embedding_matrix.shape[1])
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        ids = np.asarray(self._matrix_ids, dtype=np.int64)
        vectors = self._embedding_matrix.astype(np.float32, copy=False)
        if len(ids) == len(vectors) and len(vectors) > 0:
            index.add_with_ids(vectors, ids)
            self._faiss_index = index
            self._faiss_available = True
            try:
                faiss.write_index(index, str(self.index_path))
            except Exception as exc:
                logger.debug("document_rag_faiss_write_failed:%s", exc)
        else:
            self._faiss_index = None
            self._faiss_available = False

    def _ensure_cache_loaded(self) -> None:
        if not self._cache_loaded:
            self._rebuild_cache_from_db()

    def _delete_document_rows(self, document_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            self._conn.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))

    async def _load_document_text(self, path: str) -> tuple[str, dict[str, Any], str]:
        file_path = Path(path).expanduser().resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Dosya bulunamadı: {file_path}")
        ext = file_path.suffix.lower()
        source_type = ext.lstrip(".") or "text"
        warnings: list[str] = []
        content = ""

        if ext in {".docx", ".doc"}:
            from tools.office_tools.word_tools import read_word

            result = await read_word(str(file_path), max_chars=50000)
            if not result.get("success"):
                raise RuntimeError(str(result.get("error") or "Word dosyası okunamadı"))
            content = str(result.get("content") or "")
            source_type = "docx"
        elif ext in {".xlsx", ".xls"}:
            from tools.office_tools.excel_tools import read_excel

            result = await read_excel(str(file_path), use_pandas=True, max_rows=1000)
            if not result.get("success"):
                raise RuntimeError(str(result.get("error") or "Excel dosyası okunamadı"))
            data = result.get("data")
            if isinstance(data, dict):
                sections: list[str] = []
                for sheet, rows in data.items():
                    sections.append(f"[Sheet: {sheet}]")
                    if isinstance(rows, list):
                        for row in rows[:500]:
                            if isinstance(row, dict):
                                sections.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
                            elif isinstance(row, (list, tuple)):
                                sections.append(" | ".join(str(v) for v in row))
                            else:
                                sections.append(str(row))
                content = "\n".join(sections)
            elif isinstance(data, list):
                lines: list[str] = []
                for row in data[:1000]:
                    if isinstance(row, dict):
                        lines.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
                    elif isinstance(row, (list, tuple)):
                        lines.append(" | ".join(str(v) for v in row))
                    else:
                        lines.append(str(row))
                content = "\n".join(lines)
            else:
                content = str(result.get("summary") or result.get("content") or "")
            source_type = "xlsx"
        elif ext == ".pdf":
            from tools.office_tools.pdf_tools import read_pdf

            result = await read_pdf(str(file_path), extract_tables=True, use_ocr=False)
            if not result.get("success"):
                raise RuntimeError(str(result.get("error") or "PDF dosyası okunamadı"))
            content = str(result.get("content") or "")
            tables = result.get("tables") or []
            if tables:
                table_lines = []
                for table in tables[:20]:
                    if not isinstance(table, dict):
                        continue
                    page = table.get("page")
                    rows = table.get("data") or []
                    table_lines.append(f"[Table page={page}]")
                    for row in rows[:60]:
                        if isinstance(row, list):
                            table_lines.append(" | ".join(str(cell) for cell in row))
                if table_lines:
                    content += "\n\n" + "\n".join(table_lines)
            source_type = "pdf"
        elif ext in {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".html", ".htm", ".xml", ".log"}:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            source_type = ext.lstrip(".")
        else:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:
                warnings.append(f"unknown_format:{exc}")
                content = ""

        return _normalize_text(content), {"warnings": warnings, "path": str(file_path)}, source_type

    async def ingest_text(
        self,
        text: str,
        *,
        source_name: str = "metin",
        source_path: str = "",
        title: str = "",
        metadata: dict[str, Any] | None = None,
        refresh: bool = True,
    ) -> dict[str, Any]:
        clean_text = _normalize_text(text)
        if len(clean_text) < 50:
            return {"success": False, "error": "İçerik çok kısa", "source_name": source_name}

        doc_hash = _document_hash(source_name, source_path, clean_text, json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True))
        document_id = f"doc_{doc_hash[:20]}"
        created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        source_type = "text"
        title = _normalize_text(title) or source_name

        with self._conn:
            existing = None
            cursor = self._conn.execute(
                "SELECT document_id, content_hash FROM documents WHERE source_path = ? ORDER BY updated_at DESC LIMIT 1",
                (source_path or source_name,),
            )
            row = cursor.fetchone()
            if row is not None:
                existing = dict(row)
            if existing and existing.get("content_hash") == doc_hash and not refresh:
                self._ensure_cache_loaded()
                return {
                    "success": True,
                    "cache_hit": True,
                    "document_id": existing.get("document_id"),
                    "source_name": source_name,
                    "source_path": source_path,
                    "chunk_count": sum(1 for chunk in self._chunk_cache if chunk.get("document_id") == existing.get("document_id")),
                    "content_hash": doc_hash,
                }
            if existing:
                self._delete_document_rows(str(existing.get("document_id") or ""))

        chunks = split_text_recursive(clean_text, max_tokens=self.chunk_tokens, overlap_tokens=self.chunk_overlap)
        if not chunks:
            return {"success": False, "error": "Chunk üretilemedi", "source_name": source_name}

        embed_vectors = await self._embed_texts([chunk["text"] for chunk in chunks], kind="passage")
        if embed_vectors.size == 0:
            embed_vectors = np.zeros((len(chunks), 0), dtype=np.float32)

        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO documents (
                    document_id, source_path, source_name, source_type, content_hash,
                    title, metadata_json, token_count, char_count, chunk_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    source_path or source_name,
                    source_name,
                    source_type,
                    doc_hash,
                    title,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    _token_count(clean_text),
                    len(clean_text),
                    len(chunks),
                    created_at,
                    created_at,
                ),
            )
            inserted_chunk_ids: list[int] = []
            for idx, chunk in enumerate(chunks):
                vector = None
                if embed_vectors.size and idx < len(embed_vectors):
                    vector = embed_vectors[idx].astype(float).tolist()
                cursor = self._conn.execute(
                    """
                    INSERT INTO chunks (
                        document_id, chunk_index, source_path, source_name, section, text,
                        token_count, char_count, start_char, end_char, metadata_json,
                        embedding_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        int(chunk.get("chunk_index", idx)),
                        source_path or source_name,
                        source_name,
                        _normalize_text(chunk.get("section")),
                        _normalize_text(chunk.get("text")),
                        _safe_int(chunk.get("token_count"), _token_count(chunk.get("text", ""))),
                        _safe_int(chunk.get("char_count"), len(str(chunk.get("text") or ""))),
                        _safe_int(chunk.get("start_char"), 0),
                        _safe_int(chunk.get("end_char"), 0),
                        json.dumps(metadata or {}, ensure_ascii=False),
                        serialize_embedding(vector) if vector is not None else "",
                        created_at,
                    ),
                )
                inserted_chunk_ids.append(int(cursor.lastrowid))

        self._rebuild_cache_from_db()
        return {
            "success": True,
            "cache_hit": False,
            "document_id": document_id,
            "source_name": source_name,
            "source_path": source_path or source_name,
            "title": title,
            "chunk_count": len(chunks),
            "token_count": _token_count(clean_text),
            "content_length": len(clean_text),
            "content_hash": doc_hash,
            "chunk_ids": inserted_chunk_ids,
        }

    async def ingest_document(
        self,
        path: str,
        *,
        title: str = "",
        metadata: dict[str, Any] | None = None,
        refresh: bool = True,
    ) -> dict[str, Any]:
        try:
            text, extra, source_type = await self._load_document_text(path)
            if not text:
                return {"success": False, "error": "İçerik okunamadı", "path": path}
            merged_metadata = dict(metadata or {})
            merged_metadata.update(extra or {})
            merged_metadata["source_type"] = source_type
            source_path = str(Path(path).expanduser().resolve())
            source_name = Path(source_path).name
            return await self.ingest_text(
                text,
                source_name=source_name,
                source_path=source_path,
                title=title or source_name,
                metadata=merged_metadata,
                refresh=refresh,
            )
        except Exception as exc:
            logger.error("document_rag_ingest_failed:%s", exc)
            return {"success": False, "error": str(exc), "path": path}

    def _candidate_rows(self, *, source_paths: Sequence[str] | None = None, document_ids: Sequence[str] | None = None) -> list[dict[str, Any]]:
        self._ensure_cache_loaded()
        rows = list(self._chunk_cache)
        if source_paths:
            normalized_paths = {str(Path(path).expanduser().resolve()) for path in source_paths if str(path).strip()}
            rows = [row for row in rows if str(row.get("source_path") or "").strip() in normalized_paths]
        if document_ids:
            ids = {str(item).strip() for item in document_ids if str(item).strip()}
            rows = [row for row in rows if str(row.get("document_id") or "").strip() in ids]
        return rows

    async def search(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_SEARCH_TOP_K,
        source_paths: Sequence[str] | None = None,
        document_ids: Sequence[str] | None = None,
        candidate_pool: int | None = None,
    ) -> dict[str, Any]:
        clean_query = _normalize_text(query)
        if not clean_query:
            return {"success": False, "error": "Sorgu boş"}

        candidate_rows = self._candidate_rows(source_paths=source_paths, document_ids=document_ids)
        if not candidate_rows:
            return {"success": True, "query": clean_query, "results": [], "source_count": 0}

        candidate_pool = candidate_pool or max(12, top_k * 6)
        candidate_pool = min(candidate_pool, len(candidate_rows))

        query_vector = await self._embed_texts([clean_query], kind="query")
        query_vector = query_vector[0] if query_vector.size else np.zeros(0, dtype=np.float32)

        matrix = self._embedding_matrix if self._embedding_matrix.size else np.zeros((0, 0), dtype=np.float32)
        candidate_rows_by_id = {int(row["id"]): row for row in candidate_rows if row.get("id") is not None}
        ranked_candidates: list[tuple[float, dict[str, Any]]] = []

        if matrix.size and query_vector.size and self._matrix_ids:
            similarities: list[tuple[float, int]] = []
            for idx, chunk_id in enumerate(self._matrix_ids):
                row = candidate_rows_by_id.get(int(chunk_id))
                if row is None:
                    continue
                vector = matrix[idx]
                sim = _cosine_similarity(query_vector, vector)
                text = str(row.get("text") or "")
                sim = max(sim, _topic_overlap_score(clean_query, text))
                similarities.append((sim, int(chunk_id)))
            similarities.sort(key=lambda item: item[0], reverse=True)
            for score, chunk_id in similarities[:candidate_pool]:
                row = candidate_rows_by_id.get(int(chunk_id))
                if row is not None:
                    ranked_candidates.append((float(score), row))
        else:
            lexical_scores = []
            for row in candidate_rows:
                text = str(row.get("text") or "")
                score = _topic_overlap_score(clean_query, text)
                if not score:
                    score = len(set(_tokenize(clean_query)) & set(_tokenize(text))) / max(len(_tokenize(clean_query)) or 1, 1)
                lexical_scores.append((float(score), row))
            lexical_scores.sort(key=lambda item: item[0], reverse=True)
            ranked_candidates.extend(lexical_scores[:candidate_pool])

        if not ranked_candidates:
            return {"success": True, "query": clean_query, "results": [], "source_count": 0}

        candidate_texts = [str(row.get("text") or "") for _, row in ranked_candidates]
        try:
            reranked = self._semantic_retriever.rank_passages(clean_query, candidate_texts, top_k=min(top_k, len(candidate_texts)), candidate_pool=len(candidate_texts))
        except Exception:
            reranked = []

        final_rows: list[RetrievedChunk] = []
        if reranked:
            text_to_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for score, row in ranked_candidates:
                text_to_rows[_normalize_text(row.get("text") or "")].append(row)
            for idx, item in enumerate(reranked, start=1):
                rows = text_to_rows.get(_normalize_text(item.text), [])
                if rows:
                    row = rows.pop(0)
                    final_rows.append(
                        RetrievedChunk(
                            citation_id=f"S{idx}",
                            chunk_id=int(row["id"]),
                            document_id=str(row.get("document_id") or ""),
                            source_name=str(row.get("source_name") or ""),
                            source_path=str(row.get("source_path") or ""),
                            chunk_index=_safe_int(row.get("chunk_index"), 0),
                            section=_normalize_text(row.get("section")),
                            text=str(row.get("text") or ""),
                            score=float(item.score),
                            token_count=_safe_int(row.get("token_count"), _token_count(str(row.get("text") or ""))),
                            char_count=_safe_int(row.get("char_count"), len(str(row.get("text") or ""))),
                            metadata=json.loads(row.get("metadata_json") or "{}"),
                        )
                    )
        else:
            for idx, (_, row) in enumerate(ranked_candidates[:top_k], start=1):
                final_rows.append(
                    RetrievedChunk(
                        citation_id=f"S{idx}",
                        chunk_id=int(row["id"]),
                        document_id=str(row.get("document_id") or ""),
                        source_name=str(row.get("source_name") or ""),
                        source_path=str(row.get("source_path") or ""),
                        chunk_index=_safe_int(row.get("chunk_index"), 0),
                        section=_normalize_text(row.get("section")),
                        text=str(row.get("text") or ""),
                        score=float(ranked_candidates[idx - 1][0]),
                        token_count=_safe_int(row.get("token_count"), _token_count(str(row.get("text") or ""))),
                        char_count=_safe_int(row.get("char_count"), len(str(row.get("text") or ""))),
                        metadata=json.loads(row.get("metadata_json") or "{}"),
                    )
                )

        return {
            "success": True,
            "query": clean_query,
            "results": [row.to_dict() for row in final_rows[:top_k]],
            "source_count": len(final_rows[:top_k]),
            "candidate_pool": len(ranked_candidates),
        }

    def _build_context(self, query: str, hits: Sequence[RetrievedChunk], *, max_chars: int | None = None) -> tuple[str, list[dict[str, Any]]]:
        max_chars = max_chars or self.context_chars
        lines: list[str] = []
        citations: list[dict[str, Any]] = []
        total_chars = 0
        for hit in hits:
            citation_line = (
                f"[{hit.citation_id}] {hit.source_name}"
                f"{' | ' + hit.section if hit.section else ''}"
                f" (score={hit.score:.2f})"
            )
            snippet = _safe_text_excerpt(hit.text, limit=600)
            block = f"{citation_line}\n{snippet}"
            if total_chars + len(block) > max_chars and lines:
                break
            lines.append(block)
            total_chars += len(block)
            citations.append(
                {
                    "citation_id": hit.citation_id,
                    "chunk_id": hit.chunk_id,
                    "document_id": hit.document_id,
                    "source_name": hit.source_name,
                    "source_path": hit.source_path,
                    "chunk_index": hit.chunk_index,
                    "section": hit.section,
                    "score": hit.score,
                    "snippet": snippet,
                }
            )
        context = "\n\n".join(lines).strip()
        return context, citations

    def _fallback_answer(self, query: str, hits: Sequence[RetrievedChunk], *, language: str = "tr") -> tuple[str, float]:
        if not hits:
            return ("Yeterli belge kanıtı bulunamadı.", 0.0)
        top_hits = list(hits[:4])
        answer_lines = []
        answer_lines.append("Kısa cevap: Belgedeki kanıtlara göre aşağıdaki noktalar öne çıkıyor.")
        for hit in top_hits:
            excerpt = _safe_text_excerpt(hit.text, limit=260)
            answer_lines.append(f"- [{hit.citation_id}] {excerpt}")
        answer_lines.append("")
        answer_lines.append("Daha fazla ayrıntı istersen belgeyi daha uzun, kaynak etiketli bir sürüme genişletebilirim.")
        confidence = min(0.95, 0.35 + (statistics.fmean([hit.score for hit in top_hits]) if top_hits else 0.0) * 0.5 + len(top_hits) * 0.05)
        return ("\n".join(answer_lines).strip(), round(confidence, 3))

    async def answer_question(
        self,
        question: str,
        *,
        path: str | None = None,
        text: str | None = None,
        paths: Sequence[str] | None = None,
        top_k: int = DEFAULT_SEARCH_TOP_K,
        language: str = "tr",
        use_llm: bool = False,
    ) -> dict[str, Any]:
        clean_question = _normalize_text(question)
        if not clean_question:
            return {"success": False, "error": "Soru boş"}

        source_paths: list[str] = [str(Path(path).expanduser().resolve())] if path else []
        if paths:
            source_paths.extend(str(Path(item).expanduser().resolve()) for item in paths if str(item or "").strip())

        if path:
            ingest = await self.ingest_document(path)
            if not ingest.get("success"):
                return ingest
        elif text is not None:
            ingest = await self.ingest_text(text, source_name="metin", source_path="metin", title="metin")
            if not ingest.get("success"):
                return ingest

        search_result = await self.search(clean_question, top_k=top_k, source_paths=source_paths or None)
        if not search_result.get("success"):
            return search_result

        hits = [RetrievedChunk(**item) for item in search_result.get("results", [])]
        context, citations = self._build_context(clean_question, hits)

        answer_text = ""
        answer_mode = "extractive"
        confidence = 0.0
        if use_llm and context:
            try:
                from core.llm_client import LLMClient

                llm = LLMClient()
                prompt = (
                    "Aşağıdaki belge bağlamını kullanarak soruya cevap ver.\n"
                    "Kurallar:\n"
                    "- Sadece verilen bağlamı kullan.\n"
                    "- Bilgi eksikse bunu açıkça söyle.\n"
                    "- Her önemli iddiadan sonra [S1], [S2] gibi atıf ekle.\n"
                    "- Uydurma, genel geçer veya dış kaynaklı bilgi ekleme.\n"
                    "- Yanıtı kısa ama yeterince açıklayıcı tut.\n"
                    "- Sonunda 'Daha fazla ayrıntı istersen genişletebilirim.' cümlesini ekle.\n\n"
                    f"Soru: {clean_question}\n\n"
                    f"Bağlam:\n{context}"
                )
                response = await llm.generate(
                    prompt,
                    role="analysis",
                    system_prompt="Sen belge tabanlı soru-cevap asistanısın. Sadece verilen bağlamı kullan.",
                    temperature=0.15,
                    disable_collaboration=True,
                )
                candidate = _normalize_text(response)
                if candidate and any(citation["citation_id"] in candidate for citation in citations):
                    answer_text = candidate
                    answer_mode = "llm"
                    confidence = min(0.98, 0.55 + len(citations) * 0.08)
                else:
                    logger.debug("document_rag_llm_answer_rejected")
            except Exception as exc:
                logger.debug("document_rag_llm_answer_failed:%s", exc)

        if not answer_text:
            answer_text, confidence = self._fallback_answer(clean_question, hits, language=language)

        answer_text = answer_text.strip()
        if citations and not any(citation["citation_id"] in answer_text for citation in citations):
            answer_text = f"{answer_text}\n\nKaynaklar:\n" + "\n".join(f"[{c['citation_id']}] {c['source_name']} — {c['snippet']}" for c in citations[:5])

        return {
            "success": True,
            "question": clean_question,
            "answer": answer_text,
            "answer_mode": answer_mode,
            "confidence": round(confidence, 3),
            "citations": citations,
            "source_count": len(citations),
            "context": context,
            "hallucination_guard": "citations_required",
            "source_paths": [citation["source_path"] for citation in citations],
        }

    def _summarize_sentences(self, sentences: list[str], *, topic: str = "", max_sentences: int = 5) -> tuple[list[str], list[float]]:
        clean_sentences = _ordered_unique(sentences)
        if not clean_sentences:
            return [], []
        if len(clean_sentences) <= max_sentences:
            scores = [1.0 - (idx * 0.01) for idx in range(len(clean_sentences))]
            return clean_sentences, scores

        query_bias = [_topic_overlap_score(topic, sentence) if topic else 0.0 for sentence in clean_sentences]
        frequency_scores = _sentence_frequency_score(clean_sentences)
        try:
            vectors = _sentence_vectors(clean_sentences)
            if vectors.size > 0:
                similarity = np.matmul(vectors, vectors.T)
                page_rank = _pagerank(similarity)
            else:
                page_rank = np.array([], dtype=np.float32)
        except Exception:
            page_rank = np.array([], dtype=np.float32)

        combined_scores: list[float] = []
        for idx, sentence in enumerate(clean_sentences):
            score = float(frequency_scores[idx]) * 0.55
            score += float(query_bias[idx]) * 1.2
            if idx < 2:
                score += 0.2
            if page_rank.size == len(clean_sentences):
                score += float(page_rank[idx]) * 2.5
            combined_scores.append(score)

        ranked = sorted(range(len(clean_sentences)), key=lambda i: combined_scores[i], reverse=True)
        selected = sorted(ranked[:max_sentences])
        return [clean_sentences[idx] for idx in selected], [combined_scores[idx] for idx in selected]

    async def summarize_text(
        self,
        text: str,
        *,
        title: str = "Metin Özeti",
        source_name: str = "metin",
        style: str = "brief",
        topic: str = "",
        include_bibliography: bool = False,
    ) -> dict[str, Any]:
        clean_text = _normalize_text(text)
        if len(clean_text) < 50:
            return {"success": False, "error": "Özetlenecek içerik yetersiz", "source_name": source_name}

        sentences = _split_sentences(clean_text)
        if len(sentences) > 40 or len(clean_text) > 12000:
            chunks = split_text_recursive(clean_text, max_tokens=self.chunk_tokens, overlap_tokens=self.chunk_overlap)
            chunk_summaries: list[str] = []
            for chunk in chunks[:8]:
                summary_chunk = await self._summarize_small_text(
                    chunk["text"],
                    title=title,
                    topic=topic or title,
                    style="bullets",
                    include_bibliography=False,
                    source_name=source_name,
                )
                if summary_chunk:
                    chunk_summaries.append(summary_chunk)
            merged = "\n\n".join(chunk_summaries) if chunk_summaries else clean_text
            sentences = _split_sentences(merged)
            style = "detailed" if style == "brief" else style

        selected_sentences, scores = self._summarize_sentences(sentences, topic=topic or title, max_sentences=5 if style != "brief" else 3)
        if not selected_sentences:
            return {"success": False, "error": "Özet çıkarılamadı", "source_name": source_name}

        key_topics = _extract_key_topics(clean_text, limit=8)
        source_preview = source_name if source_name else title

        if style == "bullets":
            summary_text = _format_bullet_list(selected_sentences[:5])
        elif style == "detailed":
            intro = selected_sentences[0]
            detail = " ".join(selected_sentences[1:4]) if len(selected_sentences) > 1 else ""
            summary_text = "\n\n".join(
                part
                for part in [
                    intro,
                    detail,
                    "Temel Noktalar:\n" + _format_bullet_list(selected_sentences[:5]),
                ]
                if _normalize_text(part)
            )
        else:
            summary_text = "\n\n".join(
                part
                for part in [
                    "Kısa Özet:\n" + " ".join(selected_sentences[:2]),
                    "Temel Noktalar:\n" + _format_bullet_list(selected_sentences[:4]),
                ]
                if _normalize_text(part)
            )

        citations = [
            {
                "citation_id": f"S{idx + 1}",
                "source_name": source_preview,
                "source_path": "",
                "chunk_id": idx + 1,
                "chunk_index": idx,
                "section": "",
                "score": round(float(score), 4),
                "snippet": _safe_text_excerpt(sentence, 240),
            }
            for idx, (sentence, score) in enumerate(zip(selected_sentences, scores))
        ]
        section_bundle = _sectioned_summary_from_paragraphs(
            title=title,
            paragraphs=[summary_text] if summary_text else selected_sentences,
            highlights=selected_sentences[:5],
            citations=citations,
            style=style,
            summary_kind="extractive" if len(clean_text) < 12000 else "hybrid",
        )

        # Optional lightweight abstractive refinement if enabled and dependencies are present.
        abstractive_summary = ""
        if os.getenv("ELYAN_RAG_ENABLE_MT5", "").strip().lower() in {"1", "true", "yes"}:
            abstractive_summary = await self._try_mt5_refine("\n".join(selected_sentences), max_length=220)
        if abstractive_summary:
            summary_text = f"{summary_text}\n\nAbstraktif Özet:\n{abstractive_summary}"

        return RAGSummaryResult(
            success=True,
            title=title,
            summary=summary_text.strip(),
            style=style,
            summary_kind=section_bundle["summary_kind"],
            source_name=source_preview,
            source_path="",
            original_length=len(clean_text),
            summary_length=len(summary_text.strip()),
            source_count=len(citations),
            chunk_count=len(sentences),
            highlights=selected_sentences[:5],
            citations=citations,
            sections=section_bundle["sections"],
            key_topics=key_topics,
            quality_summary={
                "status": "pass" if len(selected_sentences) >= 2 else "partial",
                "coverage": round(len(selected_sentences) / max(len(sentences), 1), 3),
                "topic_count": len(key_topics),
            },
            warnings=[],
            analysis={
                "source_preview": source_preview,
                "style": style,
                "summary_kind": section_bundle["summary_kind"],
            },
        ).to_dict()

    async def _summarize_small_text(
        self,
        text: str,
        *,
        title: str = "Metin",
        topic: str = "",
        style: str = "brief",
        include_bibliography: bool = False,
        source_name: str = "metin",
    ) -> str:
        result = await self.summarize_text(
            text,
            title=title,
            source_name=source_name,
            style=style,
            topic=topic,
            include_bibliography=include_bibliography,
        )
        if not result.get("success"):
            return ""
        summary = str(result.get("summary") or "").strip()
        return summary

    async def summarize_document(
        self,
        path: str,
        *,
        style: str = "brief",
        question: str | None = None,
        include_bibliography: bool = False,
    ) -> dict[str, Any]:
        ingest = await self.ingest_document(path)
        if not ingest.get("success"):
            return ingest
        text, _, _ = await self._load_document_text(path)
        source_name = Path(path).expanduser().resolve().name
        if question:
            return await self.answer_question(
                question,
                path=path,
                top_k=DEFAULT_SEARCH_TOP_K,
            )
        summary = await self.summarize_text(
            text,
            title=source_name,
            source_name=source_name,
            style=style,
            topic=source_name,
            include_bibliography=include_bibliography,
        )
        summary["source_path"] = str(Path(path).expanduser().resolve())
        summary["document_id"] = ingest.get("document_id")
        return summary

    async def analyze_document(
        self,
        path: str,
        *,
        analysis_type: str = "comprehensive",
        extract_metadata: bool = True,
    ) -> dict[str, Any]:
        ingest = await self.ingest_document(path)
        if not ingest.get("success"):
            return ingest

        text, extra, source_type = await self._load_document_text(path)
        summary_result = await self.summarize_document(path, style="detailed")
        if not summary_result.get("success"):
            return summary_result

        metadata: dict[str, Any] = {}
        if extract_metadata:
            file_path = Path(path).expanduser().resolve()
            stat = file_path.stat()
            metadata = {
                "size": stat.st_size,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_ctime)),
                "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
                "extension": file_path.suffix,
                "name": file_path.name,
                "source_type": source_type,
            }
            metadata.update(extra or {})

        key_topics = _extract_key_topics(text, limit=10)
        sentiment = _sentiment_score(text)
        top_hits = await self.search(summary_result.get("summary", text[:500]), top_k=min(5, ingest.get("chunk_count", 5)))
        citations = top_hits.get("results", []) if isinstance(top_hits, dict) else []
        structure = {
            "chunk_count": ingest.get("chunk_count", 0),
            "sentence_count": len(_split_sentences(text)),
            "paragraph_count": len([part for part in re.split(r"\n\s*\n", text) if part.strip()]),
        }

        analysis = {
            "analysis_type": analysis_type,
            "summary": summary_result.get("summary", ""),
            "key_points": summary_result.get("highlights", []),
            "key_topics": key_topics,
            "sentiment": sentiment,
            "structure": structure,
            "citations": citations,
            "quality_summary": summary_result.get("quality_summary", {}),
            "source_count": summary_result.get("source_count", 0),
            "chunk_count": summary_result.get("chunk_count", 0),
        }

        if analysis_type == "topics":
            analysis["analysis_focus"] = "topical"
        elif analysis_type == "sentiment":
            analysis["analysis_focus"] = "sentiment"
        else:
            analysis["analysis_focus"] = "comprehensive"

        return {
            "success": True,
            "file_path": str(Path(path).expanduser().resolve()),
            "analysis_type": analysis_type,
            "metadata": metadata,
            "analysis": analysis,
            "content_length": len(text),
            "rag_summary": summary_result.get("summary", ""),
            "citations": summary_result.get("citations", []),
            "source_count": summary_result.get("source_count", 0),
            "chunk_count": summary_result.get("chunk_count", 0),
        }

    async def reindex(self) -> dict[str, Any]:
        self._rebuild_cache_from_db()
        return {
            "success": True,
            "document_count": len({row.get("document_id") for row in self._chunk_cache}),
            "chunk_count": len(self._chunk_cache),
            "vector_dimension": self._vector_dim,
            "backend": "faiss" if self._faiss_available else "numpy",
        }

    async def _try_mt5_refine(self, text: str, *, max_length: int = 220) -> str:
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except Exception as exc:
            logger.debug("document_rag_mt5_unavailable:%s", exc)
            return ""

        model_name = os.getenv("ELYAN_RAG_MT5_MODEL", "google/mt5-small")
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        except Exception as exc:
            logger.debug("document_rag_mt5_load_failed:%s", exc)
            return ""

        prompt = _normalize_text(text)
        if not prompt:
            return ""

        inputs = tokenizer(prompt[:4096], return_tensors="pt", truncation=True, max_length=1024)
        try:
            outputs = model.generate(
                **inputs,
                max_length=max_length,
                min_length=min(80, max(20, len(prompt.split()) // 4)),
                num_beams=4,
                length_penalty=1.0,
                no_repeat_ngram_size=3,
                early_stopping=True,
            )
            summary = tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
            return _normalize_text(summary)
        except Exception as exc:
            logger.debug("document_rag_mt5_generate_failed:%s", exc)
            return ""


_ENGINE: DocumentRAGEngine | None = None


def get_document_rag_engine(storage_dir: str | Path | None = None) -> DocumentRAGEngine:
    global _ENGINE
    if storage_dir is not None:
        return DocumentRAGEngine(storage_dir=storage_dir)
    if _ENGINE is None:
        _ENGINE = DocumentRAGEngine()
    return _ENGINE


async def build_document_rag_index(
    paths: Sequence[str],
    *,
    storage_dir: str | Path | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    engine = get_document_rag_engine(storage_dir)
    results = []
    for path in paths:
        if not str(path or "").strip():
            continue
        results.append(await engine.ingest_document(path, refresh=refresh))
    return {
        "success": all(item.get("success") for item in results) if results else False,
        "results": results,
        "indexed_count": sum(1 for item in results if item.get("success")),
        "failed_count": sum(1 for item in results if not item.get("success")),
        "backend": "faiss" if engine._faiss_available else "numpy",
    }


async def document_rag_qa(
    *,
    path: str | None = None,
    text: str | None = None,
    paths: Sequence[str] | None = None,
    question: str,
    top_k: int = DEFAULT_SEARCH_TOP_K,
    storage_dir: str | Path | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    engine = get_document_rag_engine(storage_dir)
    if path:
        return await engine.answer_question(question, path=path, top_k=top_k, use_llm=use_llm)
    if text is not None:
        return await engine.answer_question(question, text=text, top_k=top_k, use_llm=use_llm)
    if paths:
        return await engine.answer_question(question, paths=paths, top_k=top_k, use_llm=use_llm)
    return await engine.answer_question(question, top_k=top_k, use_llm=use_llm)


async def summarize_document_rag(
    *,
    path: str | None = None,
    text: str | None = None,
    style: str = "brief",
    title: str = "",
    question: str | None = None,
    storage_dir: str | Path | None = None,
    include_bibliography: bool = False,
) -> dict[str, Any]:
    engine = get_document_rag_engine(storage_dir)
    if path:
        result = await engine.summarize_document(path, style=style, question=question, include_bibliography=include_bibliography)
        return result
    if text is not None:
        result = await engine.summarize_text(
            text,
            title=title or "Metin Özeti",
            source_name=title or "metin",
            style=style,
            topic=title or "metin",
            include_bibliography=include_bibliography,
        )
        if question:
            result = await engine.answer_question(question, text=text, top_k=DEFAULT_SEARCH_TOP_K, use_llm=True)
        return result
    return {"success": False, "error": "path veya text gerekli"}


async def analyze_document_rag(
    path: str,
    *,
    analysis_type: str = "comprehensive",
    extract_metadata: bool = True,
    storage_dir: str | Path | None = None,
) -> dict[str, Any]:
    engine = get_document_rag_engine(storage_dir)
    return await engine.analyze_document(path, analysis_type=analysis_type, extract_metadata=extract_metadata)


__all__ = [
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_CHUNK_TOKENS",
    "DEFAULT_CONTEXT_CHARS",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_SEARCH_TOP_K",
    "DocumentChunkRecord",
    "DocumentRAGEngine",
    "RAGSummaryResult",
    "RetrievedChunk",
    "analyze_document_rag",
    "build_document_rag_index",
    "build_research_narrative",
    "document_rag_qa",
    "get_document_rag_engine",
    "split_text_recursive",
    "summarize_document_rag",
]
