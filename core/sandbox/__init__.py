"""
Elyan Sandbox Package

Provides isolated code execution through Docker or local sandbox.
Usage:
    from core.sandbox.selector import sandbox
    result = await sandbox.execute_code("print('hello')", language="python")
"""

from .selector import sandbox
from .polyglot import polyglot

__all__ = ["sandbox", "polyglot"]
