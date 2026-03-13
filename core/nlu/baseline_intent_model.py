from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


def _normalize_tr(text: str) -> str:
    table = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return str(text or "").translate(table).lower()


def _tokenize(text: str) -> List[str]:
    low = _normalize_tr(text)
    return [tok for tok in re.findall(r"[a-z0-9_]+", low) if tok]


class NaiveBayesIntentModel:
    def __init__(self) -> None:
        self.class_doc_count: Dict[str, int] = {}
        self.class_token_count: Dict[str, int] = {}
        self.token_count_by_class: Dict[str, Dict[str, int]] = {}
        self.vocab_size: int = 0
        self.total_docs: int = 0
        self.labels: List[str] = []

    def fit(self, texts: List[str], labels: List[str]) -> "NaiveBayesIntentModel":
        if len(texts) != len(labels):
            raise ValueError("texts/labels length mismatch")
        self.class_doc_count = defaultdict(int)
        self.class_token_count = defaultdict(int)
        token_by_class: Dict[str, Counter] = defaultdict(Counter)
        vocab: set[str] = set()

        for text, label in zip(texts, labels):
            label_key = str(label or "").strip().lower()
            if not label_key:
                continue
            tokens = _tokenize(str(text or ""))
            self.class_doc_count[label_key] += 1
            self.class_token_count[label_key] += len(tokens)
            token_by_class[label_key].update(tokens)
            vocab.update(tokens)

        self.token_count_by_class = {k: dict(v) for k, v in token_by_class.items()}
        self.vocab_size = max(1, len(vocab))
        self.total_docs = int(sum(self.class_doc_count.values()))
        self.labels = sorted(self.class_doc_count.keys())
        return self

    def predict_proba(self, text: str) -> Dict[str, float]:
        if not self.labels:
            return {}
        tokens = _tokenize(text)
        if self.total_docs <= 0:
            return {}

        log_probs: Dict[str, float] = {}
        for label in self.labels:
            doc_count = self.class_doc_count.get(label, 0)
            if doc_count <= 0:
                continue
            prior = math.log(doc_count / self.total_docs)
            token_counts = self.token_count_by_class.get(label, {})
            token_total = max(1, self.class_token_count.get(label, 0))
            score = prior
            for tok in tokens:
                count = token_counts.get(tok, 0)
                # Laplace smoothing.
                score += math.log((count + 1) / (token_total + self.vocab_size))
            log_probs[label] = score

        if not log_probs:
            return {}
        best = max(log_probs.values())
        exp_scores = {k: math.exp(v - best) for k, v in log_probs.items()}
        denom = sum(exp_scores.values()) or 1.0
        return {k: (v / denom) for k, v in exp_scores.items()}

    def predict(self, text: str) -> Tuple[str, float]:
        probs = self.predict_proba(text)
        if not probs:
            return "", 0.0
        label, score = max(probs.items(), key=lambda x: x[1])
        return label, float(score)

    def save(self, path: Path) -> Path:
        payload = {
            "class_doc_count": self.class_doc_count,
            "class_token_count": self.class_token_count,
            "token_count_by_class": self.token_count_by_class,
            "vocab_size": self.vocab_size,
            "total_docs": self.total_docs,
            "labels": self.labels,
        }
        out = Path(path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    @classmethod
    def load(cls, path: Path) -> "NaiveBayesIntentModel":
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        model = cls()
        model.class_doc_count = {str(k): int(v) for k, v in dict(payload.get("class_doc_count") or {}).items()}
        model.class_token_count = {str(k): int(v) for k, v in dict(payload.get("class_token_count") or {}).items()}
        model.token_count_by_class = {
            str(label): {str(tok): int(count) for tok, count in dict(counts or {}).items()}
            for label, counts in dict(payload.get("token_count_by_class") or {}).items()
        }
        model.vocab_size = int(payload.get("vocab_size") or 1)
        model.total_docs = int(payload.get("total_docs") or 0)
        model.labels = [str(x) for x in list(payload.get("labels") or []) if str(x).strip()]
        return model


__all__ = ["NaiveBayesIntentModel"]
