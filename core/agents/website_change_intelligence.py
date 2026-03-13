from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from core.storage_paths import resolve_elyan_data_dir


_PRICE_MARKERS = (
    "pricing",
    "price",
    "usd",
    "eur",
    "plan",
    "subscription",
    "monthly",
    "yearly",
    "cost",
    "api pricing",
)

_FEATURE_MARKERS = (
    "new",
    "feature",
    "release",
    "model",
    "endpoint",
    "capability",
    "launch",
    "beta",
    "update",
)


def _safe_slug(url: str) -> str:
    digest = hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:12]
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(url).lower()).strip("-")
    if len(cleaned) > 42:
        cleaned = cleaned[:42]
    return f"{cleaned or 'url'}-{digest}"


def _extract_text(html: str, max_chars: int = 12000) -> str:
    body = str(html or "")
    body = re.sub(r"(?is)<script.*?>.*?</script>", " ", body)
    body = re.sub(r"(?is)<style.*?>.*?</style>", " ", body)
    body = re.sub(r"(?is)<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return body[:max_chars]


def _fetch_url_text(url: str, timeout: float = 10.0) -> tuple[bool, str, str]:
    req = Request(
        str(url),
        headers={
            "User-Agent": "ElyanWebsiteIntel/1.0 (+https://elyan.local)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(req, timeout=float(timeout)) as resp:
            raw = resp.read()
        html = raw.decode("utf-8", errors="ignore")
        return True, "", _extract_text(html)
    except URLError as exc:
        return False, str(exc), ""
    except Exception as exc:
        return False, str(exc), ""


def _classify_change(old_text: str, new_text: str) -> list[str]:
    tags: list[str] = []
    low_old = old_text.lower()
    low_new = new_text.lower()
    for marker in _PRICE_MARKERS:
        if marker in low_new and marker not in low_old:
            tags.append("pricing_signal")
            break
    for marker in _FEATURE_MARKERS:
        if marker in low_new and marker not in low_old:
            tags.append("feature_signal")
            break
    if not tags:
        tags.append("content_change")
    return tags


def _summary_line(url: str, tags: list[str], changed: bool, err: str = "") -> str:
    if err:
        return f"{url}: fetch_failed ({err})"
    if not changed:
        return f"{url}: no_change"
    return f"{url}: changed ({', '.join(tags)})"


def _load_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_report(result: dict[str, Any]) -> str:
    report_dir = resolve_elyan_data_dir() / "reports" / "website_change_intelligence"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"website_change_{stamp}.md"
    lines = [
        "# Website Change Intelligence",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- URLs checked: {result.get('checked_count', 0)}",
        f"- Changed: {result.get('changed_count', 0)}",
        "",
        "## Summary",
    ]
    for row in result.get("summary_lines", []):
        lines.append(f"- {row}")
    lines.extend(["", "## Changes", ""])
    for row in result.get("changes", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('url')}: {', '.join(row.get('tags', []))} "
            f"(old_hash={row.get('old_hash', '')[:8]} new_hash={row.get('new_hash', '')[:8]})"
        )
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return str(out)


async def run_website_change_intelligence_module(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = payload if isinstance(payload, dict) else {}
    tracked_urls = req.get("tracked_urls", [])
    if isinstance(tracked_urls, str):
        tracked_urls = [tracked_urls]
    urls = [str(url).strip() for url in tracked_urls if str(url).strip()]

    if not urls:
        return {
            "success": True,
            "module_id": "website_change_intelligence",
            "status": "no_targets",
            "checked_count": 0,
            "changed_count": 0,
            "changes": [],
            "summary_lines": ["No tracked_urls provided."],
        }

    root = resolve_elyan_data_dir() / "website_intelligence" / "snapshots"
    now = int(time.time())
    changes: list[dict[str, Any]] = []
    summary: list[str] = []

    for url in urls:
        slug = _safe_slug(url)
        snapshot_path = root / slug / "latest.json"
        prev = _load_snapshot(snapshot_path)
        old_text = str(prev.get("text") or "")
        old_hash = str(prev.get("hash") or "")

        ok, err, new_text = _fetch_url_text(url)
        if not ok:
            summary.append(_summary_line(url, [], False, err))
            continue

        new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
        changed = bool(old_hash and old_hash != new_hash)
        tags = _classify_change(old_text, new_text) if changed else []
        summary.append(_summary_line(url, tags, changed))
        record = {
            "url": url,
            "slug": slug,
            "checked_at": now,
            "hash": new_hash,
            "text": new_text,
            "status": "ok",
        }
        _write_json(snapshot_path, record)

        if changed:
            changes.append(
                {
                    "url": url,
                    "slug": slug,
                    "old_hash": old_hash,
                    "new_hash": new_hash,
                    "tags": tags,
                }
            )

    result = {
        "success": True,
        "module_id": "website_change_intelligence",
        "status": "ok",
        "checked_count": len(urls),
        "changed_count": len(changes),
        "changes": changes,
        "summary_lines": summary,
    }
    result["report_path"] = _write_report(result)
    return result


__all__ = ["run_website_change_intelligence_module"]
