import json
import importlib.util
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.elyan_config import elyan_config
from core.model_catalog import QWEN_LIGHT_OLLAMA_MODEL, default_model_for_provider, normalize_model_name
from core.runtime_policy import get_runtime_policy_resolver
from security.keychain import KeychainManager, keychain


SETUP_MARKER_VERSION = 1
SETUP_MARKER_PATH = Path.home() / ".elyan" / "setup_complete.json"
SETUP_SKIP_ENV_KEYS = ("ELYAN_SKIP_SETUP", "ELYAN_SKIP_ONBOARD")


def _env_truthy(name: str) -> bool:
    value = str(os.environ.get(name, "") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _safe_input(prompt: str, default: str = "") -> str:
    raw = input(prompt).strip()
    return raw or default


def _check_macos_permissions() -> dict[str, bool]:
    """
    Best-effort permission hints. macOS TCC status is not reliably queryable from here,
    so this returns conservative checks for operator visibility.
    """
    return {
        "is_macos": sys.platform == "darwin",
        "osascript_available": shutil.which("osascript") is not None,
        "screencapture_available": shutil.which("screencapture") is not None,
    }


def _ensure_optional_dependency(
    *,
    module_name: str,
    install_spec: str,
    headless: bool,
    label: str,
) -> bool:
    if importlib.util.find_spec(module_name) is not None:
        return True

    print(f"⚠️ {label} için gerekli bağımlılık eksik: `{install_spec}`")
    if headless:
        print(f"   Kurulum için: {sys.executable} -m pip install {install_spec}")
        return False

    should_install = _safe_input("Şimdi otomatik kurulsun mu? (Y/n): ", "y").strip().lower() in {"", "y", "yes"}
    if not should_install:
        print(f"   Atlandı. Sonradan çalıştır: {sys.executable} -m pip install {install_spec}")
        return False

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", install_spec],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and importlib.util.find_spec(module_name) is not None:
            print(f"✅ {label} bağımlılığı kuruldu.")
            return True
        err = (proc.stderr or proc.stdout or "").strip()
        print(f"⚠️ Otomatik kurulum başarısız: {err or 'pip install failed'}")
        print(f"   Manuel: {sys.executable} -m pip install {install_spec}")
        return False
    except Exception as exc:
        print(f"⚠️ Otomatik kurulum hatası: {exc}")
        print(f"   Manuel: {sys.executable} -m pip install {install_spec}")
        return False


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
    provider = str(provider or "").strip().lower()
    model = normalize_model_name(provider, model)
    elyan_config.set("models.default.provider", provider)
    elyan_config.set("models.default.model", model)
    elyan_config.set("agent.model.local_first", True)
    if provider == "ollama":
        elyan_config.set("models.local.provider", "ollama")
        elyan_config.set("models.local.model", model)
    else:
        # Keep local fallback hot even when cloud is selected.
        elyan_config.set("models.local.provider", "ollama")
        elyan_config.set(
            "models.local.model",
            normalize_model_name(
                "ollama",
                str(elyan_config.get("models.local.model", default_model_for_provider("ollama"))),
            ),
        )


def _build_role_map(provider: str, model: str, *, has_ollama: bool) -> dict[str, dict[str, str]]:
    provider = str(provider or "").strip().lower()
    model = normalize_model_name(provider, model)
    router_provider = "ollama" if has_ollama else provider
    router_model = (
        normalize_model_name("ollama", str(elyan_config.get("models.local.model", default_model_for_provider("ollama"))))
        if has_ollama
        else model
    )
    worker_role = {"provider": provider, "model": model}
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


def _set_provider_key(provider: str, api_key: str) -> None:
    if not api_key:
        return
    provider_env_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "groq": "GROQ_API_KEY",
    }
    env_key = provider_env_map.get(provider, f"{provider.upper()}_API_KEY")
    key_name = KeychainManager.key_for_env(env_key) or env_key.lower()
    if keychain.set_key(key_name, api_key):
        print(f"✅ {env_key} anahtarı Keychain'e kaydedildi.")
    else:
        print("⚠️ Keychain yazılamadı; anahtar ortam değişkeninden okunmalı.")


def _upsert_channel(channel_type: str, fields: dict[str, Any]) -> None:
    channels = elyan_config.get("channels")
    if not isinstance(channels, list):
        channels = []
    found = False
    for ch in channels:
        if isinstance(ch, dict) and str(ch.get("type", "")).strip().lower() == channel_type:
            ch.update(fields)
            ch["enabled"] = True
            found = True
            break
    if not found:
        payload = {"type": channel_type, "enabled": True}
        payload.update(fields)
        channels.append(payload)
    elyan_config.set("channels", channels)


def _ensure_full_autonomy_defaults() -> None:
    resolver = get_runtime_policy_resolver()
    resolver.apply_preset("full-autonomy")
    # UX defaults: always conversational, don't spam artifacts unless needed.
    elyan_config.set("agent.response_style.mode", "friendly")
    elyan_config.set("agent.response_style.friendly", True)
    elyan_config.set("agent.response_style.share_manifest_default", False)
    elyan_config.set("agent.response_style.share_attachments_default", False)
    # Keep deterministic execution options enabled.
    elyan_config.set("agent.capability_router.enabled", True)
    elyan_config.set("agent.planning.use_llm", True)
    elyan_config.set("agent.multi_agent.enabled", True)


class OnboardingWizard:
    def __init__(self):
        self.project_root = Path(__file__).resolve().parent.parent
        self.config_path = Path.home() / ".elyan" / "elyan.json"

    def _check_command(self, cmd: str) -> bool:
        return shutil.which(cmd) is not None

    def run(
        self,
        *,
        headless: bool = False,
        channel: str | None = None,
        install_daemon: bool = False,
        force: bool = False,
    ) -> bool:
        if is_setup_complete() and not force:
            print("✅ Elyan kurulum sihirbazı zaten tamamlanmış.")
            print("Yeniden çalıştırmak için: `elyan setup --force`")
            return True

        print("\n" + "=" * 54)
        print("✨ ELYAN - İLK KURULUM SİHİRBAZI")
        print("=" * 54 + "\n")
        print("Bu kurulum, tam otonom çalışma için temel ayarları tek adımda yapar.\n")

        has_docker = self._check_command("docker")
        has_ollama = self._check_command("ollama")
        perms = _check_macos_permissions()

        print("🔍 Sistem Kontrolü:")
        print(f"  - Docker: {'✅ Kurulu' if has_docker else '⚠️ Bulunamadı'}")
        print(f"  - Ollama: {'✅ Kurulu' if has_ollama else '⚠️ Bulunamadı'}")
        if perms["is_macos"]:
            print("  - macOS: ✅")
            print(f"  - osascript: {'✅' if perms['osascript_available'] else '⚠️ yok'}")
            print(f"  - screencapture: {'✅' if perms['screencapture_available'] else '⚠️ yok'}")
        print("")

        elyan_config.set("sandbox.enabled", has_docker)
        _ensure_full_autonomy_defaults()

        provider_map = {
            "1": ("ollama", "llama3.1:8b"),
            "2": ("openai", "gpt-4o"),
            "3": ("google", "gemini-2.0-flash"),
            "4": ("groq", "llama-3.3-70b-versatile"),
            "5": ("ollama", QWEN_LIGHT_OLLAMA_MODEL),
        }
        default_choice = "1" if has_ollama else "2"

        if headless:
            choice = default_choice
        else:
            print("[1] LLM Sağlayıcısı:")
            print("  1. Ollama (yerel, KVKK için önerilen)")
            print("  2. OpenAI")
            print("  3. Google Gemini")
            print("  4. Groq")
            print(f"  5. Ollama Qwen Light ({QWEN_LIGHT_OLLAMA_MODEL})")
            choice = _safe_input(f"Seçim (1-5) [{default_choice}]: ", default_choice)

        provider, selected_model = provider_map.get(choice, provider_map[default_choice])
        _set_provider_and_model(provider, selected_model)

        if provider != "ollama":
            api_key = ""
            if not headless:
                api_key = _safe_input(f"🔑 {provider.upper()} API key (boş geçilebilir): ", "")
            _set_provider_key(provider, api_key)
        elif has_ollama:
            print("📦 Yerel model kontrolü: `ollama list` ile modelleri doğrula.")

        # Keep hybrid router/worker/critic roles aligned with onboarding choice.
        elyan_config.set("router.enabled", True)
        elyan_config.set("models.roles", _build_role_map(provider, selected_model, has_ollama=has_ollama))

        normalized_channel = str(channel or "").strip().lower()
        if not normalized_channel:
            if headless:
                normalized_channel = "webchat"
            else:
                print("\n[2] Birincil Kanal:")
                print("  1. Telegram")
                print("  2. WhatsApp")
                print("  3. Sadece Web/CLI")
                ch = _safe_input("Seçim (1-3) [1]: ", "1")
                normalized_channel = {"1": "telegram", "2": "whatsapp", "3": "webchat"}.get(ch, "telegram")

        if normalized_channel == "telegram":
            _ensure_optional_dependency(
                module_name="telegram",
                install_spec="python-telegram-bot>=22.0",
                headless=headless,
                label="Telegram",
            )
            token_value = "$TELEGRAM_BOT_TOKEN"
            token = ""
            if not headless:
                token = _safe_input("🤖 Telegram bot token (boş geçilebilir): ", "")
            if token:
                if not keychain.set_key("telegram_bot_token", token):
                    token_value = token
                    print("⚠️ Keychain yazılamadı; token config'e düz metin yazıldı.")
            _upsert_channel("telegram", {"token": token_value})
            print("✅ Telegram kanal ayarı tamamlandı.")
        elif normalized_channel == "whatsapp":
            _upsert_channel("whatsapp", {})
            if not headless:
                try:
                    from cli.commands.channels import login_whatsapp

                    ok = login_whatsapp(channel_id="whatsapp")
                    if ok:
                        print("✅ WhatsApp oturumu bağlandı.")
                    else:
                        print("⚠️ WhatsApp bağlanamadı. Sonradan: `elyan channels login whatsapp`")
                except Exception as exc:
                    print(f"⚠️ WhatsApp onboarding hatası: {exc}")
            else:
                print("ℹ️ Headless kurulumda WhatsApp QR adımı atlandı.")
        else:
            _upsert_channel("webchat", {})
            print("✅ Web/CLI kanal ayarı tamamlandı.")

        if perms["is_macos"]:
            print("\n🖥️ macOS izin kontrol listesi (tam otonom için):")
            print("  1. Accessibility: Terminal/Python/ELYAN izinli olmalı.")
            print("  2. Screen Recording: ekran analizi/screenshot için açık olmalı.")
            print("  3. Full Disk Access: dosya işlemleri için önerilir.")

        daemon_enabled = bool(install_daemon)
        if not daemon_enabled and not headless:
            daemon_enabled = _safe_input("\nElyan açılışta otomatik başlasın mı? (y/N): ", "n").lower() == "y"
        if daemon_enabled:
            try:
                from cli.daemon import daemon_manager

                if daemon_manager.install():
                    print("✅ launchd servisi kuruldu.")
            except Exception as exc:
                print(f"⚠️ Servis kurulamadı: {exc}")

        elyan_config.save()
        mark_setup_complete(
            {
                "channel": normalized_channel,
                "provider": provider,
                "model": selected_model,
                "headless": bool(headless),
            }
        )

        print("\n" + "=" * 54)
        print("🎉 KURULUM TAMAMLANDI")
        print("=" * 54)
        elyan_bin = Path(sys.executable).with_name("elyan")
        cli_mod = f"{sys.executable} -m cli.main"
        if elyan_bin.exists():
            print(f"Sonraki adım: `{elyan_bin} gateway start --daemon`")
            print(f"Sağlık kontrolü: `{elyan_bin} doctor`")
            print(f"Hızlı durum: `{elyan_bin} status`")
            print(f"Dashboard: `{elyan_bin} dashboard`")
        else:
            print(f"Sonraki adım: `{cli_mod} gateway start --daemon`")
            print(f"Sağlık kontrolü: `{cli_mod} doctor`")
            print(f"Hızlı durum: `{cli_mod} status`")
            print(f"Dashboard: `{cli_mod} dashboard`")
        print(f"Config yolu: {self.config_path}")
        print(f"Aktif HOME: {Path.home()}")
        print("")
        return True


def ensure_first_run_setup(command: str = "", non_interactive: bool = False) -> bool:
    if is_setup_complete():
        return True
    print("⚙️ İlk kurulum henüz tamamlanmamış. Setup sihirbazı başlatılıyor...")
    return start_onboarding(headless=bool(non_interactive), force=False)


def start_onboarding(
    *,
    headless: bool = False,
    channel: str | None = None,
    install_daemon: bool = False,
    force: bool = False,
) -> bool:
    try:
        wizard = OnboardingWizard()
        return wizard.run(
            headless=bool(headless),
            channel=channel,
            install_daemon=bool(install_daemon),
            force=bool(force),
        )
    except KeyboardInterrupt:
        print("\n\n👋 Kurulum iptal edildi.")
        return False
    except Exception as exc:
        print(f"\n❌ Beklenmedik kurulum hatası: {exc}")
        return False
