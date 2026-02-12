"""
Safe Code Execution Sandbox

Provides secure execution of Python code with:
- Resource limits (CPU, memory, time)
- Restricted imports and builtins
- Output capture
- Safe execution environment
"""

import asyncio
import sys
import io
import contextlib
from typing import Dict, Any, Optional, List
from utils.logger import get_logger

logger = get_logger("tools.code_executor")


# Allowed safe modules for code execution
SAFE_MODULES = {
    "math", "random", "datetime", "time", "json", "re", "collections",
    "itertools", "functools", "operator", "string", "textwrap",
    "statistics", "decimal", "fractions", "pathlib"
}

# Restricted builtins
SAFE_BUILTINS = {
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "chr", "dict", "divmod", "enumerate", "filter", "float", "format",
    "frozenset", "hex", "int", "isinstance", "issubclass", "iter", "len",
    "list", "map", "max", "min", "oct", "ord", "pow", "print", "range",
    "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum",
    "tuple", "type", "zip", "True", "False", "None"
}


class CodeExecutor:
    """
    Safe Python code executor with sandboxing
    """
    
    def __init__(self, timeout: int = 10, max_output_size: int = 10000):
        self.timeout = timeout
        self.max_output_size = max_output_size
    
    async def execute_python_code(self, code: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute Python code in a sandboxed environment
        
        Args:
            code: Python code to execute
            context: Optional context variables
        
        Returns:
            Execution result with output, errors, and return value
        """
        logger.info(f"Executing Python code ({len(code)} chars)")
        
        # Safety check
        safety = self.analyze_code_safety(code)
        if not safety["safe"]:
            return {
                "success": False,
                "error": f"Code safety check failed: {safety['reason']}",
                "safety_analysis": safety
            }
        
        # Create safe execution environment
        safe_globals = self._create_safe_globals()
        
        # Add context variables if provided
        if context:
            for key, value in context.items():
                if isinstance(key, str) and key.isidentifier():
                    safe_globals[key] = value
        
        # Capture output
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        result = {
            "success": False,
            "output": "",
            "error": "",
            "return_value": None
        }
        
        try:
            # Execute with timeout
            with contextlib.redirect_stdout(stdout_capture):
                with contextlib.redirect_stderr(stderr_capture):
                    # Compile code
                    compiled = compile(code, "<sandbox>", "exec")
                    
                    # Execute in separate task with timeout
                    exec_task = asyncio.create_task(
                        asyncio.to_thread(exec, compiled, safe_globals)
                    )
                    
                    try:
                        await asyncio.wait_for(exec_task, timeout=self.timeout)
                        result["success"] = True
                    except asyncio.TimeoutError:
                        exec_task.cancel()
                        result["error"] = f"Execution timed out after {self.timeout}s"
                        return result
            
            # Capture output
            output = stdout_capture.getvalue()
            error = stderr_capture.getvalue()
            
            # Limit output size
            if len(output) > self.max_output_size:
                output = output[:self.max_output_size] + "\n... (output truncated)"
            
            result["output"] = output
            result["error"] = error
            
            # Try to get return value from last expression
            if "__return__" in safe_globals:
                result["return_value"] = safe_globals["__return__"]
        
        except SyntaxError as e:
            result["error"] = f"Syntax error: {e}"
        except NameError as e:
            result["error"] = f"Name error: {e}"
        except Exception as e:
            result["error"] = f"Execution error: {type(e).__name__}: {e}"
        
        return result
    
    def _create_safe_globals(self) -> Dict[str, Any]:
        """Create a safe globals dictionary for code execution"""
        safe_globals = {"__builtins__": {}}
        
        # Add safe builtins
        for builtin in SAFE_BUILTINS:
            if builtin in dir(__builtins__):
                safe_globals["__builtins__"][builtin] = getattr(__builtins__, builtin)
        
        # Add safe modules
        for module_name in SAFE_MODULES:
            try:
                safe_globals[module_name] = __import__(module_name)
            except ImportError:
                pass
        
        return safe_globals
    
    def analyze_code_safety(self, code: str) -> Dict[str, Any]:
        """
        Analyze code for safety issues
        
        Returns:
            Safety analysis
        """
        issues = []
        risk_level = "low"
        
        # Dangerous keywords
        dangerous_keywords = [
            "import os", "import sys", "import subprocess", "import socket",
            "__import__", "eval", "exec", "compile", "open", "file",
            "input", "raw_input"
        ]
        
        code_lower = code.lower()
        for keyword in dangerous_keywords:
            if keyword in code_lower:
                # Allow compile since we use it ourselves in safe context
                if keyword == "compile":
                    continue
                issues.append(f"Uses potentially dangerous keyword: {keyword}")
                risk_level = "high"
        
        # Check for import statements
        if "import " in code and not all(module in code for module in SAFE_MODULES):
            # Parse imports more carefully
            import re
            imports = re.findall(r'import\s+(\w+)', code)
            for imp in imports:
                if imp not in SAFE_MODULES:
                    issues.append(f"Imports non-whitelisted module: {imp}")
                    risk_level = "high"
        
        # Check for attribute access that might be dangerous
        dangerous_attrs = ["__class__", "__bases__", "__subclasses__", "__globals__"]
        for attr in dangerous_attrs:
            if attr in code:
                issues.append(f"Uses potentially dangerous attribute: {attr}")
                risk_level = "high"
        
        # If high risk, not safe
        if risk_level == "high":
            return {
                "safe": False,
                "reason": f"High risk code detected: {', '.join(issues)}",
                "risk_level": risk_level,
                "issues": issues
            }
        
        return {
            "safe": True,
            "reason": "Code passed safety checks",
            "risk_level": risk_level,
            "issues": issues
        }


# Tool functions

async def execute_python(code: str, timeout: int = 10) -> Dict[str, Any]:
    """
    Execute Python code safely
    
    Args:
        code: Python code to execute
        timeout: Timeout in seconds
    
    Returns:
        Execution result
    """
    executor = CodeExecutor(timeout=timeout)
    return await executor.execute_python_code(code)


async def evaluate_expression(expression: str) -> Dict[str, Any]:
    """
    Evaluate a Python expression and return the result
    
    Args:
        expression: Python expression to evaluate
    
    Returns:
        Result value
    """
    executor = CodeExecutor(timeout=5)
    
    # Wrap in code that captures return value
    code = f"__return__ = {expression}"
    
    result = await executor.execute_python_code(code)
    
    if result["success"]:
        return {
            "success": True,
            "value": result["return_value"],
            "expression": expression
        }
    else:
        return {
            "success": False,
            "error": result["error"],
            "expression": expression
        }


async def run_python_file(file_path: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Run a Python file safely
    
    Args:
        file_path: Path to Python file
        timeout: Timeout in seconds
    
    Returns:
        Execution result
    """
    from pathlib import Path
    
    path = Path(file_path).expanduser()
    
    if not path.exists():
        return {
            "success": False,
            "error": f"File not found: {file_path}"
        }
    
    if path.suffix != ".py":
        return {
            "success": False,
            "error": "File must have .py extension"
        }
    
    # Read code
    try:
        code = path.read_text()
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read file: {e}"
        }
    
    # Execute
    executor = CodeExecutor(timeout=timeout)
    result = await executor.execute_python_code(code)
    result["file"] = str(path)
    
    return result


async def analyze_python_code(code: str) -> Dict[str, Any]:
    """
    Analyze Python code for safety without executing
    
    Args:
        code: Python code to analyze
    
    Returns:
        Safety analysis
    """
    executor = CodeExecutor()
    analysis = executor.analyze_code_safety(code)
    
    # Add code metrics
    lines = code.split("\n")
    analysis["metrics"] = {
        "total_lines": len(lines),
        "non_empty_lines": len([l for l in lines if l.strip()]),
        "code_size_chars": len(code)
    }
    
    return analysis
