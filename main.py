#!/usr/bin/env python3
"""
Elyan — AI Agent Framework
Interactive CLI with OpenClaw-style onboarding.
"""

import sys
import os
import json
import socket
import time
import subprocess
from pathlib import Path

project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    import click
except ImportError:
    print("Error: click required. Run: pip install click")
    sys.exit(1)

from utils.logger import get_logger

logger = get_logger("main")
VERSION = "20.1.0"
PORT = int(os.environ.get("ELYAN_PORT", 18789))
HOME = Path.home() / ".elyan"
CFG_FILE = HOME / "elyan.json"


def _load_dotenv():
    """Load .env files into os.environ (project root + ~/.elyan)."""
    for env_path in [project_root / ".env", project_root / "bot" / ".env", HOME / ".env"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if val and not os.environ.get(key):
                    os.environ[key] = val


# ── Helpers ──────────────────────────────────────────────────

def _port_alive(port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, OSError):
            return False

def _cfg() -> dict:
    if CFG_FILE.exists():
        try:
            return json.loads(CFG_FILE.read_text())
        except Exception:
            return {}
    return {}

def _save(cfg: dict):
    CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CFG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))

def _ollama_ok():
    try:
        import httpx
        return httpx.get("http://localhost:11434/api/tags", timeout=2).status_code == 200
    except Exception:
        return False

def _ollama_models():
    try:
        import httpx
        return [m["name"] for m in httpx.get("http://localhost:11434/api/tags", timeout=3).json().get("models", [])]
    except Exception:
        return []


def _configured_model(cfg: dict | None = None) -> tuple[str, str]:
    cfg = cfg or _cfg()
    models = cfg.get("models", {}) if isinstance(cfg.get("models"), dict) else {}
    default = models.get("default", {}) if isinstance(models.get("default"), dict) else {}
    provider = str(default.get("provider") or cfg.get("provider") or "auto").strip() or "auto"
    model = str(default.get("model") or cfg.get("model") or "").strip()
    return provider, (model or "not set")


def _gateway_health(port=PORT) -> dict:
    status = {"reachable": _port_alive(port), "ok": None, "health_status": "", "entrypoint": ""}
    try:
        import httpx
        resp = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=2.0)
        status["reachable"] = resp.status_code < 500
        if resp.headers.get("content-type", "").startswith("application/json"):
            data = resp.json()
            status["ok"] = bool(data.get("ok"))
            status["health_status"] = str(data.get("health_status") or data.get("status") or "").strip()
            status["entrypoint"] = str(data.get("entrypoint") or "").strip()
        else:
            status["ok"] = resp.status_code == 200
    except Exception:
        pass
    return status


# ── Fancy Printing ───────────────────────────────────────────

def _banner():
    click.echo()
    click.echo(click.style("  ╔═══════════════════════════════════════╗", fg="blue"))
    click.echo(click.style("  ║", fg="blue") + click.style("   🧠 ELYAN AI AGENT FRAMEWORK", fg="white", bold=True) + click.style("         ║", fg="blue"))
    click.echo(click.style("  ║", fg="blue") + click.style(f"        v{VERSION}  •  Terminal-First", fg="bright_black") + click.style("      ║", fg="blue"))
    click.echo(click.style("  ╚═══════════════════════════════════════╝", fg="blue"))
    click.echo()

def _step(num, text):
    click.echo(click.style(f"\n  [{num}] ", fg="blue", bold=True) + click.style(text, bold=True))

def _ok(text):
    click.echo(click.style(f"      ✅ {text}", fg="green"))

def _warn(text):
    click.echo(click.style(f"      ⚠️  {text}", fg="yellow"))

def _info(text):
    click.echo(click.style(f"      ℹ️  {text}", fg="bright_black"))

def _line():
    click.echo(click.style("  ─────────────────────────────────────────", fg="bright_black"))


# ═══════════════════════════════════════════════════════════════
#  ROOT
# ═══════════════════════════════════════════════════════════════

@click.group(invoke_without_command=True)
@click.version_option(VERSION, prog_name="Elyan")
@click.pass_context
def cli(ctx):
    """🧠 Elyan — AI Agent Framework

    \b
    İlk kurulum:    elyan setup
    Başlat:         elyan start  
    Dashboard:      elyan dashboard
    Model seç:      elyan models
    Durum:          elyan status
    """
    if ctx.invoked_subcommand is None:
        # İlk kez çalıştırılıyorsa setup'a yönlendir
        if not CFG_FILE.exists():
            ctx.invoke(setup)
        else:
            _banner()
            cfg = _cfg()
            model = cfg.get("model", "not set")
            gw = "🟢 ONLINE" if _port_alive() else "🔴 OFFLINE"
            click.echo(f"  Model:     {model}")
            click.echo(f"  Gateway:   {gw}")
            click.echo(f"  Dashboard: http://localhost:{PORT}/dashboard")
            click.echo()
            click.echo(click.style("  Komutlar:", bold=True))
            click.echo("    elyan start      — Gateway başlat")
            click.echo("    elyan models     — Model yönetimi")
            click.echo("    elyan dashboard  — Web panel aç")
            click.echo("    elyan status     — Sistem durumu")
            click.echo("    elyan team       — Ajan takımı")
            click.echo("    elyan setup      — Kurulum sihirbazı")
            click.echo()


# ═══════════════════════════════════════════════════════════════
#  elyan setup — Interactive Onboarding Wizard
# ═══════════════════════════════════════════════════════════════

@cli.command()
def setup():
    """🚀 İnteraktif kurulum sihirbazı (ilk çalıştırma)."""
    _banner()
    click.echo(click.style("  Hoş geldin! Elyan'ı birkaç adımda kuracağız.", fg="cyan", bold=True))

    cfg = _cfg()

    # ── Step 1: Home Directory ──
    _step(1, "Sistem Hazırlığı")
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "logs").mkdir(exist_ok=True)
    (HOME / "memory").mkdir(exist_ok=True)
    _ok(f"Dizin: {HOME}")

    # ── Step 2: Dil Seçimi ──
    _step(2, "Dil Seçimi")
    click.echo("      1) 🇹🇷 Türkçe")
    click.echo("      2) 🇬🇧 English")
    lang_choice = click.prompt(click.style("      Seçim", fg="blue"), default="1", show_default=False)
    lang = "tr" if lang_choice == "1" else "en"
    cfg["language"] = lang
    _ok(f"Dil: {'Türkçe' if lang == 'tr' else 'English'}")

    # ── Step 3: Model Seçimi ──
    _step(3, "LLM Model Seçimi")
    click.echo()
    click.echo("      Hangi AI modelini kullanmak istiyorsun?")
    click.echo()

    # Check Ollama
    ollama_up = _ollama_ok()
    local_models = _ollama_models() if ollama_up else []

    options = []
    idx = 1

    # Ollama local models
    if local_models:
        click.echo(click.style("      📦 Yerel Ollama Modelleri:", bold=True))
        for m in local_models:
            click.echo(f"        {idx}) {m}")
            options.append(("ollama", m, f"ollama/{m}"))
            idx += 1
        click.echo()

    # Cloud providers
    click.echo(click.style("      ☁️  Bulut Modelleri:", bold=True))
    cloud = [
        ("openai", "gpt-4o", "gpt-4o"),
        ("openai", "gpt-4o-mini", "gpt-4o-mini"),
        ("anthropic", "claude-sonnet-4-20250514", "claude-sonnet-4-20250514"),
        ("google", "gemini-2.0-flash", "gemini-2.0-flash"),
        ("groq", "llama-3.3-70b-versatile", "llama-3.3-70b-versatile (ücretsiz)"),
    ]
    for provider, model_name, label in cloud:
        click.echo(f"        {idx}) {label}")
        options.append((provider, model_name, label))
        idx += 1

    click.echo()
    if not ollama_up:
        click.echo(click.style("      💡 Ollama yüklü değil/kapalı. Yerel model için: brew install ollama && ollama serve", fg="bright_black"))
        click.echo()

    choice = click.prompt(
        click.style("      Model numarası", fg="blue"),
        default="1", show_default=False
    )
    try:
        chosen = options[int(choice) - 1]
    except (IndexError, ValueError):
        chosen = options[0] if options else ("openai", "gpt-4o", "gpt-4o")

    provider, model_name, label = chosen
    cfg["provider"] = provider
    cfg["model"] = f"{provider}/{model_name}" if provider == "ollama" else model_name
    cfg["model_name"] = model_name
    _ok(f"Model: {cfg['model']} ({provider})")

    # ── Step 4: API Key (cloud only) ──
    if provider != "ollama":
        _step(4, f"{provider.capitalize()} API Key")
        env_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "groq": "GROQ_API_KEY",
        }
        env_key = env_map.get(provider, "")
        existing = os.environ.get(env_key, "")

        if existing:
            _ok(f"{env_key} zaten ayarlı (env)")
        else:
            key = click.prompt(
                click.style(f"      {env_key}", fg="blue"),
                default="", show_default=False, hide_input=True
            )
            if key:
                cfg.setdefault("api_keys", {})[provider] = key
                os.environ[env_key] = key
                _ok("API key kaydedildi")
            else:
                _warn(f"Atlandı. Sonra: export {env_key}=sk-xxx")
    else:
        _step(4, "Yerel Model — API key gerekmez")
        if not local_models:
            click.echo(click.style("      💡 Ollama'da henüz model yok. İndirilsin mi?", fg="yellow"))
            want_pull = click.confirm(
                click.style(f"      '{model_name}' indirilsin mi?", fg="blue"),
                default=True
            )
            if want_pull:
                click.echo(f"      ⏳ '{model_name}' indiriliyor (birkaç dakika sürebilir)...")
                try:
                    subprocess.run(["ollama", "pull", model_name], check=True, timeout=600)
                    _ok(f"Model '{model_name}' indirildi")
                except subprocess.TimeoutExpired:
                    _warn("İndirme zaman aşımına uğradı. Terminalde 'ollama pull " + model_name + "' dene.")
                except Exception as e:
                    _warn(f"İndirme hatası: {e}. Terminalde 'ollama pull {model_name}' dene.")
            else:
                _warn(f"Sonra: ollama pull {model_name}")
        else:
            _ok("Ollama ayarlandı")

    # ── Step 5: Telegram ──
    _step(5, "Telegram Bağlantısı (opsiyonel)")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        _ok("TELEGRAM_BOT_TOKEN zaten ayarlı")
        cfg.setdefault("channels", [])
        if not any(c.get("type") == "telegram" for c in cfg["channels"]):
            cfg["channels"].append({"type": "telegram", "enabled": True, "token": "$TELEGRAM_BOT_TOKEN"})
    else:
        want_tg = click.confirm(
            click.style("      Telegram botu bağlamak ister misin?", fg="blue"),
            default=False
        )
        if want_tg:
            token = click.prompt(
                click.style("      Bot token (@BotFather'dan)", fg="blue"),
                default="", show_default=False
            )
            if token:
                os.environ["TELEGRAM_BOT_TOKEN"] = token
                cfg.setdefault("channels", []).append({
                    "type": "telegram", "enabled": True, "token": token
                })
                _ok("Telegram botu eklendi")
            else:
                _warn("Atlandı")
        else:
            _info("Telegram atlandı. Sonra dashboard'dan ekleyebilirsin.")

    # ── Step 6: Config for elyan_config compatibility ──
    _step(6, "Konfigürasyon Oluşturuluyor")

    # Build full config compatible with elyan_config.py / gateway server
    full_cfg = {
        "version": VERSION,
        "app_name": "Elyan",
        "environment": "production",
        "agent": {
            "autonomous": True,
            "personality": "professional",
            "language": lang,
        },
        "models": {
            "default": {
                "provider": provider,
                "model": model_name,
            },
            "fallback": {
                "provider": "openai",
                "model": "gpt-4o",
            },
            "local": {
                "provider": "ollama",
                "model": local_models[0] if local_models else "llama3.2:3b",
                "baseUrl": "http://localhost:11434",
            },
        },
        "channels": cfg.get("channels", []),
        "tools": {
            "allow": ["group:fs", "group:web", "group:ui", "group:runtime",
                       "group:messaging", "group:automation", "group:memory", "browser"],
            "deny": ["exec"],
            "requireApproval": ["delete_file", "write_file"],
        },
        "memory": {
            "enabled": True,
            "path": "~/.elyan/memory/",
            "maxSizeMB": 500,
        },
        "gateway": {
            "port": PORT,
            "host": "127.0.0.1",
        },
        "security": {
            "operatorMode": "Confirmed",
            "requirePlanApproval": True,
            "auditLog": True,
            "rateLimitPerMinute": 20,
        },
        "monthly_budget_usd": 20.0,
        # CLI state
        "model": cfg.get("model", model_name),
        "provider": provider,
        "model_name": model_name,
        "language": lang,
    }

    # Merge API keys and register with orchestrator
    if "api_keys" in cfg:
        full_cfg["api_keys"] = cfg["api_keys"]
        # Register keys with model_orchestrator for immediate use
        try:
            from core.model_orchestrator import model_orchestrator
            for prov, key in cfg["api_keys"].items():
                if key:
                    model_orchestrator.add_provider(prov, key)
                    logger.info(f"Registered provider: {prov}")
        except Exception as e:
            logger.debug(f"Orchestrator registration deferred: {e}")

    # Mark setup complete for LLM setup manager
    try:
        from core.llm_setup import get_llm_setup
        get_llm_setup().mark_setup_complete()
    except Exception:
        pass

    _save(full_cfg)
    _ok(f"Config: {CFG_FILE}")

    # ── Done ──
    _line()
    click.echo()
    click.echo(click.style("  ✅ Kurulum tamamlandı!", fg="green", bold=True))
    click.echo()
    click.echo("  Sonraki adımlar:")
    click.echo(click.style("    elyan start", fg="cyan") + "       — Gateway'i başlat")
    click.echo(click.style("    elyan dashboard", fg="cyan") + "   — Web kontrol panelini aç")
    click.echo(click.style("    elyan status", fg="cyan") + "      — Sistem durumunu kontrol et")
    click.echo(click.style("    elyan models", fg="cyan") + "      — Model değiştir")
    click.echo()


# ═══════════════════════════════════════════════════════════════
#  elyan start / stop / restart
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--port", default=PORT, help="Port")
@click.option("--daemon", is_flag=True, help="Arka planda çalıştır")
def start(port, daemon):
    """🚀 Gateway'i başlat."""
    if not CFG_FILE.exists():
        click.echo("⚠️  Önce kurulum yapın: elyan setup")
        return

    if _port_alive(port):
        click.echo(f"⚠️  Zaten çalışıyor (port {port})")
        click.echo(f"   Dashboard: http://localhost:{port}/dashboard")
        return

    cfg = _cfg()
    model = cfg.get("model", "not set")
    _banner()
    click.echo(f"  Model:    {model}")
    click.echo(f"  Port:     {port}")

    if daemon:
        (HOME / "logs").mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0,'{project_root}'); "
             f"from main import _run_gateway; _run_gateway({port})"],
            stdout=open(HOME / "logs" / "gateway.out.log", "a"),
            stderr=open(HOME / "logs" / "gateway.err.log", "a"),
            start_new_session=True, cwd=str(project_root)
        )
        click.echo(f"  ✅ Arka planda başlatıldı (PID: {proc.pid})")
        click.echo(f"  Dashboard: http://localhost:{port}/dashboard")
    else:
        _run_gateway(port)


def _run_gateway(port: int):
    os.environ["ELYAN_PORT"] = str(port)
    # Load .env before imports so tokens are available
    _load_dotenv()
    from core.agent import Agent
    from core.gateway.server import ElyanGatewayServer
    import asyncio

    agent = Agent()
    server = ElyanGatewayServer(agent)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        if not loop.run_until_complete(agent.initialize()):
            click.echo("❌ Başlatma hatası.")
            return
        loop.run_until_complete(server.start(port=port))
        click.echo(f"\n  ✅ Elyan v{VERSION} çalışıyor — port {port}")
        click.echo(f"  🌐 Dashboard: http://localhost:{port}/dashboard")
        click.echo("  Ctrl+C ile durdur.\n")
        loop.run_forever()
    except KeyboardInterrupt:
        click.echo("\n  🛑 Durduruldu.")
    finally:
        try:
            loop.run_until_complete(server.stop())
        except Exception:
            pass
        loop.close()


@cli.command()
@click.option("--port", default=PORT)
def stop(port):
    """🛑 Gateway'i durdur."""
    try:
        r = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
        pids = r.stdout.strip()
        if pids:
            for pid in pids.split("\n"):
                subprocess.run(["kill", "-9", pid.strip()], capture_output=True)
            click.echo(f"🛑 Durduruldu (port {port})")
        else:
            click.echo(f"ℹ️  Port {port}'da çalışan yok")
    except Exception as e:
        click.echo(f"⚠️  {e}")


@cli.command()
@click.option("--port", default=PORT)
def restart(port):
    """🔄 Gateway'i yeniden başlat."""
    ctx = click.get_current_context()
    ctx.invoke(stop, port=port)
    time.sleep(1)
    ctx.invoke(start, port=port, daemon=False)


# ═══════════════════════════════════════════════════════════════
#  elyan dashboard
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--port", default=PORT)
def dashboard(port):
    """🖥️  Dashboard panelini aç."""
    import webbrowser
    url = f"http://localhost:{port}/dashboard"
    if not _port_alive(port):
        click.echo("⚠️  Gateway kapalı. Önce başlat:")
        click.echo(f"   elyan start --daemon")
        click.echo()
        want = click.confirm("   Şimdi başlatayım mı? (arka planda)", default=True)
        if want:
            ctx = click.get_current_context()
            ctx.invoke(start, port=port, daemon=True)
            time.sleep(2)
        else:
            return

    click.echo(f"🌐 {url}")
    webbrowser.open(url)


# ═══════════════════════════════════════════════════════════════
#  elyan models
# ═══════════════════════════════════════════════════════════════

@cli.group(invoke_without_command=True)
@click.pass_context
def models(ctx):
    """🤖 Model yönetimi."""
    if ctx.invoked_subcommand is None:
        cfg = _cfg()
        provider, current = _configured_model(cfg)

        click.echo(f"\n🤖 Model: {click.style(current, bold=True)} ({provider})")
        _line()

        # API Keys
        for name, env in [("OpenAI", "OPENAI_API_KEY"), ("Anthropic", "ANTHROPIC_API_KEY"),
                          ("Google", "GOOGLE_API_KEY"), ("Groq", "GROQ_API_KEY")]:
            val = os.environ.get(env, "")
            cfg_keys = cfg.get("api_keys", {})
            has_cfg = bool(cfg_keys.get(name.lower(), ""))
            status = "🟢" if (val or has_cfg) else "🔴"
            click.echo(f"  {status} {name:<12}")

        # Ollama
        ollama = _ollama_ok()
        click.echo(f"\n  Ollama: {'🟢 running' if ollama else '🔴 kapalı'}")
        if ollama:
            for m in _ollama_models():
                marker = " ◀" if m in current else ""
                click.echo(f"    • {m}{marker}")

        click.echo(f"\n  Komutlar:")
        click.echo(f"    elyan models use <model>     Model seç")
        click.echo(f"    elyan models ollama          Yerel modeller")
        click.echo(f"    elyan models pull <model>    Model indir")
        click.echo()


@models.command("use")
@click.argument("model")
def models_use(model):
    """Model seç (örn: gpt-4o, ollama/llama3.2:3b)."""
    cfg = _cfg()
    if "/" in model:
        provider, model_name = model.split("/", 1)
    elif model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
        provider, model_name = "openai", model
    elif model.startswith("claude"):
        provider, model_name = "anthropic", model
    elif model.startswith("gemini"):
        provider, model_name = "google", model
    else:
        if _ollama_ok() and model in _ollama_models():
            provider, model_name = "ollama", model
        else:
            provider, model_name = "openai", model

    cfg["model"] = model
    cfg["provider"] = provider
    cfg["model_name"] = model_name
    # Sync with elyan_config format
    model_entry = {"provider": provider, "model": model_name}
    cfg.setdefault("models", {})["default"] = dict(model_entry)
    # Sync all roles so neural router uses the same model
    cfg["models"]["roles"] = {
        "reasoning": dict(model_entry),
        "inference": dict(model_entry),
        "creative": dict(model_entry),
        "code": dict(model_entry),
    }
    _save(cfg)
    click.echo(f"  ✅ {model} ({provider})")


@models.command("ollama")
def models_ollama():
    """Yerel Ollama modellerini listele."""
    if not _ollama_ok():
        click.echo("  🔴 Ollama kapalı. Başlat: ollama serve")
        return
    local = _ollama_models()
    click.echo(f"\n📦 Ollama ({len(local)})")
    for m in local:
        click.echo(f"  • {m}")
    click.echo(f"\n  Kullan: elyan models use ollama/{local[0] if local else 'model'}")
    click.echo()


@models.command("pull")
@click.argument("model")
def models_pull(model):
    """Ollama model indir."""
    click.echo(f"  ⬇️  İndiriliyor: {model}")
    try:
        proc = subprocess.Popen(["ollama", "pull", model],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            click.echo(f"  {line.rstrip()}")
        proc.wait()
        click.echo(f"  {'✅ İndirildi' if proc.returncode == 0 else '❌ Hata'}")
    except FileNotFoundError:
        click.echo("  ❌ ollama yüklü değil: brew install ollama")


@models.command("key")
@click.argument("provider")
@click.argument("api_key")
def models_key(provider, api_key):
    """API key kaydet."""
    cfg = _cfg()
    cfg.setdefault("api_keys", {})[provider.lower()] = api_key
    env_map = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
               "google": "GOOGLE_API_KEY", "groq": "GROQ_API_KEY"}
    env = env_map.get(provider.lower())
    if env:
        os.environ[env] = api_key
    _save(cfg)
    click.echo(f"  ✅ {provider} key kaydedildi")


# ═══════════════════════════════════════════════════════════════
#  elyan status
# ═══════════════════════════════════════════════════════════════

@cli.command()
def status():
    """📊 Sistem durumu."""
    cfg = _cfg()
    provider, model = _configured_model(cfg)
    health = _gateway_health()
    gw = bool(health.get("reachable"))
    gw_label = "🟢 ONLINE" if gw and health.get("ok") is not False else ("🟡 DEGRADED" if gw else "🔴 OFFLINE")

    click.echo(f"\n🧠 Elyan v{VERSION}")
    click.echo(f"{'═' * 40}")
    click.echo(f"  Model:    {model} ({provider})")
    click.echo(f"  Gateway:  {gw_label}")
    click.echo(f"  Ollama:   {'🟢' if _ollama_ok() else '🔴'}")
    click.echo(f"  Python:   {sys.version.split()[0]}")
    if gw:
        click.echo(f"  Dashboard: http://localhost:{PORT}/dashboard")
        if health.get("health_status"):
            click.echo(f"  Health:   {health.get('health_status')}")
    click.echo()

    modules = {
        "Reasoning": "core.reasoning.chain_of_thought",
        "Task Decomposer": "core.reasoning.task_decomposer",
        "Code Validator": "core.reasoning.code_validator",
        "Deep Researcher": "core.reasoning.deep_researcher",
        "Secure Vault": "core.security.secure_vault",
        "Prompt Firewall": "core.security.prompt_firewall",
        "Plugin Manager": "core.plugins.plugin_manager",
        "Crash Protection": "core.resilience.global_handler",
    }
    ok = 0
    for name, mod in modules.items():
        try:
            __import__(mod)
            click.echo(f"  🟢 {name}")
            ok += 1
        except Exception:
            click.echo(f"  🔴 {name}")
    click.echo(f"\n  Modüller: {ok}/{len(modules)}")
    click.echo()


# ═══════════════════════════════════════════════════════════════
#  elyan doctor
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--fix", is_flag=True, help="Sorunları otomatik düzelt")
def doctor(fix):
    """🩺 Sistem sağlık kontrolü."""
    issues = 0
    click.echo(f"\n🩺 Elyan Doctor")
    click.echo(f"{'─' * 40}\n")

    # Python
    py = sys.version_info
    click.echo(f"  {'✅' if py >= (3, 10) else '❌'} Python {py.major}.{py.minor}")
    if py < (3, 10): issues += 1

    # Home
    if HOME.exists():
        click.echo(f"  ✅ Home: {HOME}")
    elif fix:
        HOME.mkdir(parents=True, exist_ok=True)
        click.echo(f"  ✅ Oluşturuldu: {HOME}")
    else:
        click.echo(f"  ⚠️  Home yok → elyan setup")
        issues += 1

    # Config
    if CFG_FILE.exists():
        click.echo(f"  ✅ Config OK")
    elif fix:
        _save({"model": "", "provider": ""})
        click.echo(f"  ✅ Config oluşturuldu")
    else:
        click.echo(f"  ⚠️  Config yok → elyan setup")
        issues += 1

    # Model
    cfg = _cfg()
    provider, m = _configured_model(cfg)
    if m and m != "not set":
        click.echo(f"  ✅ Model: {m} ({provider})")
    else:
        click.echo(f"  ⚠️  Model seçilmemiş → elyan models use <model>")
        issues += 1

    # Gateway & Ollama
    health = _gateway_health()
    gateway_ok = bool(health.get("reachable"))
    gateway_line = "offline"
    if gateway_ok:
        gateway_line = str(health.get("health_status") or "online")
    click.echo(f"  {'✅' if gateway_ok and health.get('ok') is not False else 'ℹ️ '} Gateway {gateway_line}")
    click.echo(f"  {'✅' if _ollama_ok() else 'ℹ️ '} Ollama {'running' if _ollama_ok() else 'kapalı'}")

    # Deps
    for dep in ["cryptography", "aiohttp", "httpx", "click", "psutil"]:
        try:
            __import__(dep)
            click.echo(f"  ✅ {dep}")
        except ImportError:
            click.echo(f"  ❌ {dep}")
            issues += 1
            if fix:
                subprocess.run([sys.executable, "-m", "pip", "install", dep, "-q"], capture_output=True)
                click.echo(f"     → kuruldu")

    click.echo(f"\n{'─' * 40}")
    if issues:
        click.echo(f"  ⚠️  {issues} sorun" + (" → elyan doctor --fix" if not fix else ""))
    else:
        click.echo(f"  ✅ Her şey yolunda!")
    click.echo()


# ═══════════════════════════════════════════════════════════════
#  elyan team
# ═══════════════════════════════════════════════════════════════

@cli.group(invoke_without_command=True)
@click.pass_context
def team(ctx):
    """🏢 Ajan takımı."""
    if ctx.invoked_subcommand is None:
        from core.multi_agent.specialists import get_specialist_registry
        click.echo(f"\n{get_specialist_registry().format_team_status()}\n")


@team.command("test")
@click.argument("message")
def team_test(message):
    """Bir mesajı hangi ajan yakalar test et."""
    from core.multi_agent.specialists import get_specialist_registry
    s = get_specialist_registry().select_for_input(message)
    click.echo(f"\n  \"{message}\" → {s.emoji} {s.name} ({s.role})\n")


# ═══════════════════════════════════════════════════════════════
#  elyan config / logs
# ═══════════════════════════════════════════════════════════════

@cli.command()
def config():
    """⚙️  Mevcut konfigürasyonu göster."""
    cfg = _cfg()
    click.echo(f"\n⚙️  {CFG_FILE}")
    click.echo(json.dumps(cfg, indent=2, ensure_ascii=False))
    click.echo()


@cli.command()
@click.option("--tail", default=20)
def logs(tail):
    """📜 Son logları göster."""
    dirs = [HOME / "logs", project_root / "logs"]
    for d in dirs:
        if d.exists():
            files = sorted(d.glob("*.log"), reverse=True)
            if files:
                lines = files[0].read_text(errors="ignore").strip().split("\n")
                click.echo(f"\n📜 {files[0].name} (son {min(tail, len(lines))}):\n")
                for line in lines[-tail:]:
                    click.echo(f"  {line}")
                click.echo()
                return
    click.echo("📜 Log bulunamadı.\n")


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def _cli_main():
    (HOME / "logs").mkdir(parents=True, exist_ok=True)
    cli()

def main():
    _cli_main()

if __name__ == "__main__":
    _cli_main()
