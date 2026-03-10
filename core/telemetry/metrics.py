from __future__ import annotations

from typing import Any


def sample_runtime_metrics() -> dict[str, Any]:
    try:
        import os
        import psutil

        process = psutil.Process(os.getpid())
        mem = process.memory_info()
        return {
            "memory_mb": round(float(mem.rss) / (1024 * 1024), 2),
            "threads": int(process.num_threads()),
            "open_files": len(process.open_files()),
        }
    except Exception:
        return {}


__all__ = ["sample_runtime_metrics"]
