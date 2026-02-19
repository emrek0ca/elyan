# WebSocket API

Elyan Gateway, gerçek zamanlı iletişim için iki WebSocket uç noktası sunar.

## Sohbet WebSocket — `/ws/chat`

İnteraktif sohbet için.

### Bağlantı

```javascript
const ws = new WebSocket("ws://localhost:8765/ws/chat");
```

### Mesaj Gönderme

```javascript
ws.send(JSON.stringify({
  type: "message",
  text: "Merhaba, bugün hava nasıl?",
  user_id: "web_user_1",
  channel_id: "session_abc123"
}));
```

**İstek alanları:**

| Alan | Tip | Zorunlu | Açıklama |
|------|-----|---------|----------|
| `type` | string | ✅ | `"message"` |
| `text` | string | ✅ | Kullanıcı mesajı |
| `user_id` | string | ✅ | Kullanıcı kimliği |
| `channel_id` | string | — | Oturum kimliği |

### Yanıt Alma

```javascript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch(data.type) {
    case "response":
      console.log("Yanıt:", data.text);
      break;
    case "tool_start":
      console.log("Araç çalışıyor:", data.tool);
      break;
    case "tool_done":
      console.log("Araç tamamlandı:", data.tool, data.result);
      break;
    case "error":
      console.error("Hata:", data.message);
      break;
  }
};
```

**Yanıt tipleri:**

| `type` | Açıklama |
|--------|----------|
| `response` | Elyan'ın metin yanıtı |
| `tool_start` | Araç çalıştırma başladı |
| `tool_done` | Araç tamamlandı |
| `typing` | Elyan yazıyor (3 nokta) |
| `error` | Hata oluştu |

### Tam Örnek (JavaScript)

```javascript
const ws = new WebSocket("ws://localhost:8765/ws/chat");
const userId = "web_" + Math.random().toString(36).substr(2, 9);

ws.onopen = () => {
  console.log("Bağlandı!");
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === "response") {
    document.getElementById("response").textContent = msg.text;
  }
};

function sendMessage(text) {
  ws.send(JSON.stringify({
    type: "message",
    text: text,
    user_id: userId
  }));
}
```

## Dashboard WebSocket — `/ws/dashboard`

Gerçek zamanlı sistem aktivitesi akışı.

### Bağlantı

```javascript
const ws = new WebSocket("ws://localhost:8765/ws/dashboard");
```

### Gelen Olaylar

```javascript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data);
};
```

**Örnek olay:**

```json
{
  "event": "request",
  "ts": "2025-08-14T15:32:41.123Z",
  "user": "user123",
  "channel": "telegram",
  "text": "web araştırması: yapay zeka",
  "tool": "web_search",
  "duration_ms": 843,
  "success": true
}
```

**Olay tipleri:**

| `event` | Açıklama |
|---------|----------|
| `request` | Kullanıcı isteği |
| `tool_call` | Araç çağrısı |
| `response` | Agent yanıtı |
| `error` | Sistem hatası |
| `channel_status` | Kanal durum değişikliği |
| `system` | Gateway başlatma/durma |

### Ping / Pong

Bağlantı canlı tutma:

```javascript
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }));
  }
}, 30000);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === "pong") return;  // Ping yanıtı
  // ...
};
```

## Python WebSocket İstemcisi

```python
import asyncio
import json
import websockets

async def chat():
    async with websockets.connect("ws://localhost:8765/ws/chat") as ws:
        # Mesaj gönder
        await ws.send(json.dumps({
            "type": "message",
            "text": "Merhaba!",
            "user_id": "python_client"
        }))

        # Yanıt al
        response = await ws.recv()
        data = json.loads(response)
        print(f"Elyan: {data['text']}")

asyncio.run(chat())
```

## Kimlik Doğrulama

Auth token yapılandırıldıysa URL'de gönderin:

```javascript
const ws = new WebSocket(
  "ws://localhost:8765/ws/chat?token=your_auth_token"
);
```

veya bağlantı sonrası ilk mesajda:

```json
{
  "type": "auth",
  "token": "your_auth_token"
}
```
