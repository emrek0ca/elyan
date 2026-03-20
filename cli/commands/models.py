"""models.py — Model yönetimi CLI"""
import json
from config.elyan_config import elyan_config
from core.model_catalog import QWEN_LIGHT_OLLAMA_MODEL, default_model_for_provider, normalize_model_name


def _default_model_for_provider(provider: str) -> str:
    return default_model_for_provider(provider)


def _sync_roles_to_default(provider: str, model: str) -> None:
    provider = str(provider or "").strip().lower()
    model = normalize_model_name(provider, model)
    router_provider = str(elyan_config.get("models.local.provider", "ollama"))
    router_model = normalize_model_name(
        router_provider,
        str(elyan_config.get("models.local.model", _default_model_for_provider(router_provider))),
    )
    local_first = bool(elyan_config.get("agent.model.local_first", True))
    if provider == "ollama":
        router_provider = "ollama"
        router_model = model
        elyan_config.set("models.local.provider", "ollama")
        elyan_config.set("models.local.model", model)
    router_role = {"provider": router_provider, "model": router_model} if local_first else {"provider": provider, "model": model}
    worker_role = {"provider": provider, "model": model}
    role_map = {
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
    elyan_config.set("models.roles", role_map)


def _is_model_consistent(provider: str, model: str) -> bool:
    p = (provider or "").lower()
    m = (model or "").lower()
    if not p or not m:
        return True
    if p == "openai":
        return m.startswith(("gpt-", "o1", "o3", "gpt4"))
    if p == "anthropic":
        return "claude" in m
    if p == "google":
        return "gemini" in m
    if p == "groq":
        return m.startswith(("llama", "mixtral", "qwen", "deepseek"))
    return True

def run(args):
    sub = getattr(args, "subcommand", None)
    if not sub:
        print("Usage: elyan models [list|status|test|use|cost|ollama]")
        return

    if sub == "list":
        _list(getattr(args, "provider", None))
    elif sub == "status":
        _status()
    elif sub == "test":
        _test(getattr(args, "provider", None))
    elif sub == "use":
        _use(getattr(args, "name", None))
    elif sub in ("set-default", "set_default"):
        _use(getattr(args, "name", None))
    elif sub in ("set-fallback", "set_fallback"):
        _set_fallback(getattr(args, "name", None))
    elif sub == "cost":
        _cost(getattr(args, "period", "30d"))
    elif sub == "ollama":
        _ollama(getattr(args, "action", "list"), getattr(args, "name", None))
    elif sub == "add":
        _add(args)
    elif sub == "ollama-check":
        _ollama("list", None)
    else:
        print(f"Bilinmeyen alt komut: {sub}")


def _list(provider_filter=None):
    print(f"{'*':<2} {'SAĞLAYICI':<14} {'MODEL':<30} {'DURUM'}")
    print("─" * 60)
    try:
        from core.model_orchestrator import model_orchestrator as mo
        for p_name, data in mo.providers.items():
            if provider_filter and provider_filter.lower() != p_name.lower():
                continue
            active = "*" if p_name == mo.active_provider else " "
            model = data.get("model", "?")
            status = data.get("status", "?")
            print(f"{active} {p_name:<14} {model:<30} {status}")
    except Exception:
        # Config'den göster
        default = elyan_config.get("models.default", {})
        fallback = elyan_config.get("models.fallback", {})
        print(f"* {'default':<14} {default.get('model','?'):<30} yapılandırılmış")
        if fallback:
            print(f"  {'fallback':<14} {fallback.get('model','?'):<30} yapılandırılmış")


def _status():
    print("\n📡  Model Durumu")
    default = elyan_config.get("models.default", {})
    fallback = elyan_config.get("models.fallback", {})
    d_provider = default.get("provider", "?")
    d_model = default.get("model", "?")
    print(f"  Varsayılan : {d_provider} / {d_model}")
    if not _is_model_consistent(d_provider, d_model):
        print("  ⚠️ Tutarsızlık: provider/model eşleşmiyor. Örn: elyan models set-default openai/gpt-4o")
    if fallback:
        f_provider = fallback.get("provider", "?")
        f_model = fallback.get("model", "?")
        print(f"  Yedek      : {f_provider} / {f_model}")
        if not _is_model_consistent(f_provider, f_model):
            print("  ⚠️ Yedek model provider ile uyumsuz görünüyor.")
    local = elyan_config.get("models.local", {})
    if local:
        print(f"  Yerel      : {local.get('provider','ollama')} / {local.get('model','?')}")


def _test(provider=None):
    import httpx
    port = elyan_config.get("gateway.port", 18789)
    print(f"Model bağlantısı test ediliyor ({provider or 'varsayılan'})...")
    try:
        resp = httpx.post(
            f"http://localhost:{port}/api/models/test",
            json={"provider": provider},
            timeout=20,
        )
        data = resp.json()
        ok = data.get("ok", False)
        print(f"{'✅' if ok else '❌'}  {data.get('message', 'Yanıt alındı.')}")
        if data.get("latency_ms"):
            print(f"  Gecikme: {data['latency_ms']}ms")
    except Exception as e:
        # Gateway yok, doğrudan test et
        _direct_test(provider)


def _direct_test(provider=None):
    try:
        from core.llm_client import LLMClient
        client = LLMClient()
        import asyncio
        result = asyncio.run(client.chat("Merhaba, bu bir test."))
        if result:
            print(f"✅  Model yanıt verdi: {result[:80]}...")
        else:
            print("❌  Model boş yanıt döndürdü.")
    except Exception as e:
        print(f"❌  Test başarısız: {e}")


def _use(name: str):
    if not name:
        print("Hata: model adı gerekli.")
        return
    # provider/model formatı: "groq/llama-3.3-70b-versatile" veya sadece "groq"
    if "/" in name:
        provider, model = name.split("/", 1)
        provider = provider.strip()
        model = normalize_model_name(provider, model.strip())
    else:
        provider = name.strip()
        model = _default_model_for_provider(provider)

    elyan_config.set("models.default.provider", provider)
    elyan_config.set("models.default.model", model)
    _sync_roles_to_default(provider, model)
    print(f"✅  Varsayılan: {provider} / {model}")
    print("✅  Rol bazlı model eşlemeleri varsayılan model ile senkronlandı.")


def _set_fallback(name: str):
    if not name:
        print("Hata: model adı gerekli (örn: openai/gpt-4o).")
        return
    if "/" in name:
        provider, model = name.split("/", 1)
        provider = provider.strip()
        model = normalize_model_name(provider, model.strip())
    else:
        provider = name.strip()
        model = _default_model_for_provider(provider)
    elyan_config.set("models.fallback.provider", provider)
    elyan_config.set("models.fallback.model", model)
    print(f"✅  Yedek model: {provider} / {model}")


def _cost(period: str = "30d"):
    import httpx
    port = elyan_config.get("gateway.port", 18789)
    try:
        resp = httpx.get(f"http://localhost:{port}/api/analytics", timeout=5)
        data = resp.json()
        cost = data.get("total_cost_usd", 0)
        budget = elyan_config.get("monthly_budget_usd", 20)
        print(f"\n💰  Maliyet Analizi ({period})")
        print(f"  Toplam harcama : ${cost:.4f}")
        print(f"  Aylık bütçe   : ${budget:.2f}")
        print(f"  Kalan          : ${max(0, budget - cost):.4f}")
    except Exception:
        try:
            from core.pricing_tracker import get_pricing_tracker
            tracker = get_pricing_tracker()
            stats = tracker.get_stats() if hasattr(tracker, "get_stats") else {}
            print(f"\n💰  Maliyet (son {period}): ${stats.get('total_usd', 0):.4f}")
        except Exception as e:
            print(f"Maliyet verisi alınamadı: {e}")


def _ollama(action: str, name: str = None):
    try:
        from utils.ollama_helper import OllamaHelper
        if action == "list":
            if not OllamaHelper.ensure_available(allow_install=True, start_service=True):
                print("❌  Ollama otomatik kurulamadı.")
                print(f"  Kurulum: {OllamaHelper.get_install_command()}")
                return
            models = OllamaHelper.list_local_models()
            if models:
                print("Yerel Ollama modelleri:")
                for m in models:
                    print(f"  • {m}")
                if QWEN_LIGHT_OLLAMA_MODEL not in models:
                    print(f"  ℹ️ Hafif ücretsiz seçenek: {QWEN_LIGHT_OLLAMA_MODEL}")
            else:
                print("Yüklü model yok. 'ollama pull llama3' ile indirin.")
        elif action == "pull" and name:
            import subprocess
            model_name = normalize_model_name("ollama", name)
            print(f"Modeli indiriliyor: {model_name}...")
            if not OllamaHelper.ensure_available(allow_install=True, start_service=True):
                print("❌  Ollama otomatik kurulamadı.")
                print(f"  Kurulum: {OllamaHelper.get_install_command()}")
                return
            subprocess.run(["ollama", "pull", model_name])
        elif action == "start":
            if not OllamaHelper.ensure_available(allow_install=True, start_service=True):
                print("❌  Ollama otomatik kurulamadı.")
                print(f"  Kurulum: {OllamaHelper.get_install_command()}")
                return
            print("✅  Ollama başlatıldı.")
        elif action == "stop":
            import subprocess
            subprocess.run(["pkill", "-f", "ollama"])
            print("🛑  Ollama durduruldu.")
    except ImportError as e:
        print(f"Hata: {e}")


def _add(args):
    provider = getattr(args, "provider", None)
    key = getattr(args, "key", None)
    model = getattr(args, "model", None)
    if not provider or not key:
        print("Hata: --provider ve --key gereklidir.")
        return
    try:
        from core.model_orchestrator import model_orchestrator as mo
        mo.add_provider(provider, key, model)
        print(f"✅  {provider} eklendi.")
    except Exception as e:
        print(f"Hata: {e}")
