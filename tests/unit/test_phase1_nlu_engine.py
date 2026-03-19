from __future__ import annotations

from core.nlu.phase1_engine import get_phase1_engine
from core.intent.tier2_semantic_classifier import SemanticClassifier
from core.intent_parser import IntentParser


def test_phase1_taxonomy_is_broad_enough():
    engine = get_phase1_engine()
    assert engine.describe()["taxonomy_size"] >= 30


def test_phase1_research_document_delivery_default():
    engine = get_phase1_engine()
    decision = engine.classify("PyTorch hakkında araştırma yap")
    assert decision is not None
    assert decision.intent == "research_document_delivery"
    assert decision.action == "research_document_delivery"
    assert decision.request_contract["content_kind"] == "research_delivery"
    assert decision.params.get("topic")


def test_phase1_word_document_routes_with_action_mapping():
    engine = get_phase1_engine()
    decision = engine.classify("word dosyası oluştur")
    assert decision is not None
    assert decision.intent == "create_word_document"
    assert decision.action == "write_word"
    assert decision.params["filename"].endswith(".docx")


def test_phase1_excel_routes_with_action_mapping():
    engine = get_phase1_engine()
    decision = engine.classify("excel tablo hazırla")
    assert decision is not None
    assert decision.intent == "create_excel"
    assert decision.action == "write_excel"
    assert decision.params["filename"].endswith(".xlsx")


def test_phase1_website_routes_to_coding_or_website_action():
    engine = get_phase1_engine()
    decision = engine.classify("bana bir portfolyo websitesi yap html css js ile yap")
    assert decision is not None
    assert decision.intent in {"create_website", "create_coding_project"}
    assert decision.action in {"create_web_project_scaffold", "create_coding_project"}


def test_phase1_ambiguous_request_asks_for_clarification():
    engine = get_phase1_engine()
    decision = engine.classify("bir belge hazırla")
    assert decision is not None
    assert decision.needs_clarification is True
    assert decision.clarification_question


def test_phase1_learns_from_correction():
    engine = get_phase1_engine()
    engine.learn_from_correction("özel py torç araştır", "research_document_delivery", {"topic": "pytorch"})
    decision = engine.classify("özel py torç araştır")
    assert decision is not None
    assert decision.intent == "research_document_delivery"


def test_phase1_semantic_search_returns_ranked_entries():
    engine = get_phase1_engine()
    results = engine.semantic_search("sunum hazırla")
    assert results
    assert results[0]["intent"] in {"create_presentation", "research_document_delivery"}


def test_semantic_classifier_uses_phase1_without_llm():
    classifier = SemanticClassifier()
    tools = {
        "write_word": {"description": "write a word document"},
        "write_excel": {"description": "write an excel document"},
        "chat": {"description": "chat"},
    }
    candidate = classifier.classify("word dosyası oluştur", tools)
    assert candidate is not None
    assert candidate.action == "write_word"
    assert candidate.source_tier in {"phase1", "tier2"}


def test_intent_parser_phase1_fallback_still_returns_parser_dict():
    parser = IntentParser()
    result = parser.parse("unknown ama rapor hazırla")
    assert isinstance(result, dict)
    assert "action" in result
