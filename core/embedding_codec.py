"""Canonical embedding codec for consistent memory storage."""

from __future__ import annotations

import json
from typing import Any


def normalize_embedding(value: Any) -> list[float] | None:
    """
    Normalize embedding payload into list[float].

    Supported inputs:
    - list/tuple of numbers
    - JSON string representing number list
    - dict containing one of: embedding/vector/values
    """
    if value is None:
        return None

    if isinstance(value, dict):
        for key in ("embedding", "vector", "values"):
            if key in value:
                value = value[key]
                break

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        parsed = json.loads(text)
        return normalize_embedding(parsed)

    if isinstance(value, tuple):
        value = list(value)

    if not isinstance(value, list):
        raise TypeError("Embedding must be list/tuple/JSON string or dict with embedding key")

    normalized: list[float] = []
    for item in value:
        if item is None:
            raise ValueError("Embedding cannot contain null values")
        normalized.append(float(item))

    return normalized


def serialize_embedding(value: Any) -> str:
    """Serialize embedding to canonical JSON string."""
    normalized = normalize_embedding(value)
    if normalized is None:
        raise ValueError("Embedding is empty")
    return json.dumps(normalized, separators=(",", ":"))


def deserialize_embedding(value: Any) -> list[float] | None:
    """Deserialize canonical embedding representation."""
    return normalize_embedding(value)
