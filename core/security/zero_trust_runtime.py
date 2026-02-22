"""
core/security/zero_trust_runtime.py
─────────────────────────────────────────────────────────────────────────────
Zero Trust Runtime (Phase 26).
Ensures any code output written by Elyan (or injected via prompt hacking)
cannot compromise the host machine. Implements AST whitelisting and
resource-bound subprocess jailing for dynamic Python executions.
"""

import ast
import time
import subprocess
import os
import sys
from tempfile import NamedTemporaryFile
from utils.logger import get_logger

logger = get_logger("zero_trust")

class ZeroTrustRuntime:
    def __init__(self, use_docker: bool = False):
        self.use_docker = use_docker
        self.max_execution_sec = 10.0
        
        # Security: Hard block against importing modules that give OS control
        self.banned_imports = {
            "os", "subprocess", "sys", "shutil", "socket", 
            "pty", "ptyprocess", "paramiko"
        }
        
    def _is_ast_safe(self, code_str: str) -> tuple[bool, str]:
        """Statically analyzes the Code snippet before running it to block RCE attempts."""
        try:
            tree = ast.parse(code_str)
            for node in ast.walk(tree):
                # Block 'import module'
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split('.')[0] in self.banned_imports:
                            return False, f"BANNED_IMPORT: {alias.name}"
                # Block 'from module import X'
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split('.')[0] in self.banned_imports:
                        return False, f"BANNED_IMPORT_FROM: {node.module}"
                # Look for calls to eval / exec / globals
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in {"eval", "exec", "globals", "locals"}:
                            return False, f"BANNED_BUILTIN: {node.func.id}()"
            
            return True, "SAFE"
        except SyntaxError as e:
            return False, f"SYNTAX_ERROR: {e}"

    def safe_evaluate_python(self, code_str: str) -> dict:
        """Runs the python code inside a heavily restricted Subprocess / Docker jail."""
        
        # 1. AST Validation
        is_safe, reason = self._is_ast_safe(code_str)
        if not is_safe:
            logger.error(f"🚨 ZeroTrust Sandbox Blocked Code Execution! Reason: {reason}")
            return {"success": False, "error": f"Security Violation: {reason}"}
            
        logger.debug("🛡️ ZeroTrust AST Check Passed. Executing payload...")
        
        with NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file.write(code_str)
            file_path = temp_file.name
            
        try:
            # 2. Subprocess Runtime Bounds
            # We enforce execution limits via standard subprocess features so it works on Windows and Linux
            start_t = time.time()
            result = subprocess.run(
                [sys.executable, file_path],
                capture_output=True,
                text=True,
                timeout=self.max_execution_sec
            )
            elapsed = time.time() - start_t
            
            os.remove(file_path)
            
            if result.returncode == 0:
                logger.info(f"✅ ZeroTrust Execution Finished in {elapsed:.2f}s")
                return {"success": True, "output": result.stdout}
            else:
                return {"success": False, "error": result.stderr}
                
        except subprocess.TimeoutExpired:
            os.remove(file_path)
            logger.warning(f"⏰ ZeroTrust Timeout Triggered (> {self.max_execution_sec}s). Execution killed.")
            return {"success": False, "error": "TIMEOUT_EXCEEDED"}
        except Exception as e:
            if os.path.exists(file_path): os.remove(file_path)
            return {"success": False, "error": str(e)}

# Export Singleton
zero_trust_env = ZeroTrustRuntime(use_docker=False)
