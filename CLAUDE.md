## OTURUM GÜNCELLEMESİ — 2026-02-21 (AUDIO FEEDBACK) ✅
- **Sesli Geri Bildirim (Audio Feedback):**
  - `core/voice/audio_feedback.py`: macOS sistem seslerini (`afplay`) kullanan basit ses motoru.
  - `core/agent.py`: İşlem başarıyla tamamlandığında (özellikle yazma/değiştirme işlemleri) "Glass", hata durumunda "Basso" sesi çalınıyor. Okuma işlemleri sessiz.
  - `config/elyan_config.py`: `voice.feedback_enabled` ayarı eklendi.

**Test/Doğrulama:**
- `tests/unit/test_audio_feedback.py`: Ses çalma mantığı mocklanarak test edildi.
