"""Basic regression tests for dashboard.html."""

from pathlib import Path


def test_dashboard_html_contains_mission_tools_and_settings_tabs():
    html = Path("/Users/emrekoca/Desktop/bot/ui/web/dashboard.html").read_text(encoding="utf-8")

    assert "Mission" in html
    assert 'data-t="mission"' in html
    assert 'data-t="tools"' in html
    assert 'data-t="settings"' in html
    assert 'id="mission-input"' in html
    assert 'id="mission-list"' in html
    assert 'id="mission-filters"' in html
    assert 'id="mission-timeline"' in html
    assert 'id="mission-approvals"' in html
    assert 'id="mission-evidence"' in html
    assert 'id="mission-control-strip"' in html
    assert 'id="mission-quality"' in html
    assert 'id="mission-skills"' in html
    assert 'id="mission-memory"' in html
    assert "Save as Skill" in html
    assert 'id="p-tools"' in html
    assert 'id="llm-grid"' in html
    assert 'id="oll-installed"' in html
    assert 'id="st-table"' in html
    assert "Tools" in html
    assert "LLM Yönetimi" not in html
    assert "Ollama Yönetimi" not in html
    assert "Sistem Durumu" not in html
    assert "/desktop" not in html
    assert "/ui/web/dashboard.css" in html
    assert "/ui/web/dashboard.js" in html


def test_ops_console_html_contains_admin_panels():
    html = Path("/Users/emrekoca/Desktop/bot/ui/web/ops_console.html").read_text(encoding="utf-8")

    assert "Elyan Ops Console" in html
    assert 'id="user-list"' in html
    assert 'id="lane-execution"' in html
    assert 'id="selected-plan"' in html
    assert "/ui/web/ops_console.css" in html
    assert "/ui/web/ops_console.js" in html
