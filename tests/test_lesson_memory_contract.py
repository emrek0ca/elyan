"""Episodik belleğin (ders deposu) unutma ve tazelik sözleşmesi.

Kapatılan zaaf: dersler sınırlıydı (en çok 24) ve alaka kapısı vardı, ama
YAŞ kapısı YOKTU. Aylar önce "şu araç şu hatayı veriyor" diye öğrenilen bir
ders, hata düzeltildikten sonra da hatırlatılmaya devam ediyordu — bayat
hatırlatma, hatırlamamaktan kötüdür çünkü modeli yanlış yöne çeker.

Aynı ilke `situational_context.recent_output_is_fresh`te zaten vardı; episodik
bellekte eksikti.
"""

from __future__ import annotations

import datetime as dt

from runtime import lesson_store


def _entry(*, days_ago: float | None, lesson: str, capabilities: list[str]) -> dict:
    payload: dict = {"lesson": lesson, "capabilities": capabilities}
    if days_ago is not None:
        payload["recordedAt"] = (
            dt.datetime.now() - dt.timedelta(days=days_ago)
        ).isoformat(timespec="seconds")
    return payload


def test_fresh_lesson_is_recallable() -> None:
    assert lesson_store.lesson_is_fresh(
        _entry(days_ago=1, lesson="x", capabilities=["shell_run"])
    )


def test_expired_lesson_is_forgotten() -> None:
    assert not lesson_store.lesson_is_fresh(
        _entry(
            days_ago=lesson_store.LESSON_TTL_DAYS + 1,
            lesson="x",
            capabilities=["shell_run"],
        )
    )


def test_undated_lesson_is_treated_as_stale() -> None:
    """Fail-closed: yaşı bilinemeyen kayıt taşınmaz."""
    assert not lesson_store.lesson_is_fresh(
        _entry(days_ago=None, lesson="x", capabilities=["shell_run"])
    )
    assert not lesson_store.lesson_is_fresh(None)
    assert not lesson_store.lesson_is_fresh({"lesson": "x", "recordedAt": "bozuk"})


def test_recall_drops_expired_and_prefers_the_newest_at_equal_relevance(
    monkeypatch,
) -> None:
    """Eşit alakada YENİ ders kazanmalı.

    Önceki sürüm iki ayrı sıralama yüzünden eşitlikte ESKİ dersi öne alıyordu:
    sistem öğrendikçe eski gözlemi tekrarlıyordu.
    """
    lessons = [
        _entry(days_ago=20, lesson="eski ama taze ders", capabilities=["shell_run"]),
        _entry(days_ago=1, lesson="yeni ders", capabilities=["shell_run"]),
        _entry(
            days_ago=lesson_store.LESSON_TTL_DAYS + 5,
            lesson="bayat ders",
            capabilities=["shell_run"],
        ),
    ]
    monkeypatch.setattr(
        lesson_store.state_store,
        "snapshot",
        lambda: {"taskIntelligence": {"lessons": lessons}},
    )
    recalled = lesson_store.relevant_lessons(capabilities=["shell_run"], limit=3)
    assert "bayat ders" not in recalled
    assert recalled[0] == "yeni ders"


def test_irrelevant_context_recalls_nothing(monkeypatch) -> None:
    """Alaka kapısı korunur: örtüşme yoksa hatırlatma yapılmaz."""
    monkeypatch.setattr(
        lesson_store.state_store,
        "snapshot",
        lambda: {
            "taskIntelligence": {
                "lessons": [
                    _entry(days_ago=1, lesson="ders", capabilities=["shell_run"])
                ]
            }
        },
    )
    assert lesson_store.relevant_lessons(capabilities=["document_write"]) == []
    assert lesson_store.relevant_lessons(capabilities=[]) == []
