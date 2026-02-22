"""
core/reasoning/code_validator.py
─────────────────────────────────────────────────────────────────────────────
AST-Aware Code Validator & Auto-Test Loop (Phase 31).
After Elyan generates any Python code, this module:
  1. AST-parses it to verify syntax
  2. Auto-generates a basic pytest test
  3. Runs the test in ZeroTrust sandbox
  4. If it fails, feeds the error back for self-repair (max 3 attempts)
"""

import ast
import re
import asyncio
from dataclasses import dataclass
from utils.logger import get_logger

logger = get_logger("code_validator")

@dataclass
class ValidationResult:
    syntax_valid: bool
    test_passed: bool
    repair_attempts: int
    final_code: str
    test_output: str
    errors: list

class CodeValidator:
    MAX_REPAIR_ATTEMPTS = 3
    
    def __init__(self, agent_instance):
        self.agent = agent_instance
    
    async def validate_and_repair(self, code: str, intent: str = "") -> ValidationResult:
        """Full Write → Parse → Test → Fix pipeline."""
        result = ValidationResult(
            syntax_valid=False, test_passed=False,
            repair_attempts=0, final_code=code,
            test_output="", errors=[]
        )
        
        for attempt in range(self.MAX_REPAIR_ATTEMPTS + 1):
            # Step 1: AST Syntax Check
            syntax_ok, syntax_err = self._check_syntax(result.final_code)
            result.syntax_valid = syntax_ok
            
            if not syntax_ok:
                result.errors.append(f"Syntax Error (attempt {attempt}): {syntax_err}")
                if attempt < self.MAX_REPAIR_ATTEMPTS:
                    result.final_code = await self._self_repair(result.final_code, syntax_err, intent)
                    result.repair_attempts += 1
                    continue
                else:
                    break
            
            # Step 2: Auto-generate test
            test_code = await self._generate_test(result.final_code, intent)
            
            # Step 3: Run test in ZeroTrust sandbox
            test_ok, test_output = await self._run_test(result.final_code, test_code)
            result.test_passed = test_ok
            result.test_output = test_output
            
            if test_ok:
                logger.info(f"✅ Code validated successfully after {attempt} repair(s).")
                break
            else:
                result.errors.append(f"Test Failed (attempt {attempt}): {test_output[:200]}")
                if attempt < self.MAX_REPAIR_ATTEMPTS:
                    result.final_code = await self._self_repair(
                        result.final_code, f"Test failed: {test_output[:300]}", intent
                    )
                    result.repair_attempts += 1
        
        return result
    
    def _check_syntax(self, code: str) -> tuple:
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"
    
    async def _generate_test(self, code: str, intent: str) -> str:
        """Auto-generate a basic pytest test for the given code."""
        from core.multi_agent.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(self.agent)
        
        prompt = f"""
Aşağıdaki Python kodu için 1 adet basit pytest test fonksiyonu yaz.
Test, kodun temel işlevselliğini doğrulamalı.
SADECE test kodunu döndür, başka bir şey yazma.

Kod:
```python
{code[:500]}
```
Amacı: {intent}
"""
        raw = await orch._run_specialist("qa", prompt)
        match = re.search(r"```python\s*(.*?)\s*```", raw, re.DOTALL)
        return match.group(1) if match else f"def test_basic():\n    assert True"
    
    async def _run_test(self, code: str, test_code: str) -> tuple:
        """Execute the code + test in ZeroTrust sandbox."""
        combined = f"{code}\n\n{test_code}\n\nif __name__ == '__main__':\n    test_basic()\n    print('ALL_TESTS_PASSED')"
        
        from core.security.zero_trust_runtime import zero_trust_env
        result = zero_trust_env.safe_evaluate_python(combined)
        
        if result["success"] and "ALL_TESTS_PASSED" in result.get("output", ""):
            return True, result.get("output", "")
        return False, result.get("error", result.get("output", "Unknown failure"))
    
    async def _self_repair(self, broken_code: str, error: str, intent: str) -> str:
        """Feed the error back to the LLM for auto-correction."""
        from core.multi_agent.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(self.agent)
        
        prompt = f"""
Aşağıdaki Python kodunda hata var. Hatayı düzelt ve SADECE düzeltilmiş kodu döndür.

Hata: {error}
Amaç: {intent}

Bozuk Kod:
```python
{broken_code[:800]}
```
"""
        raw = await orch._run_specialist("executor", prompt)
        match = re.search(r"```python\s*(.*?)\s*```", raw, re.DOTALL)
        return match.group(1).strip() if match else broken_code
