## OTURUM GÜNCELLEMESİ — 2026-02-21 (SMART APPROVALS) ✅
- **Akıllı Onay İndirgeme (Smart Approval):**
  - `core/learning_engine.py`: `check_approval_confidence` metodu eklendi. Geçmişte "Onayla" denilen ve parametreleri *birebir* uyuşan işlemler (son 30 gün içinde en az 1 kez) artık otomatik onaylanıyor.
  - `core/agent.py`: `_execute_tool` içinde `ask_human` öncesinde bu kontrol yapılıyor. Otomatik onaylanırsa kullanıcıya sorulmuyor, sadece loglanıyor ve dashboard'a bildirim gidiyor.

**Test/Doğrulama:**
- `tests/unit/test_smart_approval.py`: Otomatik onay ve fallback senaryoları doğrulandı.
- `elyan status`: Ortam sorunu çözüldü ve doğrulandı.
