"""
Elyan Polyglot Executor — Multi-language code execution through sandbox.

Supports: Python, Node.js, Go, Rust, C++, Ruby, Java, Shell
"""

from typing import Any, Dict, Optional
from utils.logger import get_logger

logger = get_logger("polyglot")


# Language metadata
LANGUAGES = {
    "python": {
        "ext": ".py", "cmd": "python3 {file}", "image": "python:3.12-slim",
        "aliases": ["py", "python3"],
    },
    "node": {
        "ext": ".js", "cmd": "node {file}", "image": "node:20-slim",
        "aliases": ["javascript", "js", "nodejs"],
    },
    "go": {
        "ext": ".go", "cmd": "go run {file}", "image": "golang:1.22-alpine",
        "aliases": ["golang"],
    },
    "rust": {
        "ext": ".rs", "cmd": "rustc {file} -o /tmp/out && /tmp/out", "image": "rust:1.77-slim",
        "aliases": ["rs"],
    },
    "cpp": {
        "ext": ".cpp", "cmd": "g++ {file} -o /tmp/out && /tmp/out", "image": "gcc:14",
        "aliases": ["c++", "cxx"],
    },
    "ruby": {
        "ext": ".rb", "cmd": "ruby {file}", "image": "ruby:3.3-slim",
        "aliases": ["rb"],
    },
    "java": {
        "ext": ".java", "cmd": "javac {file} && java Main", "image": "eclipse-temurin:21-jdk",
        "aliases": [],
    },
    "shell": {
        "ext": ".sh", "cmd": "bash {file}", "image": "alpine:3.19",
        "aliases": ["bash", "sh", "zsh"],
    },
}


def resolve_language(lang_input: str) -> Optional[str]:
    """Resolve language alias to canonical name."""
    lower = lang_input.lower().strip()
    if lower in LANGUAGES:
        return lower
    for canonical, meta in LANGUAGES.items():
        if lower in meta.get("aliases", []):
            return canonical
    return None


class PolyglotExecutor:
    """Execute code in any supported language via the sandbox selector."""

    def __init__(self):
        self._sandbox = None

    @property
    def sandbox(self):
        if self._sandbox is None:
            from core.sandbox.selector import sandbox
            self._sandbox = sandbox
        return self._sandbox

    async def run(
        self,
        code: str,
        language: str = "python",
        workspace_dir: Optional[str] = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """Execute code in the specified language."""
        canonical = resolve_language(language)
        if not canonical:
            return {
                "success": False,
                "error": f"Unsupported language: {language}. Supported: {', '.join(LANGUAGES.keys())}",
            }

        logger.info(f"Polyglot executing {canonical} code ({len(code)} chars)")

        result = await self.sandbox.execute_code(
            code=code,
            language=canonical,
            workspace_dir=workspace_dir,
        )

        result["language"] = canonical
        return result

    def get_supported_languages(self) -> list:
        """List all supported languages."""
        return list(LANGUAGES.keys())


# Global instance
polyglot = PolyglotExecutor()
