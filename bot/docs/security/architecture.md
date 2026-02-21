# Güvenlik Mimarisi

Elyan, savunmacı güvenlik (defense-in-depth) prensibiyle tasarlanmıştır. Her katman bağımsız olarak güvenlik sağlar.

## Katmanlar

```
┌─────────────────────────────────────────────────┐
│                  Kullanıcı İsteği               │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│           1. Rate Limiter                        │
│     (security/rate_limiter.py)                   │
│     • Kullanıcı başına istek limiti              │
│     • Burst koruma                               │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│           2. Input Validator                     │
│     (security/validator.py)                      │
│     • Girdi sanitizasyonu                        │
│     • Maksimum uzunluk                           │
│     • İnjeksiyon engelleme                       │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│           3. Privacy Guard                       │
│     (security/privacy_guard.py)                  │
│     • PII tespiti (telefon, e-posta, TCKN...)    │
│     • Hassas veri maskeleme                      │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│           4. Tool Policy                         │
│     (security/tool_policy.py)                    │
│     • İzin verilen/yasak araçlar                 │
│     • Deny-before-allow prensibi                 │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│           5. Approval Gate                       │
│     (security/approval.py)                       │
│     • Yüksek riskli araçlar için onay            │
│     • asyncio.Lock ile eş zamanlılık             │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│           6. Sandbox                             │
│     (core/sandbox/)                              │
│     • Araç çalıştırma izolasyonu                 │
│     • Kaynak limitleri                           │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│           7. Audit Logger                        │
│     (security/audit.py)                          │
│     • Tüm işlemleri kayıt altına alır            │
│     • Thread-safe singleton                      │
└─────────────────────────────────────────────────┘
```

## Modüller

### `security/rate_limiter.py`
- `asyncio.Lock` ile thread-safe
- Kullanıcı, kanal ve global limitler
- Token bucket algoritması
- Burst desteği

### `security/validator.py`
- Girdi uzunluk sınırı (varsayılan: 4096 karakter)
- HTML/script injeksiyon temizliği
- Path traversal engeli (`../` filtreleme)

### `security/privacy_guard.py`
- Türkiye'ye özgü PII: TCKN, IBAN, telefon numarası
- Evrensel: e-posta, kredi kartı, API anahtarı pattern'leri
- Regex ve basit ML tabanlı tespit

### `security/tool_policy.py`
- JSON5 tabanlı kural tanımı
- Deny-before-allow: bir araç hem izin hem yasak listesindeyse YASAK önceliklenir
- Kullanıcı/rol bazlı kurallar

### `security/approval.py`
- Yüksek riskli araçlar için eş zamanlı onay kuyruğu
- `asyncio.Lock` ile yarış koşulu önleme
- `finally` bloğu ile onay öğesi her zaman temizlenir
- Stale entry temizleme (timeout sonrası)

### `security/audit.py`
- Thread-local context + double-checked singleton
- Dosya tabanlı günlük (`~/.elyan/audit.log`)
- Yapılandırılabilir rotasyon

## Anahtar Yönetimi

API anahtarları ve hassas veriler:

1. **macOS Keychain** (birincil)
2. **Linux Secret Service / GNOME Keyring** (Linux)
3. `.env` dosyası (yedek, önerilmez)

```bash
# Keychain'e anahtar ekle
elyan models add --provider groq --key gsk_xxx

# Doğrulama
elyan config show --masked  # Değerler maskelenir
```

## Güvenlik Testleri

```bash
# SAST tarama
bandit -r . -x .venv,tests

# Bağımlılık CVE tarama
pip-audit -r requirements.txt

# CI pipeline otomatik çalıştırır
elyan doctor --deep
```
