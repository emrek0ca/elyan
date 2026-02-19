# Dashboard Genel Bakış

Elyan Web Dashboard, sistemi görsel bir arayüzle izlemenizi ve yönetmenizi sağlar.

## Başlatma

```bash
# Dashboard'u aç (gateway otomatik başlatılır)
elyan dashboard

# Farklı port
elyan dashboard --port 9000

# Tarayıcı açma
elyan dashboard --no-browser
```

Varsayılan URL: `http://localhost:8765`

## Sekmeler

### Genel Bakış

Ana durum gösterge paneli:

| Kart | İçerik |
|------|--------|
| **Durum** | Gateway çalışıyor/durdurulmuş |
| **Model** | Aktif AI sağlayıcı |
| **Kanallar** | Aktif kanal sayısı |
| **Yanıt Süresi** | Son 5 istek ortalaması |
| **CPU** | Anlık CPU kullanımı |
| **RAM** | Anlık RAM kullanımı |

CPU ve RAM 5 saniyede bir güncellenir.

### Kanallar

- Tüm kanalların listesi ve bağlantı durumları
- Kanal başına son mesaj sayısı
- Hata durumu vurgulama

### Görevler

- Aktif görevler (çalışan)
- Geçmiş görevler (tamamlanan/hatalı)
- Hızlı görev oluşturma formu

### Güvenlik

- Son güvenlik olayları
- Rate limit durumu
- Bekleyen onaylar

### Ayarlar

- Yapılandırma formu (model seçimi, port, güvenlik modu)
- Değişiklikler anında `~/.elyan/config.json5`'e kaydedilir

## Canlı Aktivite Akışı

Dashboard sol panelinde, gateway'den gelen gerçek zamanlı olaylar WebSocket üzerinden gösterilir:

```
15:32:41  user123 → "Hava durumu nedir?"
15:32:42  groq    → yanıt 847ms
15:32:55  user456 → "Rapor hazırla"
15:32:56  task    → delivery_engine başlatıldı
```

## REST API

Dashboard aynı zamanda bir REST API sunar. Tüm uç noktalar: [API Referansı →](../api/gateway.md)

## Uzaktan Erişim

Uzaktan erişim için HTTPS tüneli veya ters proxy önerilir:

```bash
# ngrok ile hızlı tünel (geliştirme)
ngrok http 8765

# nginx ters proxy (üretim)
# Bkz: deployment/docker.md
```

!!! warning "Güvenlik Uyarısı"
    Dashboard'u internete açarken `auth_token` yapılandırın:
    ```bash
    elyan config set gateway.auth_token your_secret_token
    ```
