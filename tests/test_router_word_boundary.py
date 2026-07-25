"""Alt dizge eşleşmesi bug sınıfı: tetikleyici sözcük, başka bir sözcüğün
ORTASINDA geçtiği için yanlış rota üretmemeli.

Canlı arıza: "Masaüstünde alışverişlistesi.txt oluştur" → directory_tree,
çünkü "list" tetikleyicisi "alışveriş·list·esi" içinde eşleşiyordu.
"""
from __future__ import annotations

import pytest

from runtime.task_router import _word_starts, route_text_to_tool


def _caps(routed) -> list[str]:
    if routed is None:
        return []
    steps = getattr(routed, "steps", ()) or ()
    return [s.get("capability") for s in steps] or [routed.tool_name]


@pytest.mark.parametrize(
    "text",
    [
        "Masaüstünde alışverişlistesi.txt oluştur",
        "masaüstünde alışveriş listesi.txt oluştur",
        "masaüstüne notlar.txt oluştur",
    ],
)
def test_creation_is_never_routed_to_listing(text: str) -> None:
    caps = _caps(route_text_to_tool(text))
    assert "directory_tree" not in caps, f"{text} → listeleme rotasına düştü: {caps}"


@pytest.mark.parametrize(
    "text",
    [
        "masaüstündeki dosyaları listele",
        "indirilenler klasöründe ne var",
    ],
)
def test_real_listing_still_works(text: str) -> None:
    assert "directory_tree" in _caps(route_text_to_tool(text)), text


def test_word_starts_rejects_midword_match() -> None:
    # Alt dizge olarak geçer ama SÖZCÜK başı değildir.
    assert "list" in "alisverislistesi"
    assert _word_starts("alisverislistesi", "list") is False
    # Sözcük başında geçince yakalanır; Türkçe ekler de tolere edilir.
    assert _word_starts("dosyalari listele", "list") is True
    assert _word_starts("listeleyebilir misin", "listele") is True
