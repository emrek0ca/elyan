# Dashboard Güvenlik Sekmesi

Dashboard Güvenlik sekmesi, güvenlik olaylarını ve sistem durumunu gerçek zamanlı olarak izler.

## Güvenlik Durumu Kartları

| Kart | Açıklama |
|------|----------|
| **Güvenlik Modu** | `strict` / `balanced` / `permissive` |
| **Rate Limit** | İstekler/dakika, güncel doluluk |
| **Onay Kuyruğu** | Bekleyen onay sayısı |
| **Son Olay** | En son güvenlik olayı zaman damgası |

## Olay Akışı

Son güvenlik olayları tabloda gösterilir:

| Sütun | Açıklama |
|-------|----------|
| Zaman | Olayın zamanı |
| Seviye | `INFO`, `WARN`, `ERROR`, `CRITICAL` |
| Kullanıcı | Eylemi gerçekleştiren kullanıcı |
| Araç | Kullanılan araç veya eylem |
| Sonuç | `izin_verildi`, `reddedildi`, `onay_bekleniyor` |

Filtreler: Seviye, kullanıcı, tarih aralığı.

## Onay Yönetimi

Yüksek riskli araçlar (dosya silme, e-posta gönderme) çalışmadan önce onay bekler.

Dashboard'dan onay vermek için:

1. **Güvenlik** sekmesi → **Bekleyen Onaylar**
2. İsteği inceleyin (araç, parametreler, kullanıcı)
3. **Onayla** veya **Reddet**

CLI ile de yönetilebilir:

```bash
elyan security status         # Bekleyenleri göster
```

## Rate Limit İzleme

```
Toplam:      100 istek/dk izni
Kullanılan:  47 istek/dk
Kalan:       53 istek/dk
```

Süper kullanıcı limiti ayrı takip edilir.

## Denetim Logu (Audit Log)

Tüm işlemler `security/audit.py` modülü tarafından kaydedilir:

```
~/.elyan/audit.log
```

Günlük rotasyon ve maksimum 30 günlük geçmiş.

```bash
# CLI ile son olayları görüntüle
elyan security events --last 24h
elyan security events --last 7d --severity high
```

Daha fazla bilgi: [Denetim Logu →](../security/audit.md)

## Güvenlik Modu Değiştirme

Dashboard → **Ayarlar** sekmesinden veya CLI ile:

```bash
elyan config set security.mode strict
elyan gateway reload
```

| Mod | Açıklama |
|-----|----------|
| `strict` | Her araç onay gerektirir |
| `balanced` | Yalnızca riskli araçlar |
| `permissive` | Otomatik onay (geliştirme) |

Daha fazla bilgi: [Operator Modları →](../security/operator-modes.md)
