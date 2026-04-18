"""Legacy compatibility redirect for run store imports.

Canonical implementation lives in :mod:`core.run_store`.
"""

from __future__ import annotations

import sys

import core.run_store as _canonical_run_store

sys.modules[__name__] = _canonical_run_store
