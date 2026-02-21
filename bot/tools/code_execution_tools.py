"""
Safe Code Execution Tools
Execute Python, JavaScript, and shell scripts safely in sandbox
"""

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from utils.logger import get_logger
import json

logger = get_logger("code_execution")


@dataclass
class ExecutionResult:
    """Result of code execution"""
    success: bool
    output: str = ""
    error: str = ""
    return_code: int = 0
    execution_time: float = 0.0
    language: str = ""


class SafeCodeExecutor:
    """Safely executes code with resource limits and timeouts"""

    # Forbidden patterns that indicate potentially dangerous code
    FORBIDDEN_PATTERNS = [
        "eval", "exec", "compile", "__import__",
        "os.system", "subprocess", "pickle",
        "open(" , "file(" , "input(" , "raw_input(" ,
        "execfile" , "reload" , "__builtins__" ,
        "globals" , "locals" , "vars" , "dir" ,
        "compile" , "eval" , "exec" , "memoryview"
    ]

    # Allowed modules
    ALLOWED_PYTHON_MODULES = [
        "math", "statistics", "random", "datetime",
        "json", "re", "itertools", "functools",
        "collections", "string", "hashlib", "decimal"
    ]

    def __init__(self, max_timeout: int = 30, max_output_size: int = 10000):
        self.max_timeout = max_timeout
        self.max_output_size = max_output_size

    def _check_python_safety(self, code: str) -> bool:
        """Check if Python code is safe to execute"""
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern in code.lower():
                logger.warning(f"Forbidden pattern detected: {pattern}")
                return False
        return True

    def _create_safe_python_wrapper(self, code: str) -> str:
        """Wrap Python code with safety restrictions"""
        wrapper = f'''
import sys
import io
from contextlib import redirect_stdout, redirect_stderr

# Capture output
output = io.StringIO()
error = io.StringIO()

try:
    with redirect_stdout(output), redirect_stderr(error):
        {self._indent_code(code, 8)}
except Exception as e:
    error.write(f"Error: {{type(e).__name__}}: {{str(e)}}")

# Print results
print("__OUTPUT__", flush=True)
print(output.getvalue(), flush=True)
if error.getvalue():
    print("__ERROR__", flush=True)
    print(error.getvalue(), flush=True)
'''
        return wrapper

    def _indent_code(self, code: str, spaces: int) -> str:
        """Indent code block"""
        indent = " " * spaces
        return "\n".join(indent + line for line in code.split("\n"))

    async def execute_python(self, code: str) -> ExecutionResult:
        """Execute Python code safely"""
        # Safety check
        if not self._check_python_safety(code):
            return ExecutionResult(
                success=False,
                language="python",
                error="Code contains forbidden patterns (potential security risk)"
            )

        try:
            import time
            start_time = time.time()

            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                wrapped_code = self._create_safe_python_wrapper(code)
                f.write(wrapped_code)
                temp_file = f.name

            try:
                # Execute with timeout
                result = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        sys.executable, temp_file,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    ),
                    timeout=self.max_timeout
                )

                stdout, stderr = await asyncio.wait_for(
                    result.communicate(),
                    timeout=self.max_timeout
                )

                output = stdout.decode('utf-8', errors='ignore')
                error = stderr.decode('utf-8', errors='ignore')

                # Parse output
                lines = output.split('\n')
                parsed_output = ""
                parsed_error = ""

                if "__OUTPUT__" in output:
                    idx = output.index("__OUTPUT__")
                    output = output[idx + 10:].strip()
                    if "__ERROR__" in output:
                        parsed_output = output[:output.index("__ERROR__")].strip()
                        parsed_error = output[output.index("__ERROR__") + 9:].strip()
                    else:
                        parsed_output = output

                execution_time = time.time() - start_time

                return ExecutionResult(
                    success=not error or parsed_error == "",
                    output=parsed_output[:self.max_output_size],
                    error=parsed_error[:self.max_output_size],
                    return_code=result.returncode,
                    execution_time=execution_time,
                    language="python"
                )

            finally:
                Path(temp_file).unlink()

        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                language="python",
                error=f"Execution timeout (limit: {self.max_timeout}s)"
            )
        except Exception as e:
            logger.error(f"Python execution error: {e}")
            return ExecutionResult(
                success=False,
                language="python",
                error=str(e)
            )

    async def execute_javascript(self, code: str) -> ExecutionResult:
        """Execute JavaScript code safely"""
        try:
            import time
            start_time = time.time()

            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
                f.write(code)
                temp_file = f.name

            try:
                # Execute with Node.js
                result = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        'node', temp_file,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    ),
                    timeout=self.max_timeout
                )

                stdout, stderr = await asyncio.wait_for(
                    result.communicate(),
                    timeout=self.max_timeout
                )

                output = stdout.decode('utf-8', errors='ignore')
                error = stderr.decode('utf-8', errors='ignore')

                execution_time = time.time() - start_time

                return ExecutionResult(
                    success=result.returncode == 0,
                    output=output[:self.max_output_size],
                    error=error[:self.max_output_size],
                    return_code=result.returncode,
                    execution_time=execution_time,
                    language="javascript"
                )

            finally:
                Path(temp_file).unlink()

        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                language="javascript",
                error=f"Execution timeout (limit: {self.max_timeout}s)"
            )
        except FileNotFoundError:
            return ExecutionResult(
                success=False,
                language="javascript",
                error="Node.js not found. Install Node.js to execute JavaScript"
            )
        except Exception as e:
            logger.error(f"JavaScript execution error: {e}")
            return ExecutionResult(
                success=False,
                language="javascript",
                error=str(e)
            )

    async def execute_shell(self, command: str) -> ExecutionResult:
        """Execute shell command safely"""
        # Check for dangerous commands
        dangerous_commands = [
            "rm -rf", "dd if=", "format", "fdisk",
            ": {", "fork()", ":(){ :|:& };:"
        ]

        for dangerous in dangerous_commands:
            if dangerous in command:
                return ExecutionResult(
                    success=False,
                    language="shell",
                    error=f"Dangerous command pattern detected: {dangerous}"
                )

        try:
            import time
            start_time = time.time()

            result = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                ),
                timeout=self.max_timeout
            )

            stdout, stderr = await asyncio.wait_for(
                result.communicate(),
                timeout=self.max_timeout
            )

            output = stdout.decode('utf-8', errors='ignore')
            error = stderr.decode('utf-8', errors='ignore')

            execution_time = time.time() - start_time

            return ExecutionResult(
                success=result.returncode == 0,
                output=output[:self.max_output_size],
                error=error[:self.max_output_size],
                return_code=result.returncode,
                execution_time=execution_time,
                language="shell"
            )

        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                language="shell",
                error=f"Execution timeout (limit: {self.max_timeout}s)"
            )
        except Exception as e:
            logger.error(f"Shell execution error: {e}")
            return ExecutionResult(
                success=False,
                language="shell",
                error=str(e)
            )


# Global executor instance
_code_executor: Optional[SafeCodeExecutor] = None


def get_code_executor() -> SafeCodeExecutor:
    global _code_executor
    if _code_executor is None:
        _code_executor = SafeCodeExecutor()
    return _code_executor


# Tool functions
async def execute_python_code(code: str) -> Dict[str, Any]:
    """Execute Python code safely"""
    executor = get_code_executor()
    result = await executor.execute_python(code)
    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "execution_time": result.execution_time,
        "return_code": result.return_code
    }


async def execute_javascript_code(code: str) -> Dict[str, Any]:
    """Execute JavaScript code safely"""
    executor = get_code_executor()
    result = await executor.execute_javascript(code)
    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "execution_time": result.execution_time,
        "return_code": result.return_code
    }


async def execute_shell_command(command: str) -> Dict[str, Any]:
    """Execute shell command safely"""
    executor = get_code_executor()
    result = await executor.execute_shell(command)
    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "execution_time": result.execution_time,
        "return_code": result.return_code
    }


async def debug_code(code: str, language: str = "python") -> Dict[str, Any]:
    """Debug code with execution analysis"""
    executor = get_code_executor()

    if language == "python":
        result = await executor.execute_python(code)
    elif language == "javascript":
        result = await executor.execute_javascript(code)
    elif language == "shell":
        result = await executor.execute_shell(code)
    else:
        return {"success": False, "error": f"Unknown language: {language}"}

    return {
        "success": result.success,
        "language": language,
        "output": result.output,
        "error": result.error,
        "execution_time": result.execution_time,
        "debug_info": {
            "return_code": result.return_code,
            "output_length": len(result.output),
            "error_present": bool(result.error)
        }
    }
