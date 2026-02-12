ALLOWED_COMMANDS = {
    "ls", "pwd", "whoami", "date", "cal", "uptime",
    "df", "du", "free", "top", "ps",
    "echo", "cat", "head", "tail", "wc",
    "find", "grep", "which", "hostname",
    "python3", "pip3", "node", "npm",
}

BLOCKED_PATTERNS = [
    "rm -rf", "rm -r", "mkfs", "dd if=",
    ":(){ :|:& };:", "fork", "> /dev/sd",
    "chmod 777", "wget", "curl", "nc ",
    "sudo", "su ", "passwd", "shadow",
    "/etc/passwd", "/etc/shadow",
    "eval", "exec", "`", "$(",
]

def is_command_allowed(command: str) -> tuple[bool, str]:
    command_lower = command.lower().strip()

    for pattern in BLOCKED_PATTERNS:
        if pattern in command_lower:
            return False, f"Blocked pattern detected: {pattern}"

    base_command = command_lower.split()[0] if command_lower else ""

    if base_command in ALLOWED_COMMANDS:
        return True, "OK"

    if base_command.endswith(".py"):
        return True, "OK"

    return False, f"Command not in whitelist: {base_command}"
