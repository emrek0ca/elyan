"""
Tests for Autonomous Coding Agent
"""

import pytest
from core.autonomous_coding_agent import AutonomousCodingAgent, CodeQualityResult


class TestAutonomousCodingAgent:
    """Test AutonomousCodingAgent class"""

    @pytest.fixture
    def agent(self):
        return AutonomousCodingAgent()

    def test_initialization(self, agent):
        assert agent.llm_client is None
        assert len(agent.generated_code_history) == 0

    def test_analyze_code_quality(self, agent):
        code = """
def hello():
    print("Hello")
"""
        result = agent.analyze_code_quality(code)

        assert isinstance(result.complexity_score, float)
        assert isinstance(result.test_coverage, float)
        assert isinstance(result.overall_score, float)

    def test_self_review_code(self, agent):
        code = "def test(): pass"
        review = agent.self_review_code(code)

        assert "quality" in review
        assert "recommendations" in review
        assert "ready_for_production" in review

    def test_generate_tests(self, agent):
        code = """
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
"""
        tests = agent.generate_tests(code)

        assert len(tests) > 0
        assert "test_" in tests[0]

    def test_optimize_code(self, agent):
        code = "for i in range(10): pass"
        optimization = agent.optimize_code(code)

        assert "optimizations" in optimization
        assert "estimated_speedup" in optimization

    def test_scan_security(self, agent):
        code = "password = 'secret123'"
        result = agent.scan_security(code)

        assert "security_issues" in result
        assert "recommendations" in result

    def test_complexity_calculation(self, agent):
        simple_code = "x = 1"
        simple_complexity = agent._calculate_complexity(simple_code)

        complex_code = "if x: \n  if y: \n    for i in range(10): pass"
        complex_complexity = agent._calculate_complexity(complex_code)

        assert complex_complexity > simple_complexity

    def test_language_detection(self, agent):
        python_code = "def hello(): pass"
        assert agent._detect_language(python_code) == "python"

        js_code = "const x = 1;"
        assert agent._detect_language(js_code) == "javascript"
