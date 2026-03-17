"""
Tests for Code Memory module
"""

import pytest
import tempfile
from core.code_memory import CodeMemory, CodePattern


class TestCodePattern:
    """Test CodePattern class"""

    def test_pattern_creation(self):
        pattern = CodePattern("p1", "Test Pattern", "code here", "python", "generic", ["test"])
        
        assert pattern.pattern_id == "p1"
        assert pattern.name == "Test Pattern"
        assert pattern.quality_score == 0.0

    def test_record_success(self):
        pattern = CodePattern("p1", "Test", "code", "python", "generic", [])
        pattern.record_usage(success=True)

        assert pattern.usage_count == 1
        assert pattern.success_count == 1

    def test_quality_score_update(self):
        pattern = CodePattern("p1", "Test", "code", "python", "generic", [])
        pattern.record_usage(success=True)
        pattern.record_usage(success=True)
        pattern.record_usage(success=False)

        assert pattern.quality_score == 2.0/3


class TestCodeMemory:
    """Test CodeMemory class"""

    @pytest.fixture
    def memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield CodeMemory(tmpdir)

    def test_initialization(self, memory):
        assert len(memory.patterns) == 0

    def test_store_solution(self, memory):
        pattern_id = memory.store_solution(
            task="Create a function",
            code="def my_func(): pass",
            quality_score=0.9,
            tags=["function", "simple"]
        )

        assert pattern_id is not None
        assert pattern_id in memory.patterns

    def test_find_similar_patterns(self, memory):
        memory.store_solution("Create function", "def f(): pass", 0.9, tags=["function"])
        memory.store_solution("Create class", "class C: pass", 0.85, tags=["class"])

        similar = memory.find_similar_patterns("function", limit=5)
        assert len(similar) > 0

    def test_get_user_style(self, memory):
        memory.store_solution("Code 1", "def f():\n    pass", 0.9)
        style = memory.get_user_style()

        assert "preferred_language" in style
        assert "indentation" in style

    def test_suggest_implementation(self, memory):
        memory.store_solution("Simple function", "def f(): pass", 0.9)
        suggestions = memory.suggest_implementation("function")

        assert isinstance(suggestions, list)

    def test_update_pattern_usage(self, memory):
        pattern_id = memory.store_solution("Task", "code", 0.9)
        memory.update_pattern_usage(pattern_id, success=True)

        assert memory.patterns[pattern_id].usage_count >= 1

    def test_get_statistics(self, memory):
        memory.store_solution("Code 1", "code1", 0.9)
        memory.store_solution("Code 2", "code2", 0.85)

        stats = memory.get_statistics()
        assert stats["total_patterns"] >= 2
