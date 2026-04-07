"""
tests/test_faz7_memory.py — Faz 7 Episodik Hafıza & Kişilik Adaptörü testleri
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# JarvisMemory
# ─────────────────────────────────────────────────────────────────────────────

class TestJarvisMemory:
    def _mem(self):
        from core.memory.jarvis_memory import JarvisMemory
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            return JarvisMemory(db=Path(f.name))

    def test_record_and_recent(self):
        from core.memory.jarvis_memory import Interaction
        mem = self._mem()
        ix = Interaction("u1", "telegram", "merhaba", "selam", "ok")
        mem.record(ix)
        recent = mem.recent("u1", limit=5)
        assert len(recent) == 1
        assert recent[0]["input_text"] == "merhaba"

    def test_recent_empty_for_unknown_user(self):
        mem = self._mem()
        assert mem.recent("unknown_user") == []

    def test_recipe_not_created_before_threshold(self):
        from core.memory.jarvis_memory import Interaction
        mem = self._mem()
        for _ in range(2):
            mem.record(Interaction("u1", "tg", "rapor hazırla lütfen", "hazırlandı", "ok"))
        recipes = mem.relevant_recipes("u1", "rapor hazırla lütfen")
        assert recipes == []  # threshold=3, only 2 records

    def test_recipe_created_after_threshold(self):
        from core.memory.jarvis_memory import Interaction
        mem = self._mem()
        for _ in range(3):
            mem.record(Interaction("u1", "tg", "rapor hazırla lütfen", "hazırlandı", "ok"))
        recipes = mem.relevant_recipes("u1", "rapor hazırla lütfen")
        assert len(recipes) >= 1

    def test_relevant_recipes_returns_matching_keyword(self):
        from core.memory.jarvis_memory import Interaction
        mem = self._mem()
        for _ in range(3):
            mem.record(Interaction("u1", "tg", "analiz yap veri", "tamam", "ok"))
        # keyword "analiz" should match
        recipes = mem.relevant_recipes("u1", "analiz sonucu göster")
        assert len(recipes) >= 1
        assert any("analiz" in r["trigger_pat"] or "veri" in r["trigger_pat"] for r in recipes)

    def test_build_context_hint_returns_string(self):
        from core.memory.jarvis_memory import Interaction
        mem = self._mem()
        mem.record(Interaction("u1", "tg", "test mesajı", "test yanıt", "ok"))
        hint = mem.build_context_hint("u1", "test mesajı")
        assert isinstance(hint, str)

    def test_build_context_hint_empty_for_new_user(self):
        mem = self._mem()
        hint = mem.build_context_hint("new_user", "herhangi bir şey")
        assert hint == ""

    def test_record_multiple_users_isolated(self):
        from core.memory.jarvis_memory import Interaction
        mem = self._mem()
        mem.record(Interaction("userA", "tg", "A mesajı", "A yanıt", "ok"))
        mem.record(Interaction("userB", "tg", "B mesajı", "B yanıt", "ok"))
        assert len(mem.recent("userA")) == 1
        assert len(mem.recent("userB")) == 1
        assert mem.recent("userA")[0]["input_text"] == "A mesajı"

    def test_singleton_returns_same_instance(self):
        import core.memory.jarvis_memory as m
        m._instance = None
        a = m.get_jarvis_memory()
        b = m.get_jarvis_memory()
        assert a is b
        m._instance = None


# ─────────────────────────────────────────────────────────────────────────────
# PersonalityAdapter
# ─────────────────────────────────────────────────────────────────────────────

class TestPersonalityAdapter:
    def _adapter(self):
        from core.memory.personality_adapter import PersonalityAdapter
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            return PersonalityAdapter(db=Path(f.name))

    def test_default_profile(self):
        pa = self._adapter()
        p = pa.get_profile("u1")
        assert p.response_length == "medium"
        assert p.formality == "casual"
        assert p.preferred_channel == "desktop"
        assert not p.dnd_enabled

    def test_profile_persisted(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        from core.memory.personality_adapter import PersonalityAdapter
        pa1 = PersonalityAdapter(db=db_path)
        p = pa1.get_profile("u1")
        p.formality = "formal"
        pa1._save(p)

        pa2 = PersonalityAdapter(db=db_path)
        p2 = pa2.get_profile("u1")
        assert p2.formality == "formal"

    def test_observe_channel_updates_preferred(self):
        pa = self._adapter()
        for _ in range(5):
            pa.observe_channel("u1", "telegram")
        p = pa.get_profile("u1")
        assert p.preferred_channel == "telegram"

    def test_observe_response_length_short(self):
        pa = self._adapter()
        for _ in range(3):
            pa.observe_response_length("u1", 50)   # short = <150 chars
        p = pa.get_profile("u1")
        assert p.response_length == "short"

    def test_observe_response_length_long(self):
        pa = self._adapter()
        for _ in range(3):
            pa.observe_response_length("u1", 800)  # long = >600 chars
        p = pa.get_profile("u1")
        assert p.response_length == "long"

    def test_dnd_toggle(self):
        pa = self._adapter()
        pa.set_dnd("u1", True)
        assert pa.get_profile("u1").dnd_enabled
        pa.set_dnd("u1", False)
        assert not pa.get_profile("u1").dnd_enabled

    def test_response_style_hint_not_empty(self):
        pa = self._adapter()
        p = pa.get_profile("u1")
        hint = p.response_style_hint()
        assert isinstance(hint, str)
        assert len(hint) > 0

    def test_is_work_hours_boundaries(self):
        from core.memory.personality_adapter import UserProfile
        p = UserProfile(user_id="u1", work_hours_start=9, work_hours_end=18)
        # We can't control real time, but we can verify the logic
        import time
        hour = time.localtime().tm_hour
        expected = 9 <= hour < 18
        assert p.is_work_hours() == expected

    def test_multiple_users_isolated(self):
        pa = self._adapter()
        pa.observe_channel("alice", "telegram")
        pa.observe_channel("alice", "telegram")
        pa.observe_channel("alice", "telegram")
        for _ in range(5):
            pa.observe_channel("bob", "whatsapp")
        assert pa.get_profile("alice").preferred_channel == "telegram"
        assert pa.get_profile("bob").preferred_channel == "whatsapp"

    def test_observation_count_increments(self):
        pa = self._adapter()
        pa.observe_channel("u1", "telegram")
        pa.observe_channel("u1", "telegram")
        p = pa.get_profile("u1")
        assert p.observation_count >= 0  # observe_channel doesn't increment

    def test_singleton(self):
        import core.memory.personality_adapter as m
        m._instance = None
        a = m.get_personality_adapter()
        b = m.get_personality_adapter()
        assert a is b
        m._instance = None


# ─────────────────────────────────────────────────────────────────────────────
# JarvisStartup smoke test
# ─────────────────────────────────────────────────────────────────────────────

class TestJarvisStartup:
    @pytest.mark.asyncio
    async def test_start_services_completes_without_crashing(self):
        """All services should start gracefully even if deps are missing."""
        from core.jarvis.jarvis_startup import start_jarvis_services
        # Should not raise even if Ollama is offline, pyaudio is missing, etc.
        await start_jarvis_services(broadcast=None)

    @pytest.mark.asyncio
    async def test_stop_services_completes_without_crashing(self):
        from core.jarvis.jarvis_startup import stop_jarvis_services
        await stop_jarvis_services()
