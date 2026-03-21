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
    assert 'id="autopilot-kpis"' in html
    assert 'id="autopilot-summary"' in html
    assert 'id="autopilot-refresh"' in html
    assert 'id="autopilot-start"' in html
    assert 'id="autopilot-tick"' in html
    assert 'id="autopilot-stop"' in html
    assert 'id="packs-refresh"' in html
    assert 'id="pack-quivr-status"' in html
    assert 'id="pack-cloudflare-agents-status"' in html
    assert 'id="pack-opengauss-status"' in html
    assert 'js-pack-refresh' in html
    assert 'js-pack-mission' in html
    assert 'elyan packs scaffold quivr --path ./quivr' in html
    assert 'elyan packs scaffold cloudflare-agents --path ./worker' in html
    assert 'elyan packs scaffold opengauss --path ./db' in html
    assert 'id="skills-refresh"' in html
    assert 'id="skills-kpis"' in html
    assert 'id="skills-list"' in html
    assert 'id="skills-workflow-list"' in html
    assert 'id="marketplace-refresh"' in html
    assert 'id="marketplace-query"' in html
    assert 'id="marketplace-search"' in html
    assert 'id="marketplace-kpis"' in html
    assert 'id="marketplace-list"' in html
    assert 'data-t="integrations"' in html
    assert 'id="p-integrations"' in html
    assert 'id="integration-app"' in html
    assert 'id="integration-quick-presets"' in html
    assert 'id="integration-provider"' in html
    assert 'id="integration-account-alias"' in html
    assert 'id="integration-scopes"' in html
    assert 'id="integration-mode"' in html
    assert 'id="integration-auth-code"' in html
    assert 'id="integration-redirect-uri"' in html
    assert 'id="integration-connect"' in html
    assert 'id="integration-revoke"' in html
    assert 'integration-logo' in html
    assert 'integration-advanced' in html
    assert 'hidden aria-hidden="true"' in html
    assert 'Uygulamayı seç, Elyan sağlayıcıyı, scope' in html
    assert 'id="integration-summary"' in html
    assert 'id="integration-accounts"' in html
    assert 'id="integration-trace-filter"' in html
    assert 'id="integration-trace-search"' in html
    assert 'id="integration-trace-kpis"' in html
    assert 'id="integration-traces"' in html
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
