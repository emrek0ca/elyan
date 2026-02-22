"""
core/multi_agent/tool_governance.py
─────────────────────────────────────────────────────────────────────────────
Self-Coding and Metaprogramming Governance.
Allows Elyan to author, test, and inject new Python tools into its own brain
dynamically without human developers.
"""

import os
import ast
import uuid
from typing import Dict, Any, Tuple
from pathlib import Path
from utils.logger import get_logger
from config.settings import ELYAN_DIR

logger = get_logger("tool_governance")

class SecurityViolationError(Exception):
    pass

class ToolGovernance:
    def __init__(self, agent_instance):
        self.agent = agent_instance
        self.tools_path = Path(__file__).parent.parent.parent / "tools" / "ai_authored"
        self.sandbox_path = ELYAN_DIR / "sandbox"
        
        self.tools_path.mkdir(parents=True, exist_ok=True)
        self.sandbox_path.mkdir(parents=True, exist_ok=True)
        
        # Ensure __init__.py exists for importability
        init_py = self.tools_path / "__init__.py"
        if not init_py.exists():
            init_py.touch()

    def _static_analysis(self, python_code: str) -> bool:
        """Jail check: Rejects malicious imports or os.system calls."""
        try:
            tree = ast.parse(python_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                    module = getattr(node, 'module', None) or node.names[0].name
                    if module in ["subprocess", "os", "sys", "shutil", "socket", "eval", "exec"]:
                        logger.error(f"Security Alert: Rejected tool import for '{module}'")
                        raise SecurityViolationError(f"Malicious module '{module}' blocked.")
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in ["eval", "exec", "open"]:
                        raise SecurityViolationError(f"Dangerous built-in '{node.func.id}' blocked.")
            return True
        except SyntaxError:
            logger.error("Generated tool has syntax errors.")
            return False

    async def execute_in_sandbox(self, python_code: str, test_payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Runs the code in a restricted execution loop to verify it functions."""
        sandbox_file = self.sandbox_path / f"test_{uuid.uuid4().hex[:8]}.py"
        
        # We append a simple test runner to the bottom of the AI code
        test_runner = f"""
import json
import asyncio

{python_code}

async def _elyan_sandbox_run():
    # Attempt to find the async function inside the tool
    payload = {json.dumps(test_payload)}
    # Hacky way to run the first async function defined in local namespace
    for name, obj in list(globals().items()):
        if name.startswith("_"): continue
        if asyncio.iscoroutinefunction(obj):
            try:
                result = await obj(**payload)
                print(f"EXPECTED_OUTPUT_MARKER_\\n{{json.dumps(result)}}")
                return
            except Exception as e:
                print(f"SANDBOX_ERR: {{e}}")
                return
    print("SANDBOX_ERR: No async tool entrypoint found.")

if __name__ == '__main__':
    asyncio.run(_elyan_sandbox_run())
"""
        sandbox_file.write_text(test_runner, encoding="utf-8")
        
        try:
            process = await asyncio.create_subprocess_exec(
                "python", str(sandbox_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            out = stdout.decode().strip()
            err = stderr.decode().strip()
            
            if "SANDBOX_ERR:" in out or process.returncode != 0:
                logger.warning(f"Sandbox run failed: {out} {err}")
                return False, f"Err: {out or err}"
                
            if "EXPECTED_OUTPUT_MARKER_" in out:
                result = out.split("EXPECTED_OUTPUT_MARKER_\\n")[-1]
                logger.info(f"Sandbox successful. Tool isolated output: {result[:50]}...")
                return True, result
            
            return False, "No valid output marker."
        finally:
            if sandbox_file.exists():
                os.remove(sandbox_file)

    async def author_and_inject_tool(self, intent: str, tool_name: str) -> bool:
        """
        AI generates Python code for a tool it lacks. We statically analyze it,
        sandbox it, and if it passes, inject it into the production Tools list permanently.
        """
        logger.info(f"🧠 Meta-Programming: Elyan requires a new tool: {tool_name}")
        
        prompt = f"""
SEN BİR YAPAY ZEKA MÜHENDİSİSİN.
BENDEN (SİSTEMDEN) ŞU YETENEĞİ İSTEDİN: '{intent}' (İsim: {tool_name})
GÖREV: Bu yeteneği yerine getirecek ASYNC ve SAFE bir Python fonksiyonu yaz.
Kısıtlamalar:
- Sadece `async def {tool_name}(**kwargs):` fonksiyon bloğunu dön.
- `os`, `subprocess` vb. sys yetkileri KULLANMA.
- Fonksiyon sadece bir dict dönmeli.
- Python Markdown Bloğu içinde dön.
"""
        # Run Builder for tool generation
        from core.multi_agent.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(self.agent)
        code_raw = await orch._run_specialist("executor", prompt)
        
        # Parse Markdowns
        import re
        match = re.search(r"```python\s*(.*?)\s*```", code_raw, re.DOTALL)
        if not match:
            logger.error(f"Meta-Programming failed. No python code generated for {tool_name}")
            return False
            
        python_code = match.group(1).strip()
        
        # 1. Static Audit
        try:
            if not self._static_analysis(python_code):
                return False
        except SecurityViolationError as e:
            logger.error(f"Blocked malicious tool generation: {e}")
            return False
            
        # 2. Sandbox Run (with empty payload for smoke test)
        passed, res = await self.execute_in_sandbox(python_code, {})
        if not passed:
            logger.error(f"Sandbox rejected {tool_name}. Failed execution.")
            return False
            
        # 3. Permanent Injection
        tool_file = self.tools_path / f"{tool_name}.py"
        tool_file.write_text(python_code, encoding="utf-8")
        logger.info(f"🎉 Meta-Programming Success! Injected new capability: {tool_name} at {tool_file}")
        
        # Load capability to current brain
        import importlib.util
        spec = importlib.util.spec_from_file_location(tool_name, str(tool_file))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        func = getattr(module, tool_name, None)
        if func:
            self.agent.register_tool(func)
            return True
            
        return False
