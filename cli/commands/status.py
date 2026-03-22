import os
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _read_config() -> dict[str, Any]:
    config_file = Path.home() / ".elyan" / "elyan.json"
    if not config_file.exists():
        return {}
    try:
        payload = json.loads(config_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _count_active_channels(channels: Any) -> tuple[int, int]:
    if isinstance(channels, list):
        total = len(channels)
        active = sum(1 for ch in channels if isinstance(ch, dict) and ch.get("enabled", False))
        return active, total
    if isinstance(channels, dict):
        total = len(channels)
        active = sum(1 for ch in channels.values() if isinstance(ch, dict) and ch.get("enabled", False))
        return active, total
    return 0, 0


def _count_active_cron_jobs(cron_jobs: Any) -> tuple[int, int]:
    if isinstance(cron_jobs, list):
        total = len(cron_jobs)
        active = sum(1 for job in cron_jobs if not isinstance(job, dict) or job.get("enabled", True))
        return active, total
    if isinstance(cron_jobs, dict):
        total = len(cron_jobs)
        active = sum(1 for job in cron_jobs.values() if not isinstance(job, dict) or job.get("enabled", True))
        return active, total
    return 0, 0


def _gateway_snapshot() -> dict[str, Any]:
    pid_file = Path.home() / ".elyan" / "gateway.pid"
    running = False
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            running = True
        except (ValueError, ProcessLookupError, PermissionError):
            running = False
    return {"running": running, "pid": pid}


def _autopilot_snapshot() -> dict[str, Any]:
    try:
        from core.autopilot import get_autopilot

        autopilot = get_autopilot().get_status()
        return {
            "state": "ACTIVE" if autopilot.get("running") else "INACTIVE",
            "last_tick_reason": autopilot.get("last_tick_reason") or "-",
        }
    except Exception:
        return {
            "state": "UNKNOWN",
            "last_tick_reason": "-",
        }


def _subscription_snapshot() -> dict[str, Any]:
    try:
        from core.subscription import subscription_manager
        from core.quota import quota_manager

        tier = str(subscription_manager.get_user_tier("local") or "").strip()
        stats = quota_manager.get_user_stats("local")
        return {
            "available": True,
            "tier": tier.upper() if tier else "-",
            "daily_messages": stats.get("daily_messages"),
            "daily_limit": stats.get("daily_limit"),
        }
    except Exception:
        return {
            "available": False,
            "tier": "-",
            "daily_messages": None,
            "daily_limit": None,
        }


def _skill_count() -> int:
    skills_dir = Path.home() / ".elyan" / "skills"
    try:
        return sum(1 for d in skills_dir.iterdir() if d.is_dir()) if skills_dir.exists() else 0
    except Exception:
        return 0


def _deep_snapshot(gateway_running: bool, gateway_pid: int | None) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}

    memory_dir = Path.home() / ".elyan" / "memory"
    if memory_dir.exists():
        md_files = list(memory_dir.glob("*.md"))
        total_size = sum(f.stat().st_size for f in md_files)
        snapshot["memory"] = {
            "files": len(md_files),
            "size_kb": total_size // 1024,
        }

    projects_dir = Path.home() / ".elyan" / "projects"
    if projects_dir.exists():
        snapshot["projects"] = sum(1 for d in projects_dir.iterdir() if d.is_dir())

    logs_dir = Path.home() / ".elyan" / "logs"
    if logs_dir.exists():
        log_files = list(logs_dir.rglob("*"))
        log_size = sum(f.stat().st_size for f in log_files if f.is_file())
        snapshot["logs"] = {
            "size_mb": log_size // 1024 // 1024,
        }

    if gateway_running and gateway_pid:
        try:
            import psutil

            proc = psutil.Process(gateway_pid)
            mem_info = proc.memory_info()
            running_for = time.time() - proc.create_time()
            snapshot["process"] = {
                "memory_mb": mem_info.rss // 1024 // 1024,
                "cpu_pct": proc.cpu_percent(interval=0.5),
                "uptime_s": int(running_for),
            }
        except Exception:
            pass

    return snapshot


def _build_status_payload(deep: bool = False) -> dict[str, Any]:
    config = _read_config()
    models = config.get("models", {}) if isinstance(config, dict) else {}
    default = models.get("default", {}) if isinstance(models, dict) else {}

    provider = str(default.get("provider", "") or "").strip() or "?"
    model = str(default.get("model", "") or "").strip() or "?"
    active_channels, total_channels = _count_active_channels(config.get("channels", []))
    active_cron, total_cron = _count_active_cron_jobs(config.get("cron", []))
    gateway = _gateway_snapshot()
    autopilot = _autopilot_snapshot()
    subscription = _subscription_snapshot()
    skill_count = _skill_count()

    missing = []
    if not config:
        missing.append("konfigürasyon")
    if provider == "?":
        missing.append("varsayılan sağlayıcı")
    if model == "?":
        missing.append("varsayılan model")

    launch_ready = not missing
    if not launch_ready:
        next_action = "elyan setup --force"
    elif not gateway["running"]:
        next_action = "elyan launch"
    else:
        next_action = "elyan chat"

    payload: dict[str, Any] = {
        "launch": {
            "ready": launch_ready,
            "missing": missing,
            "next_action": next_action,
        },
        "gateway": gateway,
        "model": {
            "provider": provider,
            "name": model,
        },
        "channels": {
            "active": active_channels,
            "total": total_channels,
        },
        "cron": {
            "active": active_cron,
            "total": total_cron,
        },
        "autopilot": autopilot,
        "skills": skill_count,
        "subscription": subscription,
    }
    if deep:
        payload["deep"] = _deep_snapshot(bool(gateway["running"]), gateway.get("pid"))
    return payload


def run(args):
    payload = _build_status_payload(deep=bool(getattr(args, "deep", False)))

    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print("=" * 50)
    print("  ELYAN STATUS")
    print("=" * 50)

    gateway_running = bool(payload["gateway"]["running"])
    gateway_pid = payload["gateway"]["pid"]
    provider = payload["model"]["provider"]
    model = payload["model"]["name"]
    active_channels = payload["channels"]["active"]
    total_channels = payload["channels"]["total"]
    active_jobs = payload["cron"]["active"]
    total_cron = payload["cron"]["total"]
    autopilot_state = payload["autopilot"]["state"]
    last_tick = payload["autopilot"]["last_tick_reason"]
    skill_count = payload["skills"]
    subscription = payload["subscription"]

    print(f"\n  Lansman:     {'HAZIR' if payload['launch']['ready'] else 'EKSIK'}")
    if payload["launch"]["missing"]:
        print(f"    Eksik:     {', '.join(payload['launch']['missing'])}")
    print(f"    Sonraki:   {payload['launch']['next_action']}")

    print(f"  Gateway:     {'ACTIVE (PID: ' + str(gateway_pid) + ')' if gateway_running else 'INACTIVE'}")
    print(f"  AI Provider: {provider}")
    print(f"  Model:       {model}")
    print(f"  Kanallar:    {active_channels}/{total_channels} aktif")
    print(f"  Cron:        {active_jobs}/{total_cron} aktif gorev")
    print(f"  Autopilot:   {autopilot_state} (tick: {last_tick})")
    print(f"  Skills:      {skill_count} harici skill")

    if subscription.get("available"):
        daily_limit = subscription.get("daily_limit")
        limit_text = "∞" if daily_limit == -1 else (daily_limit if daily_limit is not None else "?")
        print(f"  Abonelik:    {subscription.get('tier', '-')}")
        print(f"  Mesaj Kota:  {subscription.get('daily_messages')}/{limit_text}")

    if getattr(args, "deep", False):
        deep = payload.get("deep", {})
        print("\n  --- DEEP STATUS ---")

        memory = deep.get("memory", {})
        if memory:
            print(f"  Bellek:      {memory.get('files', 0)} dosya, {memory.get('size_kb', 0)}KB")

        projects = deep.get("projects")
        if projects is not None:
            print(f"  Projeler:    {projects} proje")

        logs = deep.get("logs", {})
        if logs:
            print(f"  Log boyutu:  {logs.get('size_mb', 0)}MB")

        process = deep.get("process", {})
        if process:
            print(f"  Proses RAM:  {process.get('memory_mb', 0)}MB")
            print(f"  Proses CPU:  {process.get('cpu_pct', 0)}%")
            uptime_s = int(process.get("uptime_s", 0) or 0)
            hours = int(uptime_s // 3600)
            mins = int((uptime_s % 3600) // 60)
            print(f"  Calisma:     {hours}h {mins}m")

    print("\n" + "=" * 50)


def run_status(args=None):
    """Backward-compatible entrypoint used by older CLI callers."""
    run(args or SimpleNamespace(deep=False, json=False))
