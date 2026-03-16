"""
tests/test_phase4_advanced_nlu.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4 Testing: Advanced NLU Engine
Tests for semantic analysis, entity extraction, ambiguity resolution.
─────────────────────────────────────────────────────────────────────────────
"""

import pytest
import asyncio
from core.advanced_nlu import (
    AdvancedNLU, SemanticAnalyzer, EntityExtractor, RelationshipMapper,
    AmbiguityResolver, ContextualIntentResolver, ErrorCorrectionEngine,
    Entity, ConfidenceEstimator
)


class TestSemanticAnalyzer:
    """Test semantic analysis."""

    def test_sentence_structure_detection(self):
        """Test sentence structure analysis."""
        analyzer = SemanticAnalyzer()

        # Test conditional detection
        result = analyzer.analyze_sentence_structure("if you run this then check results")
        assert result["has_conditional"] is True

        # Test question detection
        result = analyzer.analyze_sentence_structure("what should I do?")
        assert result["is_question"] is True

        # Test imperative detection
        result = analyzer.analyze_sentence_structure("create a file")
        assert result["is_imperative"] is True

        # Test negation detection
        result = analyzer.analyze_sentence_structure("do not delete this")
        assert result["has_negation"] is True

    def test_verb_extraction(self):
        """Test main verb extraction."""
        analyzer = SemanticAnalyzer()

        verbs = analyzer._extract_verbs("create a new file")
        assert "create" in verbs

        verbs = analyzer._extract_verbs("read the data and analyze it")
        assert "read" in verbs and "analyze" in verbs

    def test_semantic_frames(self):
        """Test semantic role labeling frames."""
        analyzer = SemanticAnalyzer()

        frames = analyzer.extract_semantic_frames("John reads a book", [])
        assert len(frames) > 0
        assert any(f.predicate == "reads" for f in frames)


class TestEntityExtractor:
    """Test entity recognition."""

    def test_email_extraction(self):
        """Test email entity extraction."""
        extractor = EntityExtractor()

        entities = extractor.extract("contact me at john@example.com")
        emails = [e for e in entities if e.type == "email"]
        assert len(emails) > 0
        assert emails[0].value == "john@example.com"

    def test_url_extraction(self):
        """Test URL entity extraction."""
        extractor = EntityExtractor()

        entities = extractor.extract("visit https://example.com for more")
        urls = [e for e in entities if e.type == "url"]
        assert len(urls) > 0

    def test_date_extraction(self):
        """Test date entity extraction."""
        extractor = EntityExtractor()

        entities = extractor.extract("meeting tomorrow at 2pm")
        dates = [e for e in entities if e.type == "date"]
        assert len(dates) > 0

    def test_number_extraction(self):
        """Test number entity extraction."""
        extractor = EntityExtractor()

        entities = extractor.extract("I need 42 items")
        numbers = [e for e in entities if e.type == "number"]
        assert len(numbers) > 0
        assert numbers[0].value == "42"

    def test_phone_extraction(self):
        """Test phone number extraction."""
        extractor = EntityExtractor()

        entities = extractor.extract("call me at 555-1234")
        phones = [e for e in entities if e.type == "phone"]
        assert len(phones) > 0


class TestRelationshipMapper:
    """Test relationship extraction."""

    def test_dependency_detection(self):
        """Test dependency relationship detection."""
        mapper = RelationshipMapper()

        relationships = mapper.extract_relationships("do this first then do that", [])
        assert len(relationships) > 0

    def test_causality_detection(self):
        """Test causality relationship detection."""
        mapper = RelationshipMapper()

        relationships = mapper.extract_relationships("it failed because the network was down", [])
        causality = [r for r in relationships if r.relation_type == "causality"]
        assert len(causality) > 0

    def test_temporal_detection(self):
        """Test temporal relationship detection."""
        mapper = RelationshipMapper()

        relationships = mapper.extract_relationships("when the file loads, check the size", [])
        temporal = [r for r in relationships if r.relation_type == "temporal"]
        assert len(temporal) > 0


class TestAmbiguityResolver:
    """Test ambiguity detection and resolution."""

    def test_multiple_objects_detection(self):
        """Test detection of multiple objects."""
        resolver = AmbiguityResolver()

        ambiguities = resolver.detect_ambiguities("copy file A and file B", [])
        assert len(ambiguities) > 0

    def test_unclear_reference_detection(self):
        """Test unclear pronoun references."""
        resolver = AmbiguityResolver()

        ambiguities = resolver.detect_ambiguities("it is located there", [])
        assert len(ambiguities) > 0

    def test_multiple_verbs_detection(self):
        """Test detection of multiple verbs."""
        resolver = AmbiguityResolver()

        ambiguities = resolver.detect_ambiguities("create and delete and modify items", [])
        assert len(ambiguities) > 0

    def test_clarification_suggestions(self):
        """Test clarification suggestions."""
        resolver = AmbiguityResolver()

        suggestions = resolver.suggest_clarifications(
            "unclear text",
            ["Multiple objects mentioned"]
        )
        assert len(suggestions) > 0


class TestErrorCorrectionEngine:
    """Test error correction."""

    def test_typo_correction(self):
        """Test typo correction."""
        engine = ErrorCorrectionEngine()

        corrected, note = engine.correct_errors("lsit all files")
        assert "list" in corrected

    def test_no_correction_needed(self):
        """Test text without errors."""
        engine = ErrorCorrectionEngine()

        corrected, note = engine.correct_errors("create a file")
        assert corrected == "create a file"
        assert note is None


class TestConfidenceEstimator:
    """Test confidence estimation."""

    @pytest.mark.asyncio
    async def test_confidence_calculation(self):
        """Test confidence score calculation."""
        estimator = ConfidenceEstimator()

        # Create a mock NLU result
        from core.advanced_nlu import NLUResult
        result = NLUResult(
            original_text="create a file",
            normalized_text="create a file",
            primary_intent="create",
            intent_type="action",
            confidence=0.8,
            entities=[Entity("verb", "create", 0, 6, 1.0)],
        )

        overall, factors = estimator.estimate(result)
        assert 0.0 <= overall <= 1.0
        assert "entity_coverage" in factors
        assert "semantic_structure" in factors


class TestAdvancedNLU:
    """Test complete NLU pipeline."""

    @pytest.mark.asyncio
    async def test_basic_analysis(self):
        """Test basic NLU analysis."""
        nlu = AdvancedNLU()

        result = await nlu.analyze("create a file named test.txt")
        assert result is not None
        assert "create" in result.primary_intent.lower()
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_complex_sentence(self):
        """Test analysis of complex sentence."""
        nlu = AdvancedNLU()

        result = await nlu.analyze(
            "if the file exists, read it and then analyze the content"
        )
        assert result.conditional_logic is not None
        assert len(result.entities) > 0

    @pytest.mark.asyncio
    async def test_error_correction_integration(self):
        """Test error correction in pipeline."""
        nlu = AdvancedNLU()

        result = await nlu.analyze("lsit all files")
        assert result.error_correction is not None

    @pytest.mark.asyncio
    async def test_nlu_performance(self):
        """Test NLU processing performance."""
        nlu = AdvancedNLU()

        result = await nlu.analyze("create and delete files")
        assert result.processing_time_ms < 500  # < 500ms requirement

    @pytest.mark.asyncio
    async def test_confidence_factors(self):
        """Test confidence factor breakdown."""
        nlu = AdvancedNLU()

        result = await nlu.analyze("update the database")
        assert len(result.confidence_factors) > 0
        assert result.confidence == sum(result.confidence_factors.values()) / len(result.confidence_factors) if result.confidence_factors else result.confidence

    def test_nlu_result_serialization(self):
        """Test NLU result to dict conversion."""
        from core.advanced_nlu import NLUResult

        result = NLUResult(
            original_text="test",
            normalized_text="test",
            primary_intent="test",
            intent_type="action",
            confidence=0.9,
        )

        result_dict = result.to_dict()
        assert result_dict["original_text"] == "test"
        assert result_dict["confidence"] == 0.9


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
