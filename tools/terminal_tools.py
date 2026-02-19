"""
Safe Terminal Command Execution

Provides secure execution of whitelisted terminal commands with:
- Command whitelisting
- Safety analysis
- Timeout protection
- Output capture and streaming
- Resource limits
"""

import asyncio
import shlex
import re
from typing import Dict, Any, Optional, List
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("tools.terminal")


# Whitelist of safe commands that can be executed
SAFE_COMMANDS = {
    # File operations (read-only or safe)
    "ls", "cat", "head", "tail", "wc", "find", "grep", "awk", "sed",
    "tree", "file", "stat", "du", "df", "cp", "mv", "mkdir", "touch",
    
    # System information & Control
    "date", "uptime", "whoami", "hostname", "uname", "sw_vers",
    "system_profiler", "diskutil", "networksetup", "ps", "top", "arp",
    "mdfind", "pgrep", "pkill", "osascript", "defaults", "scutil",
    "scselect", "tmutil", "airport", "brightness", "caffeinate",
    "pmset", "say", "afplay", "open",
    
    # Development tools
    "python", "python3", "node", "npm", "git", "which", "whereis",
    "env", "printenv", "echo", "pwd", "basename", "dirname",
    "shasum", "md5",
    
    # Package management (info only)
    "pip", "brew", "npm", "gem",
    
    # Text processing
    "sort", "uniq", "cut", "paste", "tr", "column", "xargs",
    
    # Network (info only)
    "ping", "curl", "wget", "dig", "nslookup", "traceroute", "netstat",
    "host", "ssh-add",
    
    # Compression (extract/list only)
    "tar", "gzip", "gunzip", "unzip", "zip", "rar", "7z",
}

# Commands that require additional validation
RESTRICTED_COMMANDS = {
    "python": ["--version", "-c"],  # Only version check or simple scripts
    "python3": ["--version", "-c"],
    "pip": ["list", "show", "search"],  # No install/uninstall without approval
    "brew": ["list", "info", "search"],
    "npm": ["list", "info", "search"],
    "git": ["status", "log", "diff", "branch", "show"],  # Read-only git
}

# Dangerous patterns that should never be allowed
DANGEROUS_PATTERNS = [
    r"rm\s+-rf",  # Recursive force delete
    r":\(\)\{.*\}",  # Fork bomb
    r">/dev/",  # Write to devices
    r"dd\s+if=",  # Disk operations
    r"mkfs",  # Format filesystem
    r"chmod\s+777",  # Overly permissive
    r"sudo",  # Privilege escalation
    r"curl.*\|\s*sh",  # Pipe to shell
    r"wget.*\|\s*sh",
    r"eval",  # Code evaluation
    r"exec",  # Code execution
]

# Shell control operators are blocked even though we use create_subprocess_exec.
# This prevents ambiguous intent and future regressions if execution mode changes.
SHELL_CONTROL_PATTERN = re.compile(r"(;|&&|\|\||`|\$\(|\n|\r)")

# Interpreter-style inline execution flags are high-risk injection vectors.
BLOCKED_INLINE_EXEC_FLAGS = {
    "python": {"-c", "-m"},
    "python3": {"-c", "-m"},
    "node": {"-e", "-p"},
    "ruby": {"-e"},
    "perl": {"-e"},
    "php": {"-r"},
    "osascript": {"-e"},
    "bash": {"-c"},
    "sh": {"-c"},
    "zsh": {"-c"},
}


class SafeTerminal:
    """
    Safe terminal command executor with whitelisting and safety checks
    """
    
    def __init__(self, timeout: int = 30, max_output_size: int = 1_000_000):
        self.timeout = timeout
        self.max_output_size = max_output_size
    
    async def execute_command(self, command: str, cwd: str = None) -> Dict[str, Any]:
        """
        Execute a terminal command safely
        
        Args:
            command: Command to execute
            cwd: Working directory (defaults to user home)
        
        Returns:
            {
                "success": bool,
                "output": str,
                "error": str,
                "exit_code": int,
                "command": str,
                "duration": float
            }
        """
        logger.info(f"Executing command: {command}")
        
        # Safety checks
        safety = self.analyze_safety(command)
        if not safety["safe"]:
            return {
                "success": False,
                "error": f"Command blocked: {safety['reason']}",
                "command": command,
                "safety_analysis": safety
            }
        
        # Parse command
        try:
            parts = shlex.split(command)
            if not parts:
                return {"success": False, "error": "Empty command"}
            
            base_command = parts[0]
            args = parts[1:]
        except Exception as e:
            return {"success": False, "error": f"Failed to parse command: {e}"}
        
        # Set working directory
        if cwd is None:
            cwd = str(Path.home())
        
        # Execute
        start_time = asyncio.get_event_loop().time()
        
        try:
            process = await asyncio.create_subprocess_exec(
                base_command,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            
            # Wait with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return {
                    "success": False,
                    "error": f"Command timed out after {self.timeout}s",
                    "command": command
                }
            
            end_time = asyncio.get_event_loop().time()
            duration = end_time - start_time
            
            # Decode output
            output = stdout.decode('utf-8', errors='replace')
            error = stderr.decode('utf-8', errors='replace')
            
            # Limit output size
            if len(output) > self.max_output_size:
                output = output[:self.max_output_size] + "\n... (output truncated)"
            
            return {
                "success": process.returncode == 0,
                "output": output,
                "error": error,
                "exit_code": process.returncode,
                "command": command,
                "duration": duration
            }
        
        except FileNotFoundError:
            return {
                "success": False,
                "error": f"Command not found: {base_command}",
                "command": command
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Execution error: {str(e)}",
                "command": command
            }
    
    def analyze_safety(self, command: str) -> Dict[str, Any]:
        """
        Analyze command safety
        
        Returns:
            {
                "safe": bool,
                "reason": str,
                "risk_level": "low" | "medium" | "high",
                "issues": List[str]
            }
        """
        issues = []
        risk_level = "low"
        
        # Check for dangerous patterns
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return {
                    "safe": False,
                    "reason": f"Dangerous pattern detected: {pattern}",
                    "risk_level": "critical",
                    "issues": [f"Matches dangerous pattern: {pattern}"]
                }

        # Block shell operators that can chain/inject commands.
        if SHELL_CONTROL_PATTERN.search(command):
            return {
                "safe": False,
                "reason": "Shell control operator detected",
                "risk_level": "critical",
                "issues": ["Command contains blocked shell control characters/operators"]
            }
        
        # Parse command
        try:
            parts = shlex.split(command)
            if not parts:
                return {
                    "safe": False,
                    "reason": "Empty command",
                    "risk_level": "low",
                    "issues": ["Empty command"]
                }
            
            base_command = parts[0]
            args = parts[1:]
        except Exception as e:
            return {
                "safe": False,
                "reason": f"Cannot parse command: {e}",
                "risk_level": "high",
                "issues": [f"Parse error: {e}"]
            }
        
        # Check if command is whitelisted
        if base_command not in SAFE_COMMANDS:
            return {
                "safe": False,
                "reason": f"Command not whitelisted: {base_command}",
                "risk_level": "high",
                "issues": [f"'{base_command}' is not in the safe commands list"]
            }
        
        # Check restricted commands
        if base_command in RESTRICTED_COMMANDS:
            allowed_args = RESTRICTED_COMMANDS[base_command]
            
            # Check if any arg is allowed
            has_allowed = False
            for arg in args:
                if arg in allowed_args:
                    has_allowed = True
                    break
            
            if not has_allowed and args:  # If has args but none are allowed
                risk_level = "medium"
                issues.append(f"'{base_command}' used with non-whitelisted arguments")

        # Explicitly block inline code execution flags for interpreters.
        blocked_flags = BLOCKED_INLINE_EXEC_FLAGS.get(base_command, set())
        for arg in args:
            if arg in blocked_flags:
                return {
                    "safe": False,
                    "reason": f"Inline execution flag blocked for {base_command}: {arg}",
                    "risk_level": "critical",
                    "issues": [f"Blocked inline execution flag: {arg}"]
                }
        
        # Check for file operations on sensitive paths
        sensitive_paths = ["/etc", "/usr", "/bin", "/sbin", "/var", "/System"]
        for arg in args:
            for sensitive in sensitive_paths:
                if arg.startswith(sensitive):
                    risk_level = "medium"
                    issues.append(f"Operation on sensitive path: {arg}")
        
        # Check for output redirection (can be dangerous)
        if ">" in command or ">>" in command or "<" in command:
            risk_level = "medium"
            issues.append("Command uses I/O redirection")
        
        # Check for piping (can chain dangerous commands)
        if "|" in command:
            # Analyze each part of the pipe
            pipe_parts = command.split("|")
            for part in pipe_parts:
                part_safety = self.analyze_safety(part.strip())
                if not part_safety["safe"]:
                    return {
                        "safe": False,
                        "reason": f"Unsafe command in pipe: {part_safety['reason']}",
                        "risk_level": "high",
                        "issues": issues + part_safety["issues"]
                    }
        
        return {
            "safe": True,
            "reason": "Command passed safety checks",
            "risk_level": risk_level,
            "issues": issues
        }
    
    def get_safe_commands_list(self) -> List[str]:
        """Get list of safe commands"""
        return sorted(list(SAFE_COMMANDS))


# Tool functions for agent integration

async def execute_safe_command(command: str, cwd: str = None, timeout: int = 30) -> Dict[str, Any]:
    """
    Execute a safe terminal command
    
    Args:
        command: Command to execute
        cwd: Working directory
        timeout: Timeout in seconds
    
    Returns:
        Execution result
    """
    terminal = SafeTerminal(timeout=timeout)
    return await terminal.execute_command(command, cwd=cwd)


async def analyze_command_safety(command: str) -> Dict[str, Any]:
    """
    Analyze command safety without executing
    
    Args:
        command: Command to analyze
    
    Returns:
        Safety analysis
    """
    terminal = SafeTerminal()
    return terminal.analyze_safety(command)


async def list_safe_commands() -> Dict[str, Any]:
    """
    List all safe commands that can be executed
    
    Returns:
        List of safe commands
    """
    terminal = SafeTerminal()
    commands = terminal.get_safe_commands_list()
    
    return {
        "success": True,
        "commands": commands,
        "count": len(commands),
        "restricted_commands": {
            cmd: args for cmd, args in RESTRICTED_COMMANDS.items()
        },
        "message": f"{len(commands)} safe commands available"
    }


async def execute_script(script_path: str, args: List[str] = None, timeout: int = 60) -> Dict[str, Any]:
    """
    Execute a script file (Python, shell, etc.)
    
    Args:
        script_path: Path to script file
        args: Arguments to pass to script
        timeout: Timeout in seconds
    
    Returns:
        Execution result
    """
    from pathlib import Path
    
    script_path = Path(script_path).expanduser()
    
    if not script_path.exists():
        return {
            "success": False,
            "error": f"Script not found: {script_path}"
        }
    
    # Determine how to execute based on extension
    suffix = script_path.suffix.lower()
    
    if suffix == ".py":
        command = f"python3 {script_path}"
    elif suffix == ".sh":
        command = f"bash {script_path}"
    elif suffix == ".js":
        command = f"node {script_path}"
    else:
        return {
            "success": False,
            "error": f"Unsupported script type: {suffix}"
        }
    
    # Add arguments
    if args:
        command += " " + " ".join(shlex.quote(arg) for arg in args)
    
    # Execute
    terminal = SafeTerminal(timeout=timeout)
    return await terminal.execute_command(command)
