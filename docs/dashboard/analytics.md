# Dashboard Analitik

`GET /api/analytics` uç noktası ve Dashboard Analitik sekmesi, Elyan kullanım istatistiklerini sunar.

## API Endpoint

```
GET /api/analytics
```

Yanıt örneği:

```json
{
  "total_requests": 1247,
  "success_rate": 0.97,
  "avg_response_time_ms": 843,
  "model": "groq/llama-3.3-70b-versatile",
  "total_cost_usd": 0.00,
  "requests_last_24h": 234,
  "requests_last_7d": 1102,
  "top_tools": [
    {"name": "web_search", "count": 312},
    {"name": "screenshot", "count": 87},
    {"name": "create_word", "count": 43}
  ],
  "channels": {
    "telegram": 789,
    "discord": 312,
    "webchat": 146
  },
  "hourly_distribution": [12, 8, 3, 1, 0, 0, 5, 24, 45, ...]
}
```

## Dashboard Grafikleri

### İstek Dağılımı (Saatlik)

Son 24 saatteki istek sayısı çubuk grafik olarak gösterilir. Yoğun saatler kolayca görülebilir.

### Araç Kullanımı

En çok kullanılan 10 araç listesi.

### Kanal Dağılımı

Hangi kanaldan kaç istek geldiği pasta grafik.

### Başarı Oranı

Başarılı / başarısız istek oranı zaman serisi.

## Metriklerin Toplanması

Metrikler `core/advanced_analytics.py` modülü tarafından toplanır ve bellek içi bir depoda tutulur.

```python
# core/advanced_analytics.py
class AnalyticsCollector:
    def record_request(self, channel, tool, duration_ms, success): ...
    def get_stats(self, period="24h") -> dict: ...
```

Uzun vadeli depolama için:

```bash
elyan config set analytics.persist true
elyan config set analytics.db_path ~/.elyan/analytics.db
```

## Maliyet Takibi

Elyan, ücretsiz sağlayıcılar (Groq, Gemini) kullanıldığında maliyet sıfırdır. Ücretli API kullanıyorsanız:

```bash
# Son 30 günün maliyeti
elyan models cost --period 30d
```

## Dışa Aktarma

```bash
# CSV olarak dışa aktar (planlanan)
curl http://localhost:8765/api/analytics?format=csv > analytics.csv
```
