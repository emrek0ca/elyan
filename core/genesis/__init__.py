"""
core/genesis/__init__.py
───────────────────────────────────────────────────────────────────────────────
Genesis Feature Flag Guard

Genesis modules are EXPERIMENTAL — they modify their own source code and should
only be enabled explicitly. Set ELYAN_GENESIS_ENABLED=1 to activate.

Default: disabled. Any import from core.genesis will raise ImportError unless
the flag is set.

Usage:
  export ELYAN_GENESIS_ENABLED=1  # enable
  unset  ELYAN_GENESIS_ENABLED    # disable (default)
"""
import os as _os

_enabled = _os.environ.get("ELYAN_GENESIS_ENABLED", "0").strip().lower() in {
    "1", "true", "yes", "on"
}

if not _enabled:
    raise ImportError(
        "core.genesis is disabled (experimental). "
        "Set ELYAN_GENESIS_ENABLED=1 to enable."
    )
