"""Tests for OllamaDiscovery — model availability sync."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.llm.ollama_discovery import OllamaDiscovery


@pytest.fixture
def discovery():
    return OllamaDiscovery("http://127.0.0.1:11434")


@pytest.mark.asyncio
async def test_probe_healthy(discovery):
    """Simulates a healthy Ollama response."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "models": [
            {"name": "llama3.2:3b"},
            {"name": "qwen2.5:7b"},
        ]
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock()

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock()

    with patch("aiohttp.ClientSession", return_value=mock_session):
        models = await discovery.probe_once()

    assert "llama3.2:3b" in models
    assert "qwen2.5:7b" in models
    assert discovery.healthy is True


@pytest.mark.asyncio
async def test_probe_unhealthy(discovery):
    """Connection refused → healthy=False."""
    with patch("aiohttp.ClientSession", side_effect=Exception("connection refused")):
        models = await discovery.probe_once()

    assert models == []
    assert discovery.healthy is False


def test_status(discovery):
    s = discovery.status()
    assert "healthy" in s
    assert "models" in s
    assert s["healthy"] is False


@pytest.mark.asyncio
async def test_sync_with_policy(discovery):
    """Verifies availability flags are updated on policy candidates."""
    from core.llm.model_selection_policy import (
        ModelCandidate, ModelSelectionPolicy, get_model_selection_policy,
    )

    # Set up a fresh policy
    policy = ModelSelectionPolicy()
    policy.register_candidate(ModelCandidate(
        provider="ollama", model="llama3.2:3b", is_local=True, available=False,
    ))
    policy.register_candidate(ModelCandidate(
        provider="ollama", model="qwen2.5:7b", is_local=True, available=False,
    ))
    policy.register_candidate(ModelCandidate(
        provider="openai", model="gpt-4o", is_local=False, available=True,
    ))

    # Mock probe to return only llama
    discovery.probe_once = AsyncMock(return_value=["llama3.2:3b"])

    with patch("core.llm.ollama_discovery.get_model_selection_policy" if False else
               "core.llm.model_selection_policy.get_model_selection_policy",
               return_value=policy):
        # Patch the import inside sync_with_policy
        import core.llm.ollama_discovery as od_mod
        original = od_mod.__dict__.get("get_model_selection_policy")
        try:
            # Direct monkey-patch for test
            import core.llm.model_selection_policy as msp
            old_fn = msp.get_model_selection_policy
            msp._policy_instance = policy
            await discovery.sync_with_policy()
        finally:
            msp._policy_instance = None

    # llama should be available, qwen should not, openai untouched
    llama = [c for c in policy._candidates if c.model == "llama3.2:3b"][0]
    qwen = [c for c in policy._candidates if c.model == "qwen2.5:7b"][0]
    openai = [c for c in policy._candidates if c.model == "gpt-4o"][0]

    assert llama.available is True
    assert qwen.available is False
    assert openai.available is True  # Untouched (not ollama provider)
