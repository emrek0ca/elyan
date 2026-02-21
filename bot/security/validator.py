import re
from pathlib import Path
from config.settings import PROJECT_ROOT, ALLOWED_DIRECTORIES, HOME_DIR, FULL_DISK_ACCESS

def expand_path(path_str: str) -> Path:
    if path_str.startswith("~"):
        path_str = str(HOME_DIR) + path_str[1:]
    return Path(path_str).expanduser().resolve()

def validate_path(path_str: str) -> tuple[bool, str, Path | None]:
    try:
        path = expand_path(path_str)

        sensitive = [
            ".ssh", ".gnupg", ".aws", "Keychain", ".credentials",
            "Library/Keychains", "Library/Mail/V10/MailData"
        ]
        if any(s in str(path) for s in sensitive):
            return False, f"Hassas dizine erişim engellendi: {path}", None

        if FULL_DISK_ACCESS:
            return True, "OK", path

        for allowed in ALLOWED_DIRECTORIES:
            allowed_resolved = allowed.resolve()
            try:
                path.relative_to(allowed_resolved)
                return True, "OK", path
            except ValueError:
                continue

        if HOME_DIR.resolve() in path.parents or path == HOME_DIR.resolve():
            return True, "OK", path

        return False, f"Bu dizine erişim izni yok: {path}", None

    except Exception as e:
        return False, f"Geçersiz yol: {str(e)}", None

def validate_input(user_input: str) -> tuple[bool, str]:
    if not user_input or not user_input.strip():
        return False, "Boş girdi"

    if len(user_input) > 4000:
        return False, "Girdi çok uzun (max 4000 karakter)"

    return True, "OK"

def sanitize_input(user_input: str) -> str:
    sanitized = user_input.strip()
    sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', sanitized)
    return sanitized

def is_safe_content(content: str) -> tuple[bool, str]:
    dangerous_patterns = [
        r"rm\s+-rf\s+[/~]",
        r"mkfs\.",
        r"dd\s+if=",
        r">\s*/dev/sd",
        r"chmod\s+777\s+/",
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return False, "Tehlikeli içerik tespit edildi"

    return True, "OK"

def calculate_risk_score(tool_name: str, params: dict) -> int:
    """
    Calculate a risk score (0-100) for a given operation.
    0-30: Low Risk (Safe)
    31-70: Medium Risk (Notify User)
    71-90: High Risk (Require Approval)
    91+: Critical (Blocked in Strict Mode)
    """
    score = 0
    
    # Base scores for tools
    risk_weights = {
        "delete_file": 80,
        "write_file": 40,
        "move_file": 60,
        "execute_command": 90,
        "open_app": 20,
        "set_volume": 10,
        "read_file": 10,
        "take_screenshot": 5
    }
    
    score = risk_weights.get(tool_name, 20)
    
    # Path risk modifiers
    path = str(params.get("path", "") or params.get("source", ""))
    if any(p in path for p in ["/etc", "/var", "/bin", "/sbin", "/usr/bin"]):
        score += 50
    elif PROJECT_ROOT.resolve() in Path(path).parents:
        score += 10 # Changes inside code are medium risk
        
    # Content risk modifiers
    content = str(params.get("content", ""))
    safe, _ = is_safe_content(content)
    if not safe:
        score += 100
        
    return min(score, 100)
