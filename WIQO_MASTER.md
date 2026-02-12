# WIQO MASTER STATUS

Son güncelleme: 12 Şubat 2026

## Ürün Tanımı
- Wiqo: macOS odaklı, çok araçlı, Türkçe öncelikli dijital asistan.
- Çalışma modeli: Anla -> Planla -> Uygula.

## Çalıştırma
- UI modu: `python main.py`
- Telegram CLI modu: `python main.py --cli`

## Mimari Çekirdek
- Agent: `core/agent.py`
- Task orchestration: `core/task_engine.py`
- Intent çözümleme: `core/intent_parser.py`
- Tool registry: `tools/__init__.py`
- Telegram giriş noktası: `handlers/telegram_handler.py`
- Desktop giriş noktası: `ui/clean_main_app.py`

## Güvenlik ve Onay Akışı
- Aşağıdaki aksiyonlarda açık kullanıcı onayı zorunlu:
  - `shutdown_system`
  - `restart_system`
  - `sleep_system`
  - `lock_screen`
- Telegram:
  - Inline `Onayla/Reddet` butonları ile karar.
  - `/cancel` bekleyen onayı reddeder.
- Desktop UI:
  - `QMessageBox` ile anlık onay penceresi.

## Setup Wizard Standardı
- Kanonik giriş: `ui/wizard_entry.py`
- Fallback zinciri:
  1. `ui/apple_setup_wizard.py`
  2. `ui/enhanced_setup_wizard.py`
  3. `ui/setup_wizard.py`

## Yakın Dönem Odak
1. Telegram canlı E2E regresyon testi (intent -> tool -> sonuç + onay).
2. Otomatik dry-run zinciri: `venv/bin/python scripts/e2e_regression_check.py`.
3. Pytest bağımlılığını ortama ekleyip otomatik testleri CI benzeri akışa almak.
4. Wizard varyantlarını tek kanonik sınıfa indirip legacy dosyaları sadeleştirmek.
