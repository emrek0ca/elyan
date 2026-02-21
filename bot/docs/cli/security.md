# elyan security

Güvenlik denetimi ve olay yönetimi.

## Komutlar

### `security status`

Güvenlik sisteminin genel durumunu gösterir.

```bash
elyan security status
```

Çıktı örneği:
```
Güvenlik Sistemi:    ✅ Aktif
Denetim Logu:        ✅ Kayıt oluyor
Rate Limiter:        ✅ Aktif  (100 req/dk)
Onay Kuyruğu:        0 bekleyen
Sandbox:             ✅ Sınırlı mod
Son Olay:            yok (son 24s)
```

### `security audit`

Güvenlik denetimi çalıştırır.

```bash
elyan security audit
elyan security audit --fix           # Sorunları otomatik düzelt
elyan security audit --severity high # Yalnızca yüksek öncelikli
```

| Seçenek | Açıklama |
|---------|----------|
| `--fix` | Güvenli düzeltmeleri otomatik uygula |
| `--severity` | `low`, `medium`, `high`, `critical` |
| `--report` | Rapor dosyası oluştur |

Çıktı örneği:
```
[HIGH]   API anahtarı .env dosyasında açık — elyan config set ile keychain'e taşıyın
[MEDIUM] Rate limit çok yüksek (1000/dk) — 100/dk önerilir
[LOW]    Denetim logu rotasyonu kapalı
```

### `security events`

Son güvenlik olaylarını listeler.

```bash
elyan security events
elyan security events --last 1h      # Son 1 saat
elyan security events --last 7d      # Son 7 gün
```

Çıktı:
```
ZAMAN               SEVİYE   OLAY
2025-08-14 15:32   INFO     user123 → web_search (izin verildi)
2025-08-14 14:17   WARN     Bilinmeyen kullanıcı engellendi
2025-08-14 09:05   INFO     Rate limit: user456 yavaşlatıldı
```

### `security sandbox`

Sandbox modu bilgisini gösterir.

```bash
elyan security sandbox
```

## Güvenlik Seviyeleri

Elyan üç operatör modu destekler:

| Mod | Açıklama | Kullanım |
|-----|----------|----------|
| `strict` | Tüm araçlar onay gerektirir | Üretim |
| `balanced` | Riskli araçlar onay gerektirir | Varsayılan |
| `permissive` | Otomatik onay | Geliştirme |

```bash
elyan config set security.mode balanced
```

Daha fazla bilgi: [Güvenlik Mimarisi →](../security/architecture.md)

## Rate Limiting

```bash
# Mevcut limitleri görüntüle
elyan security status

# Limiti değiştir
elyan config set security.rate_limit.requests_per_minute 200

# Kullanıcı bazlı limit
elyan config set security.rate_limit.per_user 50
```

## Onay Kuyruğu

Yüksek riskli araçlar (dosya silme, e-posta gönderme gibi) çalışmadan önce onay bekler:

```bash
# Bekleyen onayları görüntüle
elyan security status

# Dashboard üzerinden onay
elyan dashboard
```

Onay gerektiren araçları yapılandır: [Tool Politikaları →](../security/tool-policy.md)
