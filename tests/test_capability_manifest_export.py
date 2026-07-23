"""Backend'e üretilen desktop yetenek manifest'i, canlı katalogla bire bir
örtüşmeli. Katalog büyüyünce (yeni tool/skill/capability) manifest bayatlarsa
sunucu-materyalize planlayıcı yeni yeteneği bilemez — bu guard bunu yakalar.

Onarım: venv/bin/python scripts/export_capability_manifest.py \
    /Users/emrekoca/elyan-backend/src/modules/tasks/desktop-capability-manifest.ts
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.export_capability_manifest import build_manifest

MANIFEST_TS = Path(
    "/Users/emrekoca/elyan-backend/src/modules/tasks/desktop-capability-manifest.ts"
)


def _parse_ts_manifest(text: str) -> list[dict]:
    # Dizi literaline `= [` ile git (tip anotasyonundaki `[]` yakalanmasın).
    marker = text.index("DESKTOP_CAPABILITY_MANIFEST")
    start = text.index("= [", marker) + 2
    depth = 0
    for end in range(start, len(text)):
        if text[end] == "[":
            depth += 1
        elif text[end] == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : end + 1])
    raise AssertionError("manifest dizisi ayrıştırılamadı")


@pytest.mark.skipif(not MANIFEST_TS.exists(), reason="backend manifest yok")
def test_backend_manifest_matches_live_capability_catalog() -> None:
    live = build_manifest()
    stored = _parse_ts_manifest(MANIFEST_TS.read_text(encoding="utf-8"))
    live_names = {entry["name"] for entry in live}
    stored_names = {entry["name"] for entry in stored}
    missing = live_names - stored_names
    stale = stored_names - live_names
    assert not missing, f"manifest bayat — eksik yetenekler: {sorted(missing)} (export script'i çalıştır)"
    assert not stale, f"manifest fazlalık taşıyor: {sorted(stale)}"
    # Alan içerikleri de örtüşmeli (usage/requiredArgs/approval sürüklenmesi).
    assert live == stored, "manifest içeriği katalogla örtüşmüyor — export script'i çalıştır"


@pytest.mark.skipif(not MANIFEST_TS.exists(), reason="backend manifest yok")
def test_manifest_covers_safe_baseline_and_flags_approval() -> None:
    stored = {e["name"]: e for e in _parse_ts_manifest(MANIFEST_TS.read_text(encoding="utf-8"))}
    from runtime.execution_trust import SAFE_BASELINE_CAPABILITIES

    # Tüm taban yetenekler manifest'te bulunmalı (kapsam paritesi).
    for cap in SAFE_BASELINE_CAPABILITIES:
        assert cap in stored, f"zararsız taban yetenek manifest'te yok: {cap}"
    # Salt-okunur bakışlar asla onay istemez. (browser_control taban kapsamdadır
    # AMA dışa-dönük URL açtığından yerel sohbette onaya tabidir — mobil dispatch
    # consent'i kapsar; iki kapı ayrıdır, bu yüzden istisnadır.)
    for cap in ("directory_tree", "file_read", "file_search", "sys_info", "analyze_screen", "desktop_os.processes"):
        assert stored[cap]["requiresApproval"] is False, cap
    # En az bir riskli yetenek onay bayrağı taşımalı (güvenlik sınırı görünür).
    assert any(e["requiresApproval"] for e in stored.values())


def test_capability_manifest_exports_v2_quality_contracts() -> None:
    live = {entry["name"]: entry for entry in build_manifest()}

    for cap in {
        "canvas_write",
        "document_write",
        "spreadsheet_write",
        "presentation_write",
        "document_read",
        "file_read",
        "file_write",
        "file_search",
        "directory_tree",
        "web_research",
        "text_analyze",
        "image_generate",
        "image_edit",
        "image_read",
        "analyze_screen",
        "desktop_operator.observe_screen",
        "desktop_operator.execute_action",
        "desktop_operator.run",
        "math_solve",
        "chart_generate",
        "run_skill",
    }:
        assert cap in live, cap
        entry = live[cap]
        assert entry["whenToUse"], cap
        assert entry["inputContract"], cap
        assert entry["outputContract"], cap
        assert entry["verificationPlan"], cap
        assert entry["liveNarration"], cap
        assert entry["privacyClass"], cap

    assert live["canvas_write"]["artifactContract"]["artifactTypes"] == ["pdf", "image"]
    assert live["document_write"]["artifactContract"]["extension"] == ".docx"
    assert live["spreadsheet_write"]["artifactContract"]["extension"] == ".xlsx"
    assert live["presentation_write"]["artifactContract"]["extension"] == ".pptx"
    assert live["analyze_screen"]["outputContract"]["kind"] == "screen_analysis"
    assert live["run_skill"]["inputContract"]["skillIdMustExistInCatalog"] is True
