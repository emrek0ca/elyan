"""Tests for ElyanCore — intent classification, task decomposition, response synthesis."""

import pytest
from core.elyan.elyan_core import (
    IntentCategory, Complexity, IntentClassifier,
    TaskDecomposer, ResponseSynthesizer, ElyanCore,
)


# ── IntentClassifier tests ──────────────────────────────────────────────────

class TestIntentClassifier:
    def setup_method(self):
        self.clf = IntentClassifier()

    def test_system_control_app(self):
        r = self.clf.classify("Safari'yi aç")
        assert r.category == IntentCategory.SYSTEM_CONTROL
        assert r.sub_intent == "app_control"

    def test_system_control_terminal(self):
        r = self.clf.classify("terminalde ls komutu çalıştır")
        assert r.category == IntentCategory.SYSTEM_CONTROL

    def test_system_control_network(self):
        r = self.clf.classify("wifi bağlantısını kontrol et")
        assert r.category == IntentCategory.SYSTEM_CONTROL
        assert r.sub_intent == "network"

    def test_information_search(self):
        r = self.clf.classify("Python asyncio hakkında araştır")
        assert r.category == IntentCategory.INFORMATION
        assert r.sub_intent == "search"

    def test_information_explain(self):
        r = self.clf.classify("bu hatayı açıkla")
        assert r.category == IntentCategory.INFORMATION

    def test_creation_code(self):
        r = self.clf.classify("bir Python fonksiyonu kodla")
        assert r.category == IntentCategory.CREATION
        assert r.sub_intent == "code"

    def test_creation_website(self):
        r = self.clf.classify("bir landing page web sitesi oluştur")
        assert r.category == IntentCategory.CREATION

    def test_communication_email(self):
        r = self.clf.classify("e-posta yaz ve gönder")
        assert r.category == IntentCategory.COMMUNICATION

    def test_monitoring(self):
        r = self.clf.classify("CPU kullanımını izle")
        assert r.category == IntentCategory.MONITORING

    def test_automation(self):
        r = self.clf.classify("her sabah 9'da rapor otomatik gönder")
        assert r.category == IntentCategory.AUTOMATION

    def test_conversation_fallback(self):
        r = self.clf.classify("bugün nasılsın?")
        assert r.category == IntentCategory.CONVERSATION
        assert r.confidence < 0.8

    def test_complexity_trivial(self):
        r = self.clf.classify("merhaba")
        assert r.complexity == Complexity.TRIVIAL

    def test_complexity_expert(self):
        r = self.clf.classify("kapsamlı bir proje hazırla sıfırdan tüm dosyaları oluştur")
        assert r.complexity == Complexity.EXPERT

    def test_confidence_rules_higher(self):
        # "aç" is a 2-char keyword → confidence = 0.55 + 2/20 = 0.65
        # Rule-based match is always > fallback conversation (0.5)
        r = self.clf.classify("Safari aç")
        assert r.confidence >= 0.60
        assert r.category == IntentCategory.SYSTEM_CONTROL


# ── TaskDecomposer tests ────────────────────────────────────────────────────

class TestTaskDecomposer:
    def setup_method(self):
        self.clf = IntentClassifier()
        self.dec = TaskDecomposer()

    def test_trivial_single_step(self):
        intent = self.clf.classify("merhaba")
        plan = self.dec.decompose(intent)
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "chat_response"

    def test_system_control_has_ops(self):
        intent = self.clf.classify("Safari aç")
        plan = self.dec.decompose(intent)
        assert any(s.owner == "ops" for s in plan.steps)

    def test_creation_has_builder(self):
        intent = self.clf.classify("bir web sitesi oluştur benim için")
        plan = self.dec.decompose(intent)
        assert any(s.owner == "builder" for s in plan.steps)

    def test_information_has_researcher(self):
        intent = self.clf.classify("Python async hakkında araştır")
        plan = self.dec.decompose(intent)
        assert any(s.owner == "researcher" for s in plan.steps)

    def test_communication_requires_approval(self):
        intent = self.clf.classify("Ahmet'e toplantı hakkında bilgilendirme mesaj gönder lütfen")
        plan = self.dec.decompose(intent)
        assert plan.requires_approval is True

    def test_terminal_requires_approval(self):
        intent = self.clf.classify("terminalde rm -rf komutu çalıştır")
        plan = self.dec.decompose(intent)
        assert plan.requires_approval is True

    def test_creation_has_dependencies(self):
        intent = self.clf.classify("kapsamlı bir proje oluştur")
        plan = self.dec.decompose(intent)
        # builder depends on lead's plan
        builder_step = next(s for s in plan.steps if s.owner == "builder")
        assert len(builder_step.depends_on) > 0


# ── ResponseSynthesizer tests ───────────────────────────────────────────────

class TestResponseSynthesizer:
    def setup_method(self):
        self.syn = ResponseSynthesizer()
        self.dummy_intent = IntentClassifier().classify("test")

    def test_combines_texts(self):
        results = [{"text": "Part 1"}, {"text": "Part 2"}]
        resp = self.syn.synthesize(results, self.dummy_intent, "telegram")
        assert "Part 1" in resp.text
        assert "Part 2" in resp.text

    def test_imessage_strips_markdown(self):
        results = [{"text": "**bold** and *italic*"}]
        resp = self.syn.synthesize(results, self.dummy_intent, "imessage")
        assert "**" not in resp.text
        assert resp.channel_format == "plain"

    def test_truncates_long_text(self):
        results = [{"text": "x" * 5000}]
        resp = self.syn.synthesize(results, self.dummy_intent, "telegram")
        assert len(resp.text) <= 4096

    def test_empty_results_fallback(self):
        resp = self.syn.synthesize([], self.dummy_intent, "telegram")
        assert resp.text  # Should not be empty


# ── ElyanCore integration ──────────────────────────────────────────────────

class TestElyanCore:
    def setup_method(self):
        self.elyan = ElyanCore()

    @pytest.mark.asyncio
    async def test_handle_simple_chat(self):
        resp = await self.elyan.handle("merhaba", "telegram")
        assert resp.text

    @pytest.mark.asyncio
    async def test_handle_system_control(self):
        resp = await self.elyan.handle("Safari aç", "telegram")
        assert "system_control" in resp.metadata.get("intent", "")

    @pytest.mark.asyncio
    async def test_handle_approval_required(self):
        resp = await self.elyan.handle("terminalde rm komutu çalıştır", "telegram")
        assert resp.metadata.get("requires_approval") is True

    @pytest.mark.asyncio
    async def test_handle_returns_duration(self):
        resp = await self.elyan.handle("merhaba", "desktop")
        assert resp.duration_s >= 0
