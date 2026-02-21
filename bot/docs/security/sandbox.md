# Sandbox

Sandbox, araçların izole bir ortamda çalışmasını sağlar. Kötü niyetli veya hatalı araç çağrılarının sisteme zarar vermesini önler.

## Sandbox Nedir?

Elyan sandbox'u:
- Araç çalıştırma süreçlerini kısıtlar
- Dosya sistemi erişimini sınırlar
- Ağ erişimini kontrol eder
- Kaynak kullanımını (CPU, RAM) sınırlar

## Sandbox Modları

### `none` — Sandbox Kapalı

```json5
{ "sandbox": { "mode": "none" } }
```

Araçlar doğrudan çalışır. Yalnızca güvenilir ortamlarda kullanın.

### `restricted` — Kısıtlı (Varsayılan)

```json5
{ "sandbox": { "mode": "restricted" } }
```

- Dosya yazma: yalnızca `~/.elyan/workspace/`
- Ağ: yalnızca izin verilen domainler
- Süreç: alt süreç sayısı sınırlı

### `container` — Konteyner (Üretim)

```json5
{
  "sandbox": {
    "mode": "container",
    "container_image": "python:3.12-slim",
    "workspace_volume": "/tmp/elyan-workspace"
  }
}
```

Docker konteynerinde çalışır. En yüksek izolasyon.

## Çalışma Dizini

Sandbox araçları için çalışma dizini:

```
~/.elyan/workspace/
├── downloads/     # İndirilen dosyalar
├── generated/     # Oluşturulan belgeler
├── screenshots/   # Ekran görüntüleri
└── temp/          # Geçici dosyalar
```

Araçlar bu dizinin dışına yazamaz (`restricted` modda).

## Ağ Erişim Listesi

```json5
{
  "sandbox": {
    "allowed_domains": [
      "api.groq.com",
      "generativelanguage.googleapis.com",
      "duckduckgo.com",
      "wikipedia.org"
    ],
    "block_private_networks": true   // 192.168.x.x, 10.x.x.x vb. engelle
  }
}
```

## Kaynak Limitleri

```json5
{
  "sandbox": {
    "max_cpu_percent": 50,
    "max_memory_mb": 512,
    "max_execution_seconds": 30,
    "max_file_size_mb": 50
  }
}
```

## CLI ile Sandbox Durumu

```bash
elyan security sandbox

# Çıktı:
# Sandbox Modu: restricted
# Çalışma Dizini: /Users/user/.elyan/workspace (2.3 GB kullanılıyor)
# İzin Verilen Domainler: 8
# CPU Limiti: 50%
# RAM Limiti: 512 MB
```

## macOS Sandbox (Seatbelt)

macOS'ta `restricted` mod otomatik olarak `sandbox-exec` kullanır:

```xml
<!-- ~/.elyan/sandbox.sb -->
(version 1)
(allow default)
(deny file-write* (subpath "/"))
(allow file-write* (subpath (string-append (param "HOME") "/.elyan/workspace")))
(deny network-outbound (remote ip "192.168.*"))
```
