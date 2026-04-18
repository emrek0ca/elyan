from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from config.elyan_config import elyan_config
from cli.commands.guide import render_install_to_ui_guide
from core.model_catalog import default_model_for_provider, normalize_model_name
from core.runtime_policy import get_runtime_policy_resolver

from .dependencies import DependencyManager
from .init import init_workspace

SETUP_MARKER_VERSION = 1
SETUP_MARKER_PATH = Path.home() / ".elyan" / "setup_complete.json"
SETUP_SKIP_ENV_KEYS = ("ELYAN_SKIP_SETUP", "ELYAN_SKIP_ONBOARD")
STARTER_OLLAMA_MODEL = "llama3.2:3b"


def _env_truthy(name: str) -> bool:
    value = str(os.environ.get(name, "") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _safe_input(prompt: str, default: str = "") -> str:
    raw = input(prompt).strip()
    return raw or default


def _check_macos_permissions() -> dict[str, bool]:
    return {
        "is_macos": sys.platform == "darwin",
        "osascript_available": shutil.which("osascript") is not None,
        "screencapture_available": shutil.which("screencapture") is not None,
    }


def is_setup_complete() -> bool:
    for env_name in SETUP_SKIP_ENV_KEYS:
        if _env_truthy(env_name):
            return True

    try:
        if bool(elyan_config.get("agent.setup.completed", False)):
            return True
    except Exception:
        pass

    if not SETUP_MARKER_PATH.exists():
        return False

    try:
        payload = json.loads(SETUP_MARKER_PATH.read_text(encoding="utf-8"))
        return bool(payload.get("completed")) and int(payload.get("version", 0)) >= SETUP_MARKER_VERSION
    except Exception:
        return False


def mark_setup_complete(extra: dict[str, Any] | None = None) -> None:
    payload = {
        "completed": True,
        "version": SETUP_MARKER_VERSION,
        "completed_at": _iso_now(),
    }
    if isinstance(extra, dict):
        payload.update(extra)

    SETUP_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETUP_MARKER_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    elyan_config.set("agent.setup.completed", True)
    elyan_config.set("agent.setup.completed_at", payload["completed_at"])
    elyan_config.set("agent.setup.version", SETUP_MARKER_VERSION)
    elyan_config.save()


def _set_provider_and_model(provider: str, model: str) -> None:
    provider_name = str(provider or "").strip().lower() or "ollama"
    model_name = normalize_model_name(provider_name, str(model or "").strip() or default_model_for_provider(provider_name))
    elyan_config.set("models.default.provider", provider_name)
    elyan_config.set("models.default.model", model_name)
    elyan_config.set("models.local.provider", "ollama")
    elyan_config.set(
        "models.local.model",
        normalize_model_name(
            "ollama",
            str(elyan_config.get("models.local.model", default_model_for_provider("ollama")) or default_model_for_provider("ollama")),
        ),
    )
    elyan_config.set("agent.model.local_first", True)


def _build_role_map(provider: str, model: str, *, has_ollama: bool) -> dict[str, dict[str, str]]:
    provider_name = str(provider or "").strip().lower() or "ollama"
    model_name = normalize_model_name(provider_name, str(model or "").strip() or default_model_for_provider(provider_name))
    router_provider = "ollama" if has_ollama else provider_name
    router_model = (
        normalize_model_name("ollama", str(elyan_config.get("models.local.model", default_model_for_provider("ollama"))))
        if has_ollama
        else model_name
    )
    worker_role = {"provider": provider_name, "model": model_name}
    router_role = {"provider": router_provider, "model": router_model}
    return {
        "router": router_role,
        "inference": router_role,
        "reasoning": worker_role,
        "planning": worker_role,
        "creative": worker_role,
        "code": worker_role,
        "critic": worker_role,
        "qa": worker_role,
        "research_worker": worker_role,
        "code_worker": worker_role,
    }


def _upsert_channel(channel_type: str, fields: dict[str, Any]) -> None:
    channels = elyan_config.get("channels")
    if not isinstance(channels, list):
        channels = []
    found = False
    for channel in channels:
        if isinstance(channel, dict) and str(channel.get("type", "")).strip().lower() == channel_type:
            channel.update(fields)
            channel["enabled"] = True
            found = True
            break
    if not found:
        payload = {"type": channel_type, "enabled": True}
        payload.update(fields)
        channels.append(payload)
    elyan_config.set("channels", channels)


def _ensure_full_autonomy_defaults() -> None:
    try:
        resolver = get_runtime_policy_resolver()
        resolver.apply_preset("full-autonomy")
    except Exception:
        pass

    _set_provider_and_model("ollama", STARTER_OLLAMA_MODEL)
    elyan_config.set("models.default.provider", "ollama")
    elyan_config.set("models.default.model", normalize_model_name("ollama", STARTER_OLLAMA_MODEL))
    elyan_config.set("models.local.provider", "ollama")
    elyan_config.set("models.local.model", normalize_model_name("ollama", STARTER_OLLAMA_MODEL))
    elyan_config.set("models.roles", _build_role_map("ollama", STARTER_OLLAMA_MODEL, has_ollama=True))
    elyan_config.set("router.enabled", True)
    elyan_config.set("sandbox.enabled", True)
    elyan_config.set("agent.response_style.mode", "friendly")
    elyan_config.set("agent.response_style.friendly", True)
    elyan_config.set("agent.response_style.share_manifest_default", False)
    elyan_config.set("agent.response_style.share_attachments_default", False)
    elyan_config.set("agent.capability_router.enabled", True)
    elyan_config.set("agent.planning.use_llm", True)
    elyan_config.set("agent.multi_agent.enabled", True)


def _run_elyan(args: list[str]) -> int | None:
    launcher = shutil.which("elyan")
    if launcher:
        try:
            completed = subprocess.run([launcher, *args], check=False)
            return completed.returncode
        except FileNotFoundError:
            pass
    try:
        completed = subprocess.run([sys.executable, "-m", "cli.main", *args], check=False)
        return completed.returncode
    except FileNotFoundError:
        return None


def onboard(
    workspace: str | Path | None = None,
    *,
    dry_run: bool = False,
    open_dashboard: bool = True,
    skip_dependencies: bool = False,
    force: bool = False,
    headless: bool = False,
    role: str = "operator",
    channel: str | None = None,
    install_daemon: bool = False,
) -> bool:
    try:
        workspace_path = Path(workspace or os.environ.get("ELYAN_PROJECT_DIR") or Path.cwd()).expanduser().resolve()
        print("🚀 Elyan Onboarding v2 (unified) başlıyor...", flush=True)
        print(
            f"  • Workspace: {workspace_path}\n"
            f"  • Profil: local-first / model: ollama / {STARTER_OLLAMA_MODEL}\n"
            f"  • Kanal: {str(channel or 'webchat')}\n"
            f"  • Dashboard: {'açık' if open_dashboard and not headless else 'kapalı'}",
            flush=True,
        )

        _ensure_full_autonomy_defaults()
        init_workspace(workspace_path, role=role, force=force, dry_run=dry_run)

        dependency_summary: dict[str, Any] | None = None
        if not skip_dependencies:
            dependency_manager = DependencyManager(
                workspace=workspace_path,
                headless=headless,
                open_dashboard=open_dashboard,
                dry_run=dry_run,
            )
            if not dry_run:
                dependency_summary = dependency_manager.bootstrap_all()
            else:
                print("[DRY-RUN] DependencyManager.bootstrap_all() atlanıyor", flush=True)

        if not dry_run:
            _run_elyan(["skills", "enable", "browser", "desktop", "calendar", "--quiet"])
            if install_daemon:
                _run_elyan(["service", "install"])

        if skip_dependencies and open_dashboard and not dry_run and not headless:
            _run_elyan(["dashboard", "--no-browser"])

        if channel:
            _upsert_channel(str(channel).strip().lower(), {})
        else:
            _upsert_channel("webchat", {})

        if not dry_run:
            mark_setup_complete(
                {
                    "workspace": str(workspace_path),
                    "role": role,
                    "headless": bool(headless),
                    "channel": str(channel or "webchat"),
                    "install_daemon": bool(install_daemon),
                }
            )

        if isinstance(dependency_summary, dict):
            parts: list[str] = []
            for key in ("docker", "screenpipe", "ollama", "realtime_actuator", "skills", "dashboard"):
                step = dependency_summary.get(key)
                if isinstance(step, dict):
                    state = "ok" if bool(step.get("ok")) else "partial"
                    parts.append(f"{key}={state}")
            if parts:
                print(f"  • Durum: {', '.join(parts)}", flush=True)

            ollama_step = dependency_summary.get("ollama")
            if isinstance(ollama_step, dict):
                timed_out = [
                    str(item.get("model", "")).strip()
                    for item in list(ollama_step.get("pulls", []) or [])
                    if isinstance(item, dict) and bool(item.get("timed_out"))
                ]
                if timed_out:
                    print(
                        f"  • Ollama model indirmesi zaman aşımına uğradı: {', '.join(timed_out)}",
                        flush=True,
                    )

        print(
            "✅ Onboarding tamamlandı! Artık terminalden UI yüzeyine geçebilirsin.",
            flush=True,
        )
        render_install_to_ui_guide(setup_ready=True, gateway_running=False, prefix="  ")
        return True
    except Exception as exc:
        print(f"❌ Onboarding hatası: {exc}", flush=True)
        return False


class OnboardingWizard:
    def run(
        self,
        *,
        headless: bool = False,
        channel: str | None = None,
        install_daemon: bool = False,
        skip_dependencies: bool = False,
        open_dashboard: bool = True,
        force: bool = False,
    ) -> bool:
        if is_setup_complete() and not force:
            print("✅ Elyan kurulum sihirbazı zaten tamamlanmış.", flush=True)
            print("Yeniden çalıştırmak için: `elyan setup --force`", flush=True)
            return True
        return onboard(
            workspace=Path.cwd(),
            headless=headless,
            channel=channel,
            install_daemon=install_daemon,
            skip_dependencies=skip_dependencies,
            open_dashboard=open_dashboard,
            force=force,
        )


def ensure_first_run_setup(command: str = "", non_interactive: bool = False) -> bool:
    if is_setup_complete():
        return True
    print("⚙️ İlk kurulum henüz tamamlanmamış. Setup sihirbazı başlatılıyor...", flush=True)
    return start_onboarding(headless=bool(non_interactive), force=False)


def start_onboarding(
    *,
    headless: bool = False,
    channel: str | None = None,
    install_daemon: bool = False,
    skip_dependencies: bool = False,
    open_dashboard: bool = True,
    force: bool = False,
) -> bool:
    try:
        wizard = OnboardingWizard()
        return wizard.run(
            headless=bool(headless),
            channel=channel,
            install_daemon=bool(install_daemon),
            skip_dependencies=bool(skip_dependencies),
            open_dashboard=bool(open_dashboard),
            force=bool(force),
        )
    except KeyboardInterrupt:
        print("\n\n👋 Kurulum iptal edildi.", flush=True)
        return False
    except Exception as exc:
        print(f"\n❌ Beklenmedik kurulum hatası: {exc}", flush=True)
        return False


@click.command("onboard")
@click.option("--workspace", type=click.Path(path_type=Path), default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--open-dashboard", is_flag=True, default=True)
@click.option("--skip-deps", is_flag=True)
@click.option("--force", is_flag=True)
@click.option("--headless", is_flag=True)
@click.option("--role", default="operator")
@click.option("--channel", default=None)
@click.option("--install-daemon", is_flag=True)
def cli_onboard(
    workspace: Path | None,
    dry_run: bool,
    open_dashboard: bool,
    skip_deps: bool,
    force: bool,
    headless: bool,
    role: str,
    channel: str | None,
    install_daemon: bool,
) -> None:
    onboard(
        workspace=workspace or Path.cwd(),
        dry_run=dry_run,
        open_dashboard=open_dashboard,
        skip_dependencies=skip_deps,
        force=force,
        headless=headless,
        role=role,
        channel=channel,
        install_daemon=install_daemon,
    )


__all__ = [
    "OnboardingWizard",
    "_build_role_map",
    "_check_macos_permissions",
    "elyan_config",
    "cli_onboard",
    "ensure_first_run_setup",
    "is_setup_complete",
    "mark_setup_complete",
    "onboard",
    "start_onboarding",
    "SETUP_MARKER_PATH",
    "SETUP_SKIP_ENV_KEYS",
]
