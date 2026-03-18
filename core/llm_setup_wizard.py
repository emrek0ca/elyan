"""
LLM Setup Wizard — Interactive first-run CLI setup

Runs automatically on first launch. Also callable via `elyan setup` command.
Guides user through:
1. Provider selection (Groq/Gemini/Ollama/OpenAI/etc.)
2. API key entry and validation
3. Ollama model download (if chosen)
4. Quick test to confirm everything works
"""

import asyncio
import os
import sys
from typing import Optional

from utils.logger import get_logger

logger = get_logger("setup_wizard")


# ── ANSI Colors (works in most terminals) ──────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BLUE = "\033[94m"
RESET = "\033[0m"


def _print_header():
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════╗
║          ELYAN — İlk Kurulum Sihirbazı           ║
╚══════════════════════════════════════════════════╝{RESET}

{DIM}Elyan'ın çalışması için en az 1 LLM provider gerekli.
Aşağıdan birini seç — sonra istediğin zaman dashboard'dan
daha fazla ekleyebilirsin.{RESET}
""")


def _print_providers():
    print(f"""
{BOLD}Seçenekler:{RESET}

  {GREEN}[1]{RESET} Groq          — {GREEN}Ücretsiz{RESET}, çok hızlı {DIM}(Önerilen){RESET}
  {GREEN}[2]{RESET} Google Gemini  — {GREEN}Ücretsiz{RESET}, güçlü
  {BLUE}[3]{RESET} Ollama         — {GREEN}Ücretsiz{RESET}, tamamen lokal {DIM}(İnternetsiz){RESET}
  {YELLOW}[4]{RESET} OpenAI         — Ücretli, GPT-4o
  {YELLOW}[5]{RESET} Anthropic      — Ücretli, Claude
  {DIM}[6]{RESET} DeepSeek       — Uygun fiyatlı
  {DIM}[S]{RESET} Hepsini atla   — {DIM}Sonra ayarlarım{RESET}
""")


CHOICE_MAP = {
    "1": "groq",
    "2": "google",
    "3": "ollama",
    "4": "openai",
    "5": "anthropic",
    "6": "deepseek",
}


async def run_setup_wizard(force: bool = False) -> bool:
    """
    Interactive setup wizard. Returns True if at least 1 provider configured.
    """
    from core.llm_setup import get_llm_setup, PROVIDERS

    setup = get_llm_setup()

    if not force and not setup.is_first_run():
        return True  # Already set up

    _print_header()
    _print_providers()

    configured_any = False

    while True:
        choice = input(f"{BOLD}Seçimin (1-6 veya S): {RESET}").strip().upper()

        if choice == "S":
            if not configured_any:
                print(f"\n{YELLOW}⚠ Hiçbir provider ayarlanmadı. Elyan sınırlı çalışacak.{RESET}")
                print(f"{DIM}  İstediğin zaman 'elyan setup' veya dashboard'dan ayarlayabilirsin.{RESET}\n")
            break

        provider = CHOICE_MAP.get(choice)
        if not provider:
            print(f"{RED}Geçersiz seçim. 1-6 arası veya S gir.{RESET}")
            continue

        if provider == "ollama":
            success = await _setup_ollama(setup)
        else:
            success = await _setup_api_provider(setup, provider)

        if success:
            configured_any = True
            print(f"\n{GREEN}✓ {PROVIDERS[provider]['name']} hazır!{RESET}")

            more = input(f"\n{DIM}Başka provider eklemek ister misin? (e/h): {RESET}").strip().lower()
            if more not in ("e", "evet", "y", "yes"):
                break
            _print_providers()
        else:
            retry = input(f"\n{DIM}Tekrar denemek ister misin? (e/h): {RESET}").strip().lower()
            if retry not in ("e", "evet", "y", "yes"):
                _print_providers()

    # Quick test
    if configured_any:
        print(f"\n{CYAN}Hızlı test yapılıyor...{RESET}")
        await _quick_test(setup)

    setup.mark_setup_complete()

    print(f"""
{GREEN}{BOLD}╔══════════════════════════════════════════════════╗
║              Kurulum tamamlandı!                  ║
╚══════════════════════════════════════════════════╝{RESET}

{DIM}Provider'ları yönetmek için:
  • Dashboard: http://localhost:18789 → LLM sekmesi
  • CLI:       elyan setup{RESET}
""")
    return configured_any


async def _setup_api_provider(setup, provider: str) -> bool:
    """Setup an API-key-based provider."""
    from core.llm_setup import PROVIDERS

    info = PROVIDERS[provider]
    print(f"\n{BOLD}— {info['name']} Kurulumu —{RESET}")
    print(f"{DIM}{info['description']}{RESET}")
    print(f"\n{CYAN}API key al:{RESET} {info['signup_url']}")
    print(f"{DIM}(Ücretsiz hesap aç → API Keys → Create Key → Kopyala){RESET}\n")

    api_key = input(f"{BOLD}API Key: {RESET}").strip()
    if not api_key:
        print(f"{RED}Key girilmedi.{RESET}")
        return False

    print(f"{DIM}Test ediliyor...{RESET}", end=" ", flush=True)
    result = await setup.save_api_key(provider, api_key)

    if result.get("success") and result.get("reachable"):
        print(f"{GREEN}✓ Bağlantı başarılı!{RESET}")
        return True
    elif result.get("success"):
        print(f"{YELLOW}⚠ Key kaydedildi ama bağlantı doğrulanamadı.{RESET}")
        print(f"{DIM}  Key'i kontrol edebilirsin: {info['signup_url']}{RESET}")
        return True  # Key saved, might work
    else:
        print(f"{RED}✗ Hata: {result.get('error', 'Bilinmeyen hata')}{RESET}")
        return False


async def _setup_ollama(setup) -> bool:
    """Setup Ollama (local LLM)."""
    print(f"\n{BOLD}— Ollama Kurulumu (Lokal Model) —{RESET}")

    status = await setup.ollama_status()

    if not status["running"]:
        print(f"""
{YELLOW}Ollama şu an çalışmıyor.{RESET}

{BOLD}Kurulum:{RESET}
  1. {CYAN}https://ollama.ai/download{RESET} adresinden indir ve kur
  2. Terminalde çalıştır: {BOLD}ollama serve{RESET}
  3. Sonra bu sihirbazı tekrar çalıştır: {BOLD}elyan setup{RESET}
""")
        return False

    print(f"{GREEN}✓ Ollama çalışıyor!{RESET}\n")

    installed = status.get("models", [])
    if installed:
        print(f"{BOLD}Yüklü modeller:{RESET}")
        for m in installed:
            print(f"  {GREEN}•{RESET} {m['name']} ({m.get('size', '?')})")
        print()

    # Check if any model is available
    if installed:
        use_existing = input(f"{DIM}Mevcut modelleri kullanmak ister misin? (e/h): {RESET}").strip().lower()
        if use_existing in ("e", "evet", "y", "yes", ""):
            return True

    # Offer to download
    print(f"{BOLD}İndirilecek model seç:{RESET}\n")
    recommended = status.get("recommended", [])
    for i, rec in enumerate(recommended, 1):
        marker = f"{GREEN}[yüklü]{RESET}" if rec.get("installed") else ""
        print(f"  [{i}] {rec['name']:20s} {rec['size']:8s} — {rec['description']} {marker}")
    print(f"  [0] Atla\n")

    choice = input(f"{BOLD}Seçimin (1-{len(recommended)} veya 0): {RESET}").strip()
    try:
        idx = int(choice)
    except ValueError:
        idx = 0

    if idx == 0 and not installed:
        print(f"{YELLOW}⚠ Model yüklenmedi. Ollama çalışamaz.{RESET}")
        return False
    elif idx == 0:
        return True

    if 1 <= idx <= len(recommended):
        model_name = recommended[idx - 1]["name"]
        print(f"\n{CYAN}'{model_name}' indiriliyor... (Bu birkaç dakika sürebilir){RESET}")
        result = await setup.ollama_pull_model(model_name)
        if result.get("success"):
            print(f"{GREEN}✓ {model_name} başarıyla indirildi!{RESET}")
            return True
        else:
            print(f"{RED}✗ İndirme hatası: {result.get('error')}{RESET}")
            return bool(installed)  # OK if other models exist

    return bool(installed)


async def _quick_test(setup) -> bool:
    """Quick LLM test."""
    try:
        from core.llm_client import LLMClient
        client = LLMClient()
        result = await client.generate("Merhaba! Tek kelimeyle yanıt ver: çalışıyor musun?", role="chat")
        if result and "üzgünüm" not in result.lower()[:30]:
            print(f"{GREEN}✓ LLM yanıt verdi: {result[:60].strip()}{RESET}")
            return True
        else:
            print(f"{YELLOW}⚠ LLM yanıt verdi ama sınırlı: {result[:60].strip()}{RESET}")
            return True
    except Exception as e:
        print(f"{YELLOW}⚠ LLM test atlandı: {e}{RESET}")
        return False


# ── Standalone Entry Point ─────────────────────────────────────

def run_wizard_sync(force: bool = False) -> bool:
    """Synchronous wrapper for the wizard."""
    return asyncio.run(run_setup_wizard(force=force))


if __name__ == "__main__":
    run_wizard_sync(force=True)
