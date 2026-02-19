"""Unit tests for canonical embedding codec."""

import pytest

from core.embedding_codec import (
    deserialize_embedding,
    normalize_embedding,
    serialize_embedding,
)


def test_normalize_embedding_accepts_list_tuple_and_json():
    assert normalize_embedding([1, 2.5, "3"]) == [1.0, 2.5, 3.0]
    assert normalize_embedding((1, 2)) == [1.0, 2.0]
    assert normalize_embedding("[1,2,3]") == [1.0, 2.0, 3.0]


def test_normalize_embedding_accepts_dict_wrapped_value():
    assert normalize_embedding({"embedding": [0.1, 0.2]}) == [0.1, 0.2]


def test_serialize_deserialize_roundtrip():
    raw = {"vector": [0.3, 0.4, 0.5]}
    encoded = serialize_embedding(raw)
    assert encoded == "[0.3,0.4,0.5]"
    assert deserialize_embedding(encoded) == [0.3, 0.4, 0.5]


def test_normalize_rejects_invalid_embedding():
    with pytest.raises(TypeError):
        normalize_embedding(123)
    with pytest.raises(ValueError):
        normalize_embedding([1, None, 3])
