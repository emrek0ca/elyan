"""
Phase 6.3 — Code Intelligence — Test Suite (14 tests)
"""

import pytest
from unittest.mock import patch, AsyncMock

from core.code_intel import (
    get_code_engine,
    CodeAnalysisResult,
    format_text,
    format_json,
    format_md,
)


SAMPLE_PYTHON = """
import os
from pathlib import Path

def greet(name):
    return f"Hello {name}"

class Calculator:
    def add(self, a, b):
        if a < 0 or b < 0:
            return None
        return a + b

    def subtract(self, a, b):
        for i in range(10):
            if i == a:
                break
        while a > 0:
            a -= 1
        return a - b
"""

DANGEROUS_CODE = """
import os
eval("1+1")
exec("print('test')")
__import__("sys")
os.system("ls")
subprocess.call("cmd")
"""

SECRET_CODE = """
password = "secret123"
api_key = "key-xyz"
token = "token-abc"
"""


@pytest.fixture
def code_engine():
    """Get singleton CodeEngine."""
    return get_code_engine()


def test_code_engine_singleton():
    """Test: CodeEngine is singleton."""
    engine1 = get_code_engine()
    engine2 = get_code_engine()
    assert engine1 is engine2


def test_code_engine_init():
    """Test: CodeEngine initializes correctly."""
    engine = get_code_engine()
    assert engine is not None
    assert hasattr(engine, 'analyze')
    assert hasattr(engine, 'scan')
    assert hasattr(engine, 'run')
    assert hasattr(engine, 'generate_tests')


def test_analyze_functions_detected():
    """Test: AST extraction detects functions."""
    engine = get_code_engine()
    result = engine.analyze(SAMPLE_PYTHON)

    assert result.success
    assert "greet" in result.functions
    assert len(result.functions) >= 2  # greet + add + subtract


def test_analyze_classes_detected():
    """Test: AST extraction detects classes."""
    engine = get_code_engine()
    result = engine.analyze(SAMPLE_PYTHON)

    assert result.success
    assert "Calculator" in result.classes


def test_analyze_imports_detected():
    """Test: AST extraction detects imports."""
    engine = get_code_engine()
    result = engine.analyze(SAMPLE_PYTHON)

    assert result.success
    assert any("os" in imp for imp in result.imports)
    assert any("Path" in imp for imp in result.imports)


def test_complexity_calculation():
    """Test: Cyclomatic complexity counting."""
    engine = get_code_engine()
    result = engine.analyze(SAMPLE_PYTHON)

    assert result.success
    assert result.complexity > 0  # if, for, while statements


def test_scan_eval_detected_as_critical():
    """Test: eval() detected as critical."""
    engine = get_code_engine()
    result = engine.scan("eval('code')")

    assert result.success
    assert len(result.issues) > 0
    assert any(issue["severity"] == "critical" for issue in result.issues)
    assert any("eval" in issue["message"].lower() for issue in result.issues)


def test_scan_hardcoded_secret_detected():
    """Test: Hardcoded secrets detected."""
    engine = get_code_engine()
    result = engine.scan(SECRET_CODE)

    assert result.success
    assert len(result.issues) > 0
    # Should have password, api_key, token detections
    assert any("password" in issue["message"].lower() for issue in result.issues)


def test_scan_clean_code_no_issues():
    """Test: Clean code returns no issues."""
    engine = get_code_engine()
    result = engine.scan("def hello():\n    return 'world'")

    assert result.success
    assert len(result.issues) == 0
    assert "Sorun bulunamadı" in result.text


def test_scan_severity_filter():
    """Test: Issues have proper severity levels."""
    engine = get_code_engine()
    result = engine.scan(DANGEROUS_CODE)

    assert result.success
    assert len(result.issues) > 0

    for issue in result.issues:
        assert issue.get("severity") in {"low", "medium", "high", "critical"}
        assert issue.get("message")


@pytest.mark.asyncio
async def test_run_python_success(code_engine):
    """Test: Code execution (mocked)."""
    with patch("tools.code_execution_tools.execute_python_code") as mock_exec:
        mock_exec.return_value = {
            "success": True,
            "output": "Test output",
            "return_code": 0,
        }

        result = await code_engine.run("print('test')", "python")

        assert result.success
        assert result.output == "Test output"


@pytest.mark.asyncio
async def test_run_timeout_respected(code_engine):
    """Test: Timeout is passed to executor."""
    with patch("tools.code_execution_tools.execute_python_code") as mock_exec:
        mock_exec.return_value = {"success": True, "output": "", "return_code": 0}

        await code_engine.run("print('x')", "python", timeout=5)

        mock_exec.assert_called_once()


@pytest.mark.asyncio
async def test_run_shell(code_engine):
    """Test: Shell command execution (mocked)."""
    with patch("tools.code_execution_tools.execute_shell_command") as mock_exec:
        mock_exec.return_value = {
            "success": True,
            "output": "shell output",
            "return_code": 0,
        }

        result = await code_engine.run("echo test", "shell")

        assert result.success
        assert result.output == "shell output"


@pytest.mark.asyncio
async def test_generate_tests(code_engine):
    """Test: Test generation (stubs)."""
    result = await code_engine.generate_tests(SAMPLE_PYTHON)

    assert result.success
    assert result.output  # Has test code
    assert "def test_" in result.output
    assert "pytest" in result.output


# ────────────────────────────────────────────────────────────────────────────
# Formatter Tests
# ────────────────────────────────────────────────────────────────────────────

def test_format_text():
    """Test: text formatter."""
    result = CodeAnalysisResult(
        success=True,
        text="Analysis complete",
        functions=["foo", "bar"],
        complexity=2,
    )

    output = format_text(result)
    assert "foo" in output
    assert "bar" in output
    assert "2" in output


def test_format_json():
    """Test: JSON formatter produces valid JSON."""
    import json as json_lib
    result = CodeAnalysisResult(
        success=True,
        text="Test result",
        functions=["test_func"],
        complexity=1,
    )

    output = format_json(result)
    data = json_lib.loads(output)

    assert data["success"]
    assert data["text"] == "Test result"
    assert "test_func" in data["functions"]


def test_format_md():
    """Test: Markdown formatter has header."""
    result = CodeAnalysisResult(
        success=True,
        text="Markdown test",
        functions=["func1"],
        classes=["Class1"],
        complexity=3,
    )

    output = format_md(result)
    assert "#" in output
    assert "func1" in output
    assert "Class1" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
