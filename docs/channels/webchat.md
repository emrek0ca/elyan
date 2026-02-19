# Web Sohbet Entegrasyonu

Elyan, yerleşik bir web sohbet arayüzü sunar. Herhangi bir web sitesine entegre edilebilir.

## Genel Bakış

Web Sohbet kanalı iki bileşenden oluşur:

1. **Gateway WebSocket sunucusu** — `core/gateway/server.py`
2. **Dashboard HTML** — `ui/web/dashboard.html`

## Hızlı Başlangıç

```bash
# Gateway'i başlat (web sohbet dahil)
elyan gateway start

# Dashboard'u aç
elyan dashboard
# Tarayıcı otomatik açılır: http://localhost:8765
```

## Yapılandırma

`~/.elyan/config.json5`:

```json5
{
  "channels": [
    {
      "type": "webchat",
      "port": 8765,
      "host": "0.0.0.0",
      "cors_origins": ["http://localhost:3000", "https://yoursite.com"],
      "enabled": true
    }
  ]
}
```

## Web Sitesine Gömme

### Widget (Basit)

```html
<!-- HTML sayfanıza ekleyin -->
<script>
  window.ElyanConfig = {
    gatewayUrl: "http://localhost:8765",
    widgetTitle: "Elyan Asistan",
    primaryColor: "#4F46E5"
  };
</script>
<script src="http://localhost:8765/static/widget.js"></script>
```

### iframe

```html
<iframe
  src="http://localhost:8765/chat"
  width="400"
  height="600"
  frameborder="0">
</iframe>
```

### WebSocket API

Doğrudan WebSocket bağlantısı:

```javascript
const ws = new WebSocket("ws://localhost:8765/ws/chat");

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "message",
    text: "Merhaba!",
    user_id: "web_user_1"
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Yanıt:", data.text);
};
```

## Dashboard Özellikleri

`elyan dashboard` komutu açılan web arayüzünde:

| Sekme | İçerik |
|-------|--------|
| Genel Bakış | Canlı durum kartları |
| Kanallar | Kanal listesi ve durumları |
| Görevler | Aktif ve geçmiş görevler |
| Güvenlik | Güvenlik olayları |
| Ayarlar | Yapılandırma formu |

## REST API

Gateway'in REST uç noktaları:

```
GET  /api/analytics     Analitik verisi
GET  /api/tasks         Görev listesi
POST /api/tasks         Yeni görev oluştur
GET  /api/memory/stats  Bellek istatistikleri
GET  /api/activity      Aktivite logu
WS   /ws/dashboard      Canlı WebSocket akışı
WS   /ws/chat           Sohbet WebSocket
```

Tüm API dokümantasyonu: [Gateway API →](../api/gateway.md)

## Güvenlik

```json5
{
  "type": "webchat",
  "auth_token": "your_secret_token",  // Tüm isteklerde gerekli
  "allowed_origins": ["https://yoursite.com"],
  "rate_limit": 60
}
```

HTTPS için bir ters proxy kullanın (nginx, Caddy):

```nginx
location /elyan/ {
  proxy_pass http://localhost:8765/;
  proxy_http_version 1.1;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
}
```
