# Docker ile Dağıtım

## Hızlı Başlangıç

```bash
docker run -d \
  --name elyan \
  --restart unless-stopped \
  -p 18789:18789 \
  -e TELEGRAM_BOT_TOKEN="your_token" \
  -e GROQ_API_KEY="your_key" \
  -v ~/.elyan:/home/elyan/.elyan \
  ghcr.io/your-org/elyan:latest
```

## Docker Compose

`docker-compose.yml`:

```yaml
version: "3.9"

services:
  elyan:
    image: ghcr.io/your-org/elyan:latest
    restart: unless-stopped
    ports:
      - "127.0.0.1:18789:18789"
    environment:
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      GROQ_API_KEY: ${GROQ_API_KEY}
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      LOG_LEVEL: info
    volumes:
      - elyan_data:/home/elyan/.elyan
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:18789/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

volumes:
  elyan_data:
```

`.env` dosyası:
```
TELEGRAM_BOT_TOKEN=1234567890:AAF...
GROQ_API_KEY=gsk_...
```

Başlat:
```bash
docker compose up -d
docker compose logs -f elyan
```

## Yerel Build

```bash
docker build -t elyan:local .
docker run -d elyan:local
```

## Sağlık Kontrolü

```bash
curl http://localhost:18789/health
# {"status": "ok", "version": "18.0.0"}
```

## Güncelleme

```bash
docker compose pull elyan
docker compose up -d
```

## Log İzleme

```bash
docker logs -f elyan
docker exec -it elyan tail -f /home/elyan/.elyan/logs/bot.log
```
