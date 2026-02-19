# Denetim Logu

Elyan, tüm araç çağrılarını, güvenlik kararlarını ve sistem olaylarını denetim loguna kaydeder.

## Log Dosyası

```
~/.elyan/audit.log
```

## Log Formatı

Her satır bir JSON nesnesidir:

```json
{
  "ts": "2025-08-14T15:32:41.123Z",
  "level": "INFO",
  "event": "tool_call",
  "user_id": "user123",
  "channel": "telegram",
  "tool": "web_search",
  "params": {"query": "python 3.12 özellikler"},
  "result": "allowed",
  "duration_ms": 843,
  "session_id": "sess_abc123"
}
```

## Olay Tipleri

| Olay | Açıklama |
|------|----------|
| `tool_call` | Araç çağrısı ve sonucu |
| `tool_denied` | Politika tarafından engellendi |
| `approval_request` | Onay kuyruğuna eklendi |
| `approval_granted` | Onay verildi |
| `approval_denied` | Onay reddedildi |
| `approval_timeout` | Onay zaman aşımı |
| `rate_limit_hit` | Rate limit aşıldı |
| `auth_failure` | Kimlik doğrulama başarısız |
| `mode_change` | Güvenlik modu değiştirildi |
| `config_change` | Yapılandırma değiştirildi |
| `gateway_start` | Gateway başlatıldı |
| `gateway_stop` | Gateway durduruldu |

## Log Rotasyonu

```json5
{
  "audit": {
    "max_file_size_mb": 100,
    "max_files": 30,         // 30 rotasyon dosyası = ~30 gün
    "compress": true          // gzip ile sıkıştır
  }
}
```

## CLI ile Log İnceleme

```bash
# Son 24 saat
elyan security events --last 24h

# Son 7 gün, yüksek seviye
elyan security events --last 7d --severity high

# Belirli kullanıcı
elyan security events --last 24h | grep user123

# Ham log
tail -f ~/.elyan/audit.log | python3 -m json.tool
```

## PII Maskeleme

Kişisel veriler loga yazılmadan önce maskelenir:

```json
{
  "params": {
    "to": "us**@ex*****.com",
    "text": "Merhaba, numaram: ***-***-****"
  }
}
```

Maskeleme `security/privacy_guard.py` tarafından yapılır.

## Log Analizi

```bash
# En çok kullanılan araçlar
cat ~/.elyan/audit.log | python3 -c "
import json, sys
from collections import Counter
tools = Counter()
for line in sys.stdin:
    try:
        e = json.loads(line)
        if e.get('event') == 'tool_call':
            tools[e['tool']] += 1
    except: pass
for tool, count in tools.most_common(10):
    print(f'{count:5d}  {tool}')
"

# Reddedilen istekler
grep '"result": "denied"' ~/.elyan/audit.log | wc -l
```

## SIEM Entegrasyonu

Log JSON formatında olduğundan Splunk, Elasticsearch veya diğer SIEM araçlarıyla doğrudan entegre edilebilir:

```bash
# Filebeat yapılandırması
filebeat.inputs:
- type: log
  paths: [~/.elyan/audit.log]
  json.keys_under_root: true
```
