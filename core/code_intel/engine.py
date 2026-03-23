"""
Code Intelligence Engine — Analysis, execution, security scanning, test generation.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from utils.logger import get_logger
from .ast_walker import walk_python, WalkResult

logger = get_logger("code_intel.engine")


@dataclass
class SecurityIssue:
    """Security issue found during scan."""
    severity: str  # low, medium, high, critical
    message: str
    line: Optional[int] = None
    pattern: str = ""


@dataclass
class CodeAnalysisResult:
    """Complete code analysis result."""
    success: bool
    text: str
    language: str = "python"
    functions: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    issues: List[dict] = field(default_factory=list)  # {severity, message, line}
    complexity: int = 0
    output: str = ""  # execution output
    raw: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# Security patterns to detect
DANGEROUS_PATTERNS = [
    (r"\beval\s*\(", "eval() — arbitrary code execution", "critical"),
    (r"\bexec\s*\(", "exec() — arbitrary code execution", "critical"),
    (r"\b__import__\s*\(", "__import__() — dynamic import", "critical"),
    (r"\bos\.system\s*\(", "os.system() — shell execution", "high"),
    (r"\bsubprocess\.call\s*\(", "subprocess.call() — external process", "high"),
]

SECRET_PATTERNS = [
    (r"(?:password|passwd|pwd)\s*=\s*['\"]", "Hardcoded password literal", "medium"),
    (r"(?:secret|api_key|apikey)\s*=\s*['\"]", "Hardcoded secret/key literal", "medium"),
    (r"(?:token|access_token)\s*=\s*['\"]", "Hardcoded token literal", "medium"),
]

SQL_PATTERNS = [
    (r"(?:SELECT|INSERT|UPDATE|DELETE)\s+.*?FROM.*?\+|%s|\$1", "Potential SQL injection", "high"),
]


class CodeEngine:
    """
    Code intelligence engine.
    - Analyze: AST extraction, complexity
    - Scan: Security pattern detection
    - Run: Code execution via SafeCodeExecutor
    - Test: Test generation (stub or LLM-assisted)
    """

    def __init__(self):
        self._executor = None
        self._load_executor()

    def _load_executor(self):
        """Load SafeCodeExecutor (lazy)."""
        try:
            from tools.code_execution_tools import SafeCodeExecutor
            self._executor = SafeCodeExecutor()
            logger.info("SafeCodeExecutor loaded")
        except ImportError as e:
            logger.warning(f"SafeCodeExecutor load failed: {e}")

    def analyze(self, code: str, language: str = "python") -> CodeAnalysisResult:
        """
        Static code analysis (no execution).

        Args:
            code: Source code string
            language: programming language (only python supported)

        Returns:
            CodeAnalysisResult with functions, classes, imports, complexity
        """
        if language.lower() != "python":
            return CodeAnalysisResult(
                success=False,
                text=f"Dil desteklenmiyor: {language}",
                language=language,
            )

        try:
            result = walk_python(code)

            if not result.success:
                return CodeAnalysisResult(
                    success=False,
                    text=f"Analiz başarısız: {result.error}",
                    language=language,
                    raw={"error": result.error},
                )

            text = f"Fonksiyonlar: {len(result.functions)}, Sınıflar: {len(result.classes)}, Karmaşıklık: {result.complexity}"

            return CodeAnalysisResult(
                success=True,
                text=text,
                language=language,
                functions=result.functions,
                classes=result.classes,
                imports=result.imports,
                complexity=result.complexity,
                raw={
                    "functions": result.functions,
                    "classes": result.classes,
                    "imports": result.imports,
                    "complexity": result.complexity,
                    "max_depth": result.max_depth,
                },
            )

        except Exception as e:
            logger.error(f"analyze failed: {e}")
            return CodeAnalysisResult(
                success=False,
                text=f"Hata: {e}",
                language=language,
            )

    def scan(self, code: str, language: str = "python") -> CodeAnalysisResult:
        """
        Security scanning (pattern-based, no execution).

        Args:
            code: Source code string
            language: programming language

        Returns:
            CodeAnalysisResult with security issues
        """
        if language.lower() != "python":
            return CodeAnalysisResult(
                success=False,
                text=f"Tarama dili desteklenmiyor: {language}",
                language=language,
            )

        issues = []
        lines = code.split("\n")

        # Scan dangerous patterns
        for pattern, msg, severity in DANGEROUS_PATTERNS:
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append({
                        "severity": severity,
                        "message": msg,
                        "line": i,
                        "pattern": pattern,
                    })

        # Scan secrets
        for pattern, msg, severity in SECRET_PATTERNS:
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append({
                        "severity": severity,
                        "message": msg,
                        "line": i,
                        "pattern": pattern,
                    })

        # Scan SQL injection
        for pattern, msg, severity in SQL_PATTERNS:
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append({
                        "severity": severity,
                        "message": msg,
                        "line": i,
                        "pattern": pattern,
                    })

        # Count issues by severity
        severity_counts = {}
        for issue in issues:
            sev = issue["severity"]
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        text = f"Bulunan sorun: {len(issues)} | " + ", ".join(
            f"{sev}: {count}" for sev, count in sorted(severity_counts.items())
        ) if issues else "Sorun bulunamadı ✓"

        return CodeAnalysisResult(
            success=True,
            text=text,
            language=language,
            issues=issues,
            raw={"issues": issues},
        )

    async def run(
        self,
        code: str,
        language: str = "python",
        timeout: int = 10,
    ) -> CodeAnalysisResult:
        """
        Execute code safely via SafeCodeExecutor.

        Args:
            code: Source code string
            language: python | shell
            timeout: execution timeout in seconds

        Returns:
            CodeAnalysisResult with execution output
        """
        if not self._executor:
            return CodeAnalysisResult(
                success=False,
                text="Kod yürütücü kullanılabilir değil",
                language=language,
            )

        try:
            if language.lower() == "python":
                from tools.code_execution_tools import execute_python_code
                result = await execute_python_code(code)
            elif language.lower() in {"shell", "bash", "sh"}:
                from tools.code_execution_tools import execute_shell_command
                result = await execute_shell_command(code)
            else:
                return CodeAnalysisResult(
                    success=False,
                    text=f"Dil desteklenmiyor: {language}",
                    language=language,
                )

            if result.get("success"):
                output = result.get("output", "")
                return CodeAnalysisResult(
                    success=True,
                    text="Yürütme başarılı",
                    language=language,
                    output=output,
                    raw=result,
                )
            else:
                return CodeAnalysisResult(
                    success=False,
                    text=f"Yürütme başarısız: {result.get('error', 'Unknown error')}",
                    language=language,
                    raw=result,
                )

        except Exception as e:
            logger.error(f"run failed: {e}")
            return CodeAnalysisResult(
                success=False,
                text=f"Hata: {e}",
                language=language,
            )

    async def generate_tests(
        self,
        code: str,
        language: str = "python",
        llm_client=None,
    ) -> CodeAnalysisResult:
        """
        Generate test cases for code.

        Args:
            code: Source code string
            language: python (only)
            llm_client: optional LLMClient for full test gen

        Returns:
            CodeAnalysisResult with test code
        """
        if language.lower() != "python":
            return CodeAnalysisResult(
                success=False,
                text=f"Dil desteklenmiyor: {language}",
                language=language,
            )

        # Step 1: Extract functions via AST
        analyze_result = self.analyze(code, language)
        if not analyze_result.success:
            return CodeAnalysisResult(
                success=False,
                text="Test üretimi için analiz başarısız",
                language=language,
            )

        functions = analyze_result.functions

        # Step 2: Generate stub tests
        stub_tests = ["import pytest\n\n"]
        for func in functions:
            stub_tests.append(f"def test_{func}():\n    \"\"\"Test {func}.\"\"\"\n    pass\n\n")

        test_code = "".join(stub_tests)

        # Step 3: If LLM available, enhance
        if llm_client:
            try:
                prompt = f"Generate pytest test cases for this Python code:\n\n{code}\n\nReturn complete, runnable test file."
                # Would call llm_client.call() here
                # For now, just return stubs
                pass
            except Exception as e:
                logger.warning(f"LLM test generation failed: {e}")

        return CodeAnalysisResult(
            success=True,
            text=f"Test şablonları oluşturuldu: {len(functions)} test",
            language=language,
            output=test_code,
            raw={"test_code": test_code, "function_count": len(functions)},
        )


__all__ = [
    "CodeEngine",
    "CodeAnalysisResult",
    "SecurityIssue",
]
