# Production Streaming Notes

Elyan chat streaming uses the existing authenticated `/v1/realtime/stream` SSE path. Delta events are volatile fanout events and are not written to `realtime_events`; final assistant state is committed through the canonical chat/task tables.

## Event Flow

- `message.created`: assistant placeholder is visible immediately.
- `message.delta`: raw assistant text only; never treat this as final blocks.
- `message.completed`: final `content`, `blocks`, and `usage`; replace streaming text with committed block state.
- `message.error`: keep the assistant bubble and show retryable error metadata.
- `heartbeat`: invisible keep-alive event.

## Nginx

Use streaming-safe proxy settings for `/v1/realtime/stream`:

```nginx
location /v1/realtime/stream {
  proxy_pass http://elyan_backend;
  proxy_http_version 1.1;
  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
  proxy_set_header Connection "";

  proxy_buffering off;
  proxy_cache off;
  gzip off;
  proxy_read_timeout 1h;
  proxy_send_timeout 1h;
  add_header X-Accel-Buffering no;
}
```

The backend also sends `Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`, `Connection: keep-alive`, and `X-Accel-Buffering: no`.

## Operational Checks

- Redis should be enabled in production for cross-instance fanout and request budgets.
- Watch `time_to_first_delta`, `total_response_time`, active stream count, stream errors, provider latency, DB write latency, disconnects, and timeouts.
- Do not log user content; trace by `taskId`, `sessionId`, `messageId`, provider, token counts, lengths, latency, and status.
