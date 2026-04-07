from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent


def test_bot_gateway_server_includes_integration_routes():
    source = (_REPO / "core/gateway/server.py").read_text(encoding="utf-8")

    assert "add_get('/api/integrations/accounts'" in source
    assert "add_post('/api/integrations/connect'" in source
    assert "add_post('/api/integrations/accounts/connect'" in source
    assert "add_post('/api/integrations/accounts/revoke'" in source
    assert "add_get('/api/integrations/traces'" in source
    assert "add_get('/api/integrations/summary'" in source
    assert "add_get('/api/packs'" in source
    assert "add_get('/api/packs/{pack}'" in source
    assert "handle_integrations_accounts" in source
    assert "handle_integrations_connect" in source
    assert "handle_integrations_account_connect" in source
    assert "handle_integrations_account_revoke" in source
    assert "handle_integration_traces" in source
    assert "handle_integration_summary" in source
    assert "handle_packs_overview" in source
    assert "handle_pack_detail" in source
