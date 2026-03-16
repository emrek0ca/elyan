from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


DEFAULT_FILES = ("AGENTS.txt", "SOUL.txt", "TOOLS.txt", "MEMORY.txt")


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.write_text(content, encoding="utf-8")


def ensure_workspace_contract(
    workspace_dir: str | Path,
    *,
    role: str,
    allowed_tools: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Create plain-text workspace contract files for traceable/debuggable runs."""
    base = Path(workspace_dir).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    tools = list(dict.fromkeys([str(t).strip() for t in (allowed_tools or []) if str(t).strip()]))
    meta = dict(metadata or {})

    agents_md = f"# AGENTS\n\n- role: {role}\n- created_at: {ts}\n- policy: isolated workspace\n"
    soul_md = (
        "# SOUL\n\n"
        "- operating_principle: perceive -> decide -> act -> observe\n"
        "- never_claim_done_without_verify: true\n"
        "- evidence_first_delivery: true\n"
    )
    tools_md = "# TOOLS\n\n" + ("\n".join(f"- {t}" for t in tools) if tools else "- any (runtime policy applies)") + "\n"
    memory_md = "# MEMORY\n\n" + json.dumps(meta, ensure_ascii=False, indent=2) + "\n"

    mapping = {
        "AGENTS.txt": agents_md,
        "SOUL.txt": soul_md,
        "TOOLS.txt": tools_md,
        "MEMORY.txt": memory_md,
    }
    for name, content in mapping.items():
        _write_if_missing(base / name, content)

    return {name: str((base / name).resolve()) for name in DEFAULT_FILES}
