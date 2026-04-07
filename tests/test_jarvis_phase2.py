"""
tests/test_jarvis_phase2.py
───────────────────────────────────────────────────────────────────────────────
Phase 2 Jarvis testi:
  - Türkçe suffix extraction (TR_SUFFIXES, _strip_tr_suffix, _extract_app_name)
  - Terminal/search entity extraction suffix fix
  - Sequential command chain detection
  - Intent confidence calibration (keyword length → score)
  - Calendar natural language parsing
  - IntentExecutor handler routing (no real subprocess calls)
"""
from __future__ import annotations

import asyncio
import sys
import os

import pytest

# ── path bootstrap ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Turkish Suffix Stripping
# ═══════════════════════════════════════════════════════════════════════════════

class TestTurkishSuffixStripping:
    def setup_method(self):
        from core.jarvis.intent_executor import _strip_tr_suffix
        self.strip = _strip_tr_suffix

    def test_yi_suffix(self):
        assert self.strip("safari'yi") == "safari"

    def test_yu_suffix(self):
        assert self.strip("zoom'u") == "zoom"

    def test_de_suffix(self):
        assert self.strip("terminal'de") == "terminal"

    def test_den_suffix(self):
        assert self.strip("finder'den") == "finder"

    def test_nin_suffix(self):
        assert self.strip("chrome'un") == "chrome"

    def test_no_suffix(self):
        assert self.strip("spotify") == "spotify"

    def test_curly_apostrophe(self):
        # Unicode right single quotation mark (U+2019)
        assert self.strip("safari\u2019yi") == "safari"

    def test_case_insensitive(self):
        assert self.strip("Safari'yi") == "safari"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. App Name Extraction with Suffixes
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractAppName:
    def setup_method(self):
        from core.jarvis.intent_executor import _extract_app_name
        self.extract = _extract_app_name

    def test_plain(self):
        assert self.extract("Safari aç") == "Safari"

    def test_yi_suffix(self):
        assert self.extract("Safari'yi aç") == "Safari"

    def test_yu_suffix(self):
        assert self.extract("Zoom'u kapat") == "Zoom"

    def test_u_suffix(self):
        assert self.extract("Spotify'u aç") == "Spotify"

    def test_i_suffix(self):
        assert self.extract("Telegram'ı aç") == "Telegram"

    def test_multi_word_alias(self):
        assert self.extract("Visual Studio Code aç") == "Visual Studio Code"

    def test_vscode_alias(self):
        assert self.extract("vscode'u aç") == "Visual Studio Code"

    def test_ayarlar_alias(self):
        assert self.extract("ayarları aç") == "System Preferences"

    def test_unknown_app(self):
        result = self.extract("Foobar uygulamasını aç")
        # Should return something (title-cased) not empty
        assert result != ""


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Terminal Command Extraction
# ═══════════════════════════════════════════════════════════════════════════════

class TestTerminalCmdExtraction:
    def setup_method(self):
        from core.jarvis.intent_executor import _extract_terminal_cmd
        self.extract = _extract_terminal_cmd

    def test_basic_run(self):
        assert self.extract("ls çalıştır") == "ls"

    def test_run_with_args(self):
        assert self.extract("ls -la çalıştır") == "ls -la"

    def test_suffix_on_cmd(self):
        # "ls'yi çalıştır" → cmd = "ls"
        cmd = self.extract("ls'yi çalıştır")
        assert cmd == "ls", f"Expected 'ls', got '{cmd}'"

    def test_terminal_prefix(self):
        cmd = self.extract("terminal'de ls çalıştır")
        assert "ls" in cmd

    def test_run_prefix(self):
        cmd = self.extract("run git status")
        assert "git" in cmd and "status" in cmd

    def test_empty_on_no_match(self):
        assert self.extract("hava durumu") == ""


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Search Query Extraction
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchQueryExtraction:
    def setup_method(self):
        from core.jarvis.intent_executor import _extract_search_query
        self.extract = _extract_search_query

    def test_ara_prefix(self):
        assert self.extract("Python ara") == "Python"

    def test_suffix_stripped(self):
        q = self.extract("Python'u ara")
        assert q == "Python", f"Expected 'Python', got '{q}'"

    def test_google_prefix(self):
        assert "elyan" in self.extract("google elyan").lower()

    def test_multiword(self):
        q = self.extract("Python async ne demek ara")
        assert "python" in q.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Sequential Command Chain Detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestChainDetection:
    def setup_method(self):
        from core.jarvis.jarvis_core import JarvisCore
        self.jc = JarvisCore()

    def test_single_command(self):
        segments = self.jc._split_chained_commands("Safari aç")
        assert len(segments) == 1
        assert segments[0] == "Safari aç"

    def test_sonra_split(self):
        segments = self.jc._split_chained_commands("Safari aç sonra ekran görüntüsü al")
        assert len(segments) == 2
        assert "safari" in segments[0].lower()
        assert "ekran" in segments[1].lower()

    def test_ve_sonra_split(self):
        segments = self.jc._split_chained_commands("Spotify aç ve sonra ses 80 yap")
        assert len(segments) == 2

    def test_ardından_split(self):
        segments = self.jc._split_chained_commands("ls çalıştır ardından pwd çalıştır")
        assert len(segments) == 2

    def test_ve_weak_split_two_words_each_side(self):
        segments = self.jc._split_chained_commands("Safari aç ve Spotify kapat")
        assert len(segments) == 2

    def test_ve_no_split_short(self):
        # "Ali ve Veli" — both sides have 1 word → should NOT split
        segments = self.jc._split_chained_commands("Ali ve Veli")
        assert len(segments) == 1

    def test_triple_chain(self):
        text = "Safari aç sonra ekran görüntüsü al sonra Telegram aç"
        segments = self.jc._split_chained_commands(text)
        assert len(segments) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Intent Confidence Calibration
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfidenceCalibration:
    def setup_method(self):
        from core.jarvis.jarvis_core import IntentClassifier
        self.clf = IntentClassifier()

    def test_long_keyword_high_confidence(self):
        # "ekran görüntüsü al" (19 chars) → very high confidence
        intent = self.clf.classify("ekran görüntüsü al")
        assert intent.confidence >= 0.90, f"Expected ≥0.90, got {intent.confidence}"

    def test_short_keyword_lower_confidence(self):
        # "aç" (2 chars) → lower confidence than long keyword
        short_intent = self.clf.classify("aç")
        long_intent = self.clf.classify("ekran görüntüsü al")
        assert long_intent.confidence > short_intent.confidence

    def test_no_match_low_confidence(self):
        intent = self.clf.classify("xxxxxxxx nonsense xyz")
        assert intent.confidence <= 0.45

    def test_monitoring_keyword_confidence(self):
        intent = self.clf.classify("batarya durumu nedir")
        # "batarya" (7 chars) → confidence should be > 0.65
        assert intent.confidence > 0.65

    def test_capped_at_098(self):
        # Even very long keywords shouldn't exceed 0.98
        intent = self.clf.classify("takvim etkinlik bugün")
        assert intent.confidence <= 0.98


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Calendar NL Parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalendarParsing:
    def setup_method(self):
        from core.integrations.calendar import parse_create_request
        self.parse = parse_create_request

    def test_title_extraction(self):
        req = self.parse("Yarın saat 15:00'de toplantı ekle")
        assert req["title"] != ""
        assert "toplantı" in req["title"].lower() or len(req["title"]) > 0

    def test_tomorrow_date(self):
        from datetime import datetime, timedelta
        req = self.parse("Yarın saat 10:00'de görüşme")
        tomorrow = (datetime.now() + timedelta(days=1)).date()
        assert req["start"].date() == tomorrow

    def test_time_parsing_hhmm(self):
        req = self.parse("Yarın 15:30'da toplantı")
        assert req["start"].hour == 15
        assert req["start"].minute == 30

    def test_time_parsing_saat(self):
        req = self.parse("Yarın saat 9 toplantı")
        assert req["start"].hour == 9

    def test_duration_saatlik(self):
        req = self.parse("Yarın 2 saatlik workshop")
        assert req["duration_minutes"] == 120

    def test_duration_dakikalık(self):
        req = self.parse("Yarın 45 dakikalık görüşme")
        assert req["duration_minutes"] == 45

    def test_default_duration(self):
        req = self.parse("Yarın toplantı")
        assert req["duration_minutes"] == 60  # default


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Intent Executor Routing (no real system calls)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntentExecutorRouting:
    """Tests that the right handler is called for each intent."""

    def _make_intent(self, category: str, sub: str, text: str = "test"):
        from core.jarvis.jarvis_core import ClassifiedIntent, IntentCategory, Complexity
        return ClassifiedIntent(
            category=IntentCategory(category),
            complexity=Complexity.SIMPLE,
            confidence=0.9,
            sub_intent=sub,
            raw_text=text,
        )

    @pytest.mark.asyncio
    async def test_unknown_returns_empty(self):
        from core.jarvis.intent_executor import IntentExecutor
        ex = IntentExecutor()
        intent = self._make_intent("conversation", "chat", "selam")
        result = await ex.execute(intent)
        assert result == ""  # conversation falls through to LLM

    @pytest.mark.asyncio
    async def test_system_health_returns_string(self):
        from unittest.mock import AsyncMock, patch, MagicMock
        from core.jarvis.intent_executor import IntentExecutor

        mock_ac = MagicMock()
        mock_ac.get_cpu_usage = AsyncMock(return_value=12.5)
        mock_ac.get_battery_info = AsyncMock(return_value={"percent": 80, "charging": False})
        mock_ac.get_disk_usage = AsyncMock(return_value={"free_gb": 100.0, "total_gb": 500.0})

        with patch("core.jarvis.intent_executor.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(stdout="Pages free: 12345.", returncode=0)
            with patch("core.computer.app_controller.AppController", return_value=mock_ac):
                ex = IntentExecutor()
                intent = self._make_intent("monitoring", "system_health", "sistem durumu")
                result = await ex.execute(intent)
                assert isinstance(result, str)
                assert len(result) > 0

    @pytest.mark.asyncio
    async def test_network_ip_query(self):
        from unittest.mock import patch, MagicMock
        from core.jarvis.intent_executor import IntentExecutor

        mock_result = MagicMock()
        mock_result.stdout = "192.168.1.1\n"
        mock_result.returncode = 0

        with patch("core.jarvis.intent_executor.subprocess") as mock_sub:
            mock_sub.run.return_value = mock_result
            ex = IntentExecutor()
            intent = self._make_intent("system_control", "network", "ip adresim nedir")
            result = await ex.execute(intent)
            assert "192" in result or "ip" in result.lower()

    @pytest.mark.asyncio
    async def test_web_search_opens_url(self):
        from unittest.mock import AsyncMock, patch, MagicMock
        from core.jarvis.intent_executor import IntentExecutor

        mock_ac = MagicMock()
        mock_ac.open_url = AsyncMock(return_value=True)

        with patch("core.computer.app_controller.AppController", return_value=mock_ac):
            ex = IntentExecutor()
            intent = self._make_intent("information", "search", "Python ara")
            result = await ex.execute(intent)
            assert "Python" in result or "python" in result.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Ollama Streaming (unit — no real Ollama)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOllamaStreaming:
    @pytest.mark.asyncio
    async def test_stream_calls_on_chunk(self):
        """_ollama_stream calls on_chunk for each chunk and returns full text."""
        import json
        from unittest.mock import patch, MagicMock
        from core.jarvis.jarvis_core import _ollama_stream

        # Simulate Ollama streaming response: 3 lines
        chunks_data = [
            json.dumps({"response": "Merhaba"}).encode() + b"\n",
            json.dumps({"response": " nasıl"}).encode() + b"\n",
            json.dumps({"response": " yardımcı olabilirim?"}).encode() + b"\n",
        ]

        class FakeResponse:
            def __iter__(self):
                return iter(chunks_data)
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        collected_chunks: list[str] = []

        def on_chunk(chunk: str):
            collected_chunks.append(chunk)

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = await _ollama_stream("selam", on_chunk=on_chunk)

        assert result == "Merhaba nasıl yardımcı olabilirim?"
        assert collected_chunks == ["Merhaba", " nasıl", " yardımcı olabilirim?"]

    @pytest.mark.asyncio
    async def test_stream_handles_network_error_gracefully(self):
        """Network error → returns empty string, no exception raised."""
        from unittest.mock import patch
        from core.jarvis.jarvis_core import _ollama_stream

        def on_chunk(c):
            pass

        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = await _ollama_stream("selam", on_chunk=on_chunk)

        assert result == ""

    @pytest.mark.asyncio
    async def test_stream_async_on_chunk(self):
        """on_chunk can be an async callable."""
        import json
        from unittest.mock import patch
        from core.jarvis.jarvis_core import _ollama_stream

        chunks_data = [json.dumps({"response": "test"}).encode() + b"\n"]

        class FakeResponse:
            def __iter__(self): return iter(chunks_data)
            def __enter__(self): return self
            def __exit__(self, *a): pass

        received = []

        async def async_on_chunk(chunk: str):
            received.append(chunk)

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = await _ollama_stream("test", on_chunk=async_on_chunk)

        assert result == "test"
        assert received == ["test"]


# ═══════════════════════════════════════════════════════════════════════════════
# 10. JarvisCore — handle() chain integration (no real LLM)
# ═══════════════════════════════════════════════════════════════════════════════

class TestJarvisCoreChainIntegration:
    @pytest.mark.asyncio
    async def test_single_command_no_chain(self):
        from unittest.mock import AsyncMock, patch
        from core.jarvis.jarvis_core import JarvisCore

        jc = JarvisCore()
        with patch.object(jc, "_dispatch", new_callable=AsyncMock, return_value="pong"):
            resp = await jc.handle("selam", "desktop", "test_user")
        assert resp.text == "pong"

    @pytest.mark.asyncio
    async def test_chain_two_steps_both_executed(self):
        from unittest.mock import AsyncMock, patch
        from core.jarvis.jarvis_core import JarvisCore

        jc = JarvisCore()
        call_log = []

        async def fake_dispatch(text, intent, channel, user):
            call_log.append(text)
            return f"result:{text[:10]}"

        with patch.object(jc, "_dispatch", side_effect=fake_dispatch):
            resp = await jc.handle("Safari aç sonra ekran görüntüsü al", "desktop", "u1")

        assert len(call_log) == 2
        assert resp.text  # non-empty combined result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
