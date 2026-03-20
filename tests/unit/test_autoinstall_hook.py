from __future__ import annotations

import builtins
import sys

from core.dependencies.autoinstall_hook import activate


def _hook_module():
    return sys.modules.get("elyan_repo_autoinstall_hook")


def test_autoinstall_hook_activates_builtin_import():
    activate()
    assert builtins.__import__.__module__ == "elyan_repo_autoinstall_hook"


def test_autoinstall_hook_aliases_common_packages():
    activate()
    hook = _hook_module()
    assert hook is not None
    assert hook._alias_for("speech_recognition")["package"] == "SpeechRecognition"
    assert hook._alias_for("PIL")["package"] == "Pillow"
    assert hook._alias_for("fitz")["package"] == "pymupdf"
    package, install_spec, modules = hook._normalize_install_spec("PyPDF2")
    assert package == "PyPDF2"
    assert install_spec == "PyPDF2"
    assert modules == ["PyPDF2"]


def test_autoinstall_hook_blocks_direct_sources():
    activate()
    hook = _hook_module()
    assert hook is not None
    assert hook._is_direct_source("git+https://example.com/pkg.git", {}) is True
    assert hook._is_direct_source("requests>=2.0", {}) is False

