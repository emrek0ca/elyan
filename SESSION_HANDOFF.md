# ELYAN - Oturum Notu (12 Şubat 2026)

Bu dosya kısa handoff içindir. Güncel tek kaynak: `ELYAN_MASTER.md`.

## Bu Oturumda Eklenenler
- Güç komutlarına zorunlu açık onay:
  - `shutdown_system`, `restart_system`, `sleep_system`, `lock_screen`
  - Onay gelmezse görev çalıştırılmıyor.
- Telegram için gerçek onay akışı:
  - Inline `Onayla` / `Reddet` butonları.
  - `/cancel` bekleyen onayı iptal ediyor.
- Desktop UI için onay diyaloğu:
  - Yüksek riskte `QMessageBox` ile onay soruluyor.
- Wizard standardizasyonu:
  - Yeni birleşik giriş: `ui/wizard_entry.py`
  - Öncelik: `apple_setup_wizard` -> `enhanced_setup_wizard` -> `setup_wizard`.
- Eksik giriş dosyası tamamlandı:
  - `main.py` eklendi (`python main.py`, `python main.py --cli`).

## Kısa Sonraki Adım
1. `venv/bin/python scripts/e2e_regression_check.py` ile dry-run zincirini doğrula.
2. Gerçek Telegram token ile canlı E2E doğrulama (onay butonu + güç komutu).
