"""İteratif bilgi getirme (RAG) orkestrasyonu — P3.

NEDEN
-----
Mevcut getirme tek atıştı: sorgu → getir → bitti. Kapsama yetersizse (ki
çok-parçalı sorularda sıklıkla yetersizdir) sistem bunu fark etmiyor, model
eksik kanıtla cevap üretiyordu. ``orchestration.lowConfidence`` sinyali zaten
üretiliyordu ama İKİNCİ bir tura bağlı değildi.

DÖNGÜ
-----
    ayrıştır → getir → YETERLİLİK KONTROLÜ → eksikse hedefli 2. tur → sırala

Yeterlilik kontrolü kanıta bakar (alt soruların kaçı karşılandı), model
özgüvenine değil. Böylece "kaynak buldum" ile "soruyu cevaplayan kaynak buldum"
ayrışır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

RETRIEVAL_CONTRACT = "elyan.retrieval_orchestrator.v1"

DEFAULT_MAX_ROUNDS = 2
DEFAULT_TARGET_RESULTS = 8
# Alt soruların bu oranı karşılanmazsa ikinci tur tetiklenir.
SUFFICIENCY_THRESHOLD = 0.6
_STOPWORDS = {
    "ve", "veya", "ile", "için", "icin", "bir", "bu", "şu", "su", "the", "and",
    "or", "of", "in", "to", "a", "an", "nedir", "nasıl", "nasil", "ne", "mi",
}


@dataclass(slots=True)
class RetrievedItem:
    text: str
    source: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text[:1_200], "source": self.source, "score": round(self.score, 3)}


@dataclass(slots=True)
class RetrievalOutcome:
    items: list[RetrievedItem]
    rounds_used: int
    sufficient: bool
    coverage: float
    sub_queries: list[str] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": RETRIEVAL_CONTRACT,
            "roundsUsed": self.rounds_used,
            "sufficient": self.sufficient,
            "coverage": round(self.coverage, 3),
            "subQueries": self.sub_queries,
            "unmet": self.unmet,
            "resultCount": len(self.items),
            "results": [item.to_dict() for item in self.items[:12]],
        }


def _tokens(text: str) -> set[str]:
    words = re.findall(r"\w+", str(text or "").lower())
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def decompose_query(query: str, *, limit: int = 4) -> list[str]:
    """Bileşik soruyu alt sorulara ayırır.

    Deterministik ve ucuzdur: bağlaç/noktalama sınırlarından böler. Amaç mükemmel
    ayrıştırma değil, KAPSAMA ÖLÇÜMÜ için ayrı bilgi taleplerini görünür kılmak.
    """
    raw = str(query or "").strip()
    if not raw:
        return []
    parts = re.split(r"\s*(?:\?|;|\bve\b|\bayrıca\b|\bayrica\b|\bbir de\b|,)\s*", raw)
    cleaned = [part.strip() for part in parts if len(part.strip()) > 8]
    unique: list[str] = []
    for part in cleaned:
        if part.lower() not in {item.lower() for item in unique}:
            unique.append(part)
    return unique[:limit] or [raw]


def assess_sufficiency(
    sub_queries: list[str],
    items: list[RetrievedItem],
) -> tuple[float, list[str]]:
    """Alt soruların kaçının kanıtla karşılandığını ölçer.

    Model özgüvenine değil, getirilen metinlerdeki terim örtüşmesine bakar.
    Döner: (kapsama oranı, karşılanmayan alt sorular)."""
    # KRİTİK: hiç kanıt yoksa kapsama SIFIRDIR. Aksi halde arama çöktüğünde
    # (ya da boş döndüğünde) sistem "yeterli kanıtım var" sanır ve model
    # kaynaksız cevap üretir — uydurma riskinin ta kendisi.
    if not items:
        return 0.0, list(sub_queries)
    if not sub_queries:
        return 1.0, []
    corpus = _tokens(" ".join(item.text for item in items))
    unmet: list[str] = []
    covered = 0
    for sub in sub_queries:
        needed = _tokens(sub)
        if not needed:
            covered += 1
            continue
        overlap = len(needed & corpus) / max(1, len(needed))
        if overlap >= 0.34:
            covered += 1
        else:
            unmet.append(sub)
    return covered / len(sub_queries), unmet


def rerank(items: list[RetrievedItem], query: str, *, limit: int) -> list[RetrievedItem]:
    """Sorgu terim örtüşmesi + özgün skoru harmanlayarak yeniden sıralar.

    Getirme motoru sıralamasına körü körüne güvenmek yerine, sorguya gerçekten
    değen belgeleri öne alır ve yinelenenleri düşürür."""
    query_tokens = _tokens(query)
    seen: set[str] = set()
    scored: list[tuple[float, RetrievedItem]] = []
    for item in items:
        fingerprint = item.text[:160].strip().lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        item_tokens = _tokens(item.text)
        overlap = len(query_tokens & item_tokens) / max(1, len(query_tokens))
        scored.append((overlap * 0.7 + float(item.score) * 0.3, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked: list[RetrievedItem] = []
    for blended, item in scored[:limit]:
        item.score = blended
        ranked.append(item)
    return ranked


def _coerce_items(value: Any) -> list[RetrievedItem]:
    if not isinstance(value, list):
        return []
    items: list[RetrievedItem] = []
    for entry in value[:40]:
        if isinstance(entry, str):
            if entry.strip():
                items.append(RetrievedItem(text=entry.strip()))
            continue
        if not isinstance(entry, dict):
            continue
        text = str(
            entry.get("text") or entry.get("snippet") or entry.get("content") or ""
        ).strip()
        if not text:
            continue
        try:
            score = float(entry.get("score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        items.append(
            RetrievedItem(
                text=text,
                source=str(entry.get("source") or entry.get("url") or "").strip(),
                score=score,
            )
        )
    return items


def retrieve_iteratively(
    query: str,
    *,
    search: Callable[[str], Any],
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    target_results: int = DEFAULT_TARGET_RESULTS,
) -> RetrievalOutcome:
    """Yeterli kanıt toplanana kadar (sınırlı turda) hedefli getirme yapar.

    1. tur: bütün sorgu. Yeterlilik düşükse 2. tur YALNIZ karşılanmayan alt
    sorular için çalışır — kör tekrar yerine hedefli tamamlama.
    """
    sub_queries = decompose_query(query)
    collected: list[RetrievedItem] = []
    rounds = 0
    bounded_rounds = max(1, min(int(max_rounds or DEFAULT_MAX_ROUNDS), 3))

    def run_search(text: str) -> None:
        try:
            collected.extend(_coerce_items(search(text)))
        except Exception:
            # Tek bir arama hatası tüm orkestrasyonu düşürmesin.
            pass

    rounds += 1
    run_search(query)
    coverage, unmet = assess_sufficiency(sub_queries, collected)

    while coverage < SUFFICIENCY_THRESHOLD and rounds < bounded_rounds and unmet:
        rounds += 1
        for sub in unmet[:3]:
            run_search(sub)
        coverage, unmet = assess_sufficiency(sub_queries, collected)

    ranked = rerank(collected, query, limit=max(1, int(target_results or DEFAULT_TARGET_RESULTS)))
    return RetrievalOutcome(
        items=ranked,
        rounds_used=rounds,
        sufficient=coverage >= SUFFICIENCY_THRESHOLD,
        coverage=coverage,
        sub_queries=sub_queries,
        unmet=unmet,
    )
