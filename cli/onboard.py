import os
import sys
import subprocess
import shutil
import time
from pathlib import Path
from config.elyan_config import elyan_config
from security.keychain import keychain, KeychainManager

class OnboardingWizard:
    def __init__(self):
        self.project_root = Path(__file__).resolve().parent.parent
        self.config_path = Path.home() / ".elyan" / "elyan.json"

    def _check_command(self, cmd):
        return shutil.which(cmd) is not None

    def run(self):
        print("\n" + "="*50)
        print("✨ ELYAN v18.0 - ONBOARDING WIZARD")
        print("="*50 + "\n")

        print("Sizi geleceğin asistanı ile tanıştırmak üzereyiz.")
        print("Hızlıca birkaç ayar yapalım.\n")

        # 1. System Checks
        print("🔍 Sistem Kontrolü:")
        
        # Docker Check
        has_docker = self._check_command("docker")
        status = "✅ Kurulu" if has_docker else "❌ Bulunamadı (Sandbox devre dışı kalacak)"
        print(f"  - Docker: {status}")
        elyan_config.set("sandbox.enabled", has_docker)
        
        # Ollama Check
        has_ollama = self._check_command("ollama")
        status = "✅ Kurulu" if has_ollama else "⚠️ Bulunamadı (Yerel LLM kullanılamaz)"
        print(f"  - Ollama: {status}")
        
        time.sleep(1)

        # 2. AI Provider Selection
        print("\n[1] AI Sağlayıcısı Seçin:")
        print("  1. Yerel (Ollama - Gizlilik için Önerilir)")
        print("  2. OpenAI (GPT-4o/o1)")
        print("  3. Google (Gemini 2.0 Flash/Pro)")
        print("  4. Groq (Llama-3 - Ultra Hızlı)")
        
        default_choice = "1" if has_ollama else "2"
        choice = input(f"\nSeçiminiz (1-4) [{default_choice}]: ").strip() or default_choice
        provider_map = {"1": "ollama", "2": "openai", "3": "google", "4": "groq"}
        provider = provider_map.get(choice, "ollama")
        model_defaults = {
            "ollama": "llama3.1:8b",
            "openai": "gpt-4o",
            "google": "gemini-2.0-flash",
            "groq": "llama-3.3-70b-versatile",
        }
        selected_model = model_defaults.get(provider, "gpt-4o")
        
        elyan_config.set("models.default.provider", provider)
        elyan_config.set("models.default.model", selected_model)

        # 3. API Key Setup
        if provider != "ollama":
            provider_env_map = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "google": "GOOGLE_API_KEY",
                "groq": "GROQ_API_KEY",
            }
            env_key = provider_env_map.get(provider, f"{provider.upper()}_API_KEY")
            key_name = KeychainManager.key_for_env(env_key) or env_key.lower()
            
            api_key = input(f"🔑 {env_key} girin: ").strip()
            if api_key:
                if keychain.set_key(key_name, api_key):
                    print(f"✅ Anahtar Keychain'e güvenli şekilde kaydedildi.")
                else:
                    print("⚠️ Keychain yazılamadı, sağlayıcı anahtarı ortam değişkeninden okunacak.")
        
        if provider == "ollama" and has_ollama:
            print("📦 Ollama üzerinden 'llama3.1:8b' ve 'deepseek-r1:8b' modellerinin yüklü olduğundan emin olun.")

        # 4. Neural Router Setup
        print("\n[2] Akıllı Yönlendirme (Neural Router):")
        print("  Elyan, isteğinizin karmaşıklığına göre otomatik model seçer.")
        print("  Örn: Kodlama için DeepSeek, Hızlı sohbet için Llama 3.")
        
        enable_router = input("\nNeural Router aktif olsun mu? (y/n) [y]: ").strip().lower() != "n"
        elyan_config.set("router.enabled", enable_router)
        # Keep role routing consistent with selected default provider/model.
        if enable_router:
            role_map = {
                "reasoning": {"provider": provider, "model": selected_model},
                "inference": {"provider": provider, "model": selected_model},
                "creative": {"provider": provider, "model": selected_model},
                "code": {"provider": provider, "model": selected_model},
            }
            elyan_config.set("models.roles", role_map)
        else:
            # Router kapalıysa role map yine default ile hizalı kalsın.
            elyan_config.set("models.roles", {})

        # 5. Channel Setup
        print("\n[3] İletişim Kanalı:")
        print("  1. Telegram (Mobil Erişim)")
        print("  2. WhatsApp (QR ile bağlan)")
        print("  3. Sadece Masaüstü (Web/CLI)")
        
        ch_choice = input("\nSeçiminiz (1-3) [1]: ").strip() or "1"
        
        if ch_choice == "1":
            token = input("🤖 Telegram Bot Token girin: ").strip()
            if token:
                # Prefer keychain + config reference. Fallback to plaintext if keychain unavailable.
                token_ref = "$TELEGRAM_BOT_TOKEN"
                token_value = token_ref
                if not keychain.set_key("telegram_bot_token", token):
                    token_value = token
                    print("⚠️ Keychain yazılamadı; token config dosyasına düz metin kaydedilecek.")

                channels = elyan_config.get("channels")
                if not isinstance(channels, list):
                    channels = []
                
                found = False
                for ch in channels:
                    if isinstance(ch, dict) and ch.get("type") == "telegram":
                        ch["token"] = token_value
                        ch["enabled"] = True
                        found = True
                
                if not found:
                    channels.append({"type": "telegram", "token": token_value, "enabled": True})
                
                elyan_config.set("channels", channels)
                print("✅ Telegram yapılandırıldı.")
        elif ch_choice == "2":
            try:
                from cli.commands.channels import login_whatsapp

                ok = login_whatsapp(channel_id="whatsapp")
                if ok:
                    print("✅ WhatsApp yapılandırıldı.")
                else:
                    print("⚠️ WhatsApp yapılandırması tamamlanamadı. Sonradan: `elyan channels login whatsapp`")
            except Exception as e:
                print(f"❌ WhatsApp onboarding başarısız: {e}")
                print("   Sonradan deneyin: `elyan channels login whatsapp`")

        # 6. Production Mode (Action-Lock)
        print("\n[4] Üretim Modu (Action-Lock):")
        print("  Bir web sitesi veya proje üretirken Elyan o işe odaklanır ve bölünmez.")
        print("  Güvenli üretim için Docker Sandbox kullanılacaktır.")
        
        time.sleep(1)

        # 7. Dashboard & Gateway
        print("\n🚀 Başlatma:")
        print("  Elyan arka planda çalışarak her an hazır bekleyebilir.")
        
        daemon_choice = input("\nElyan sistem açılışında otomatik başlasın mı? (y/n) [n]: ").strip().lower()
        if daemon_choice == "y":
            try:
                from cli.daemon import daemon_manager
                if daemon_manager.install():
                    print("✅ Otomatik başlatma (launchd) kuruldu.")
            except Exception as e:
                print(f"❌ Daemon kurulumu başarısız: {e}")

        # Save everything
        elyan_config.save()
        
        print("\n" + "="*50)
        print("🎉 KURULUM TAMAMLANDI!")
        print("="*50)
        print("\nElyan'ı uyandırmak için:")
        print("👉  elyan gateway start")
        print("\nDashboard için:")
        print("👉  elyan dashboard\n")

def start_onboarding():
    try:
        wizard = OnboardingWizard()
        wizard.run()
    except KeyboardInterrupt:
        print("\n\n👋 Onboarding iptal edildi.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Beklenmedik bir hata oluştu: {e}")
        sys.exit(1)
