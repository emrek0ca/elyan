"""
Autonomous Coding Agent - OpenClaw Component
Generates, reviews, and optimizes code with quality gates
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class CodeQualityResult:
    """Result of code quality analysis"""
    complexity_score: float  # 0-100, lower is better
    test_coverage: float     # 0-100
    security_issues: List[str]
    performance_issues: List[str]
    style_issues: List[str]
    overall_score: float
    passed_gates: bool


@dataclass
class CodeGeneration:
    """Generated code with metadata"""
    code: str
    language: str
    description: str
    quality_result: CodeQualityResult
    generated_at: str
    model_used: str
    confidence: float
    improvements_suggested: List[str]


class AutonomousCodingAgent:
    """Agent for autonomous code generation and review"""

    def __init__(self, llm_client=None, validators=None):
        self.llm_client = llm_client
        self.validators = validators or {}
        self.quality_gates = {
            "complexity": 0.7,      # Max complexity score
            "test_coverage": 0.8,   # Min coverage percentage
            "security": 0,          # Max security issues
            "performance": 2        # Max performance issues
        }
        self.generated_code_history: List[CodeGeneration] = []

    def generate_code(self, task_description: str, context: Dict = None) -> CodeGeneration:
        """Generate code for a task"""
        try:
            context = context or {}

            # Build prompt
            prompt = self._build_generation_prompt(task_description, context)

            # Call LLM
            if not self.llm_client:
                # Fallback: return template
                return self._generate_template_code(task_description)

            response = self.llm_client.call(prompt)
            code = self._extract_code(response)

            # Run quality gates
            quality_result = self.analyze_code_quality(code)

            # Generate
            generation = CodeGeneration(
                code=code,
                language=self._detect_language(code),
                description=task_description,
                quality_result=quality_result,
                generated_at=datetime.now().isoformat(),
                model_used="elyan-v1",
                confidence=self._calculate_confidence(quality_result),
                improvements_suggested=self._suggest_improvements(code, quality_result)
            )

            self.generated_code_history.append(generation)
            return generation

        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            generation = CodeGeneration(
                code="",
                language="python",
                description=task_description,
                quality_result=CodeQualityResult(0, 0, [str(e)], [], [], 0, False),
                generated_at=datetime.now().isoformat(),
                model_used="error",
                confidence=0.0,
                improvements_suggested=[f"Error: {e}"]
            )

    def _build_generation_prompt(self, task: str, context: Dict) -> str:
        """Build LLM prompt for code generation"""
        return f"""
        Generate high-quality, well-tested code for the following task:
        
        Task: {task}
        
        Context: {json.dumps(context)}
        
        Requirements:
        - Write clean, maintainable code
        - Include error handling
        - Add comments for complex logic
        - Design for testability
        - Follow best practices
        
        Format: Wrap code in ```python ... ``` blocks
        """

    def _extract_code(self, response: str) -> str:
        """Extract code blocks from LLM response"""
        import re
        pattern = r'```(?:python|javascript|typescript|java|golang|rust)?\n(.*?)\n```'
        matches = re.findall(pattern, response, re.DOTALL)
        if matches:
            return matches[0]
        return response

    def _detect_language(self, code: str) -> str:
        """Detect programming language"""
        if "def " in code or "import " in code:
            return "python"
        elif "function " in code or "const " in code:
            return "javascript"
        elif "class " in code and "java" in code.lower():
            return "java"
        return "unknown"

    def analyze_code_quality(self, code: str) -> CodeQualityResult:
        """Analyze code quality"""
        try:
            complexity_score = self._calculate_complexity(code)
            test_coverage = self._estimate_test_coverage(code)
            security_issues = self._scan_security(code)
            performance_issues = self._identify_performance_issues(code)
            style_issues = self._check_style(code)

            overall_score = (
                (100 - complexity_score) * 0.3 +
                test_coverage * 0.3 +
                (100 - len(security_issues) * 20) * 0.2 +
                (100 - len(performance_issues) * 15) * 0.2
            )
            overall_score = max(0, min(100, overall_score))

            passed_gates = (
                complexity_score <= self.quality_gates["complexity"] * 100 and
                test_coverage >= self.quality_gates["test_coverage"] * 100 and
                len(security_issues) <= self.quality_gates["security"] and
                len(performance_issues) <= self.quality_gates["performance"]
            )

            return CodeQualityResult(
                complexity_score=complexity_score,
                test_coverage=test_coverage,
                security_issues=security_issues,
                performance_issues=performance_issues,
                style_issues=style_issues,
                overall_score=overall_score,
                passed_gates=passed_gates
            )

        except Exception as e:
            logger.error(f"Quality analysis failed: {e}")
            return CodeQualityResult(0, 0, [str(e)], [], [], 0, False)

    def _calculate_complexity(self, code: str) -> float:
        """Calculate cyclomatic complexity (simplified)"""
        complexity = 1.0
        complexity += code.count("if ") * 0.5
        complexity += code.count("for ") * 0.3
        complexity += code.count("while ") * 0.3
        complexity += code.count("try ") * 0.2
        return min(100, complexity * 10)

    def _estimate_test_coverage(self, code: str) -> float:
        """Estimate test coverage"""
        # Check for test files or test cases in code
        test_indicators = code.count("def test_") + code.count("def describe")
        total_functions = code.count("def ") + code.count("function ")
        if total_functions == 0:
            return 0
        return min(100, (test_indicators / total_functions) * 100)

    def _scan_security(self, code: str) -> List[str]:
        """Scan for security issues - with ReDoS protection"""
        issues = []
        # Use simple, safe patterns to avoid ReDoS attacks
        security_patterns = {
            "SQL Injection": (r"execute\s*\(.*['\"]", "execute() with string concatenation"),
            "Hard-coded credentials": (r"password\s*=\s*['\"]", "Hard-coded password"),
            "Insecure hash": (r"\b(md5|sha1)\b", "Use of weak hash (MD5/SHA1)"),
            "No input validation": (r"eval\s*\(|exec\s*\(", "Use of eval/exec"),
        }

        for issue, (pattern, description) in security_patterns.items():
            try:
                # Use a simple substring check first for common patterns
                if issue == "Hard-coded credentials" and "password = '" in code:
                    issues.append(description)
                elif issue == "Insecure hash":
                    if ".md5(" in code or ".sha1(" in code:
                        issues.append(description)
                elif issue == "No input validation":
                    if "eval(" in code or "exec(" in code:
                        issues.append(description)
                elif issue == "SQL Injection":
                    if "execute(" in code and ("' +" in code or '" +' in code):
                        issues.append(description)
            except Exception as e:
                logger.warning(f"Security pattern check failed for {issue}: {e}")

        return issues

    def _identify_performance_issues(self, code: str) -> List[str]:
        """Identify performance issues"""
        issues = []
        if code.count("for ") > 3:
            issues.append("Possible nested loops causing O(n²) complexity")
        if "sleep" in code:
            issues.append("Blocking sleep detected - use async")
        if "*..*" in code:
            issues.append("Possible regex performance issue")
        return issues

    def _check_style(self, code: str) -> List[str]:
        """Check code style"""
        issues = []
        if len(code.split("\n")) > 500:
            issues.append("Function too long")
        if code.count("TODO") > 0:
            issues.append(f"Found {code.count('TODO')} TODO comments")
        return issues

    def _calculate_confidence(self, quality: CodeQualityResult) -> float:
        """Calculate confidence in generated code"""
        if quality.passed_gates:
            return min(0.95, 0.5 + (quality.overall_score / 100) * 0.45)
        return max(0.1, quality.overall_score / 200)

    def _suggest_improvements(self, code: str, quality: CodeQualityResult) -> List[str]:
        """Suggest code improvements"""
        suggestions = []

        if quality.complexity_score > 50:
            suggestions.append("Refactor to reduce complexity")
        if quality.test_coverage < 80:
            suggestions.append("Add more unit tests")
        if quality.security_issues:
            suggestions.extend([f"Fix: {issue}" for issue in quality.security_issues])
        if quality.performance_issues:
            suggestions.extend([f"Optimize: {issue}" for issue in quality.performance_issues])

        return suggestions

    def self_review_code(self, code: str) -> Dict[str, Any]:
        """Self-review generated code"""
        try:
            quality = self.analyze_code_quality(code)
            recommendations = []

            if not quality.passed_gates:
                recommendations.extend([
                    "Review security scan results",
                    "Improve test coverage",
                    "Reduce complexity"
                ])

            return {
                "quality": {
                    "overall_score": quality.overall_score,
                    "complexity": quality.complexity_score,
                    "test_coverage": quality.test_coverage,
                    "security_issues": quality.security_issues,
                    "passed_gates": quality.passed_gates
                },
                "recommendations": recommendations,
                "ready_for_production": quality.passed_gates
            }

        except Exception as e:
            logger.error(f"Self-review failed: {e}")
            return {"error": str(e)}

    def generate_tests(self, code: str) -> List[str]:
        """Generate unit tests for code"""
        try:
            tests = []

            # Extract functions
            if "def " in code:
                import re
                functions = re.findall(r'def (\w+)\(', code)
                for func in functions:
                    if not func.startswith("_"):
                        test = f"def test_{func}():\n    assert {func}() is not None"
                        tests.append(test)

            return tests if tests else ["def test_example(): assert True"]

        except Exception as e:
            logger.error(f"Test generation failed: {e}")
            return ["def test_example(): assert True"]

    def optimize_code(self, code: str) -> Dict[str, Any]:
        """Optimize code for performance"""
        try:
            optimizations = []

            if code.count("for ") > 1:
                optimizations.append({
                    "type": "vectorization",
                    "suggestion": "Use list comprehension or vectorized operations"
                })

            if "sleep" in code:
                optimizations.append({
                    "type": "async",
                    "suggestion": "Use async/await instead of blocking sleep"
                })

            return {
                "optimizations": optimizations,
                "estimated_speedup": 1.0 + len(optimizations) * 0.2
            }

        except Exception as e:
            logger.error(f"Code optimization failed: {e}")
            return {"error": str(e)}

    def scan_security(self, code: str) -> Dict[str, Any]:
        """Security scan for code"""
        issues = self._scan_security(code)
        return {
            "security_issues": issues,
            "severity_level": "high" if len(issues) > 2 else "medium" if issues else "low",
            "recommendations": [
                "Use parameterized queries",
                "Store credentials in environment variables",
                "Use strong hashing algorithms (bcrypt, argon2)",
                "Validate all inputs"
            ] if issues else []
        }

    def _generate_template_code(self, description: str) -> CodeGeneration:
        """Generate template code when LLM unavailable"""
        template = f"""# Generated by Elyan
# Task: {description}

def main():
    '''Main entry point'''
    pass

if __name__ == "__main__":
    main()
"""
        quality = self.analyze_code_quality(template)
        return CodeGeneration(
            code=template,
            language="python",
            description=description,
            quality_result=quality,
            generated_at=datetime.now().isoformat(),
            model_used="template",
            confidence=0.5,
            improvements_suggested=["Complete the implementation"]
        )
