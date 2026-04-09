from __future__ import annotations

from core.decision_fabric import Decision, DecisionFabric


class _FakeAuditLogger:
    def __init__(self) -> None:
        self.operations: list[dict[str, object]] = []

    def log_operation(self, **kwargs):
        self.operations.append(dict(kwargs))
        return len(self.operations)


def test_record_persists_and_search_finds_summary_match(tmp_path) -> None:
    audit_logger = _FakeAuditLogger()
    fabric = DecisionFabric(storage_path=tmp_path / "decision_fabric.jsonl", audit_logger=audit_logger)
    decision = Decision(
        summary="Tedarikci X sozlesme yenilenmedi",
        context="Q3 fiyat artisi ve uc teslimat gecikmesi",
        actor_id="actor-1",
        workspace_id="ws-1",
        related_event_ids=["evt-1", "evt-2"],
        tags=["tedarikci", "lojistik"],
    )

    decision_id = fabric.record(decision)
    results = fabric.search("fiyat artisi", workspace_id="ws-1")

    assert decision_id
    assert [row.id for row in results] == [decision_id]
    assert audit_logger.operations[0]["action"] == "record"
    assert audit_logger.operations[1]["action"] == "search"


def test_search_isolated_by_workspace(tmp_path) -> None:
    fabric = DecisionFabric(storage_path=tmp_path / "decision_fabric.jsonl")
    fabric.record(
        Decision(
            summary="Logo connector secildi",
            context="Muhasebe ekibi mevcut lisans kullaniyor",
            actor_id="actor-1",
            workspace_id="ws-1",
            tags=["logo"],
        )
    )
    fabric.record(
        Decision(
            summary="Netsis connector secildi",
            context="Diger workspace Netsis kullaniyor",
            actor_id="actor-2",
            workspace_id="ws-2",
            tags=["netsis"],
        )
    )

    ws1_results = fabric.search("connector", workspace_id="ws-1")
    ws2_results = fabric.search("connector", workspace_id="ws-2")

    assert len(ws1_results) == 1
    assert len(ws2_results) == 1
    assert ws1_results[0].workspace_id == "ws-1"
    assert ws2_results[0].workspace_id == "ws-2"


def test_record_generates_defaults_for_missing_id_and_timestamp(tmp_path) -> None:
    fabric = DecisionFabric(storage_path=tmp_path / "decision_fabric.jsonl")
    decision = Decision(
        summary="Iyzico checkout akisi korundu",
        context="Gelir zinciri bozulmamali",
        actor_id="actor-1",
        workspace_id="ws-1",
    )

    decision_id = fabric.record(decision)
    results = fabric.search("checkout", workspace_id="ws-1")

    assert decision_id.startswith("decision_")
    assert results[0].timestamp


def test_search_matches_tags_and_returns_most_recent_first(tmp_path) -> None:
    fabric = DecisionFabric(storage_path=tmp_path / "decision_fabric.jsonl")
    first = Decision(
        summary="Eski onboarding kaldirildi",
        context="Kullanilmayan ekran temizligi",
        actor_id="actor-1",
        workspace_id="ws-1",
        timestamp="2026-04-08T10:00:00Z",
        tags=["frontend", "cleanup"],
    )
    second = Decision(
        summary="Yeni onboarding korundu",
        context="Aktif akis sabit kalacak",
        actor_id="actor-1",
        workspace_id="ws-1",
        timestamp="2026-04-09T10:00:00Z",
        tags=["frontend", "critical"],
    )
    fabric.record(first)
    fabric.record(second)

    results = fabric.search("frontend", workspace_id="ws-1")

    assert [row.summary for row in results] == [
        "Yeni onboarding korundu",
        "Eski onboarding kaldirildi",
    ]
