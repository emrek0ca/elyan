# Tool Politikaları

Tool politikaları, hangi araçların kim tarafından kullanılabileceğini tanımlar.

## Politika Dosyası

`~/.elyan/tool_policy.json5` veya yapılandırmada inline:

```json5
{
  "tool_policy": {
    "default_action": "allow",   // "allow" veya "deny"
    "rules": [
      {
        "tool": "delete_file",
        "action": "deny",
        "reason": "Dosya silme yasaklı"
      },
      {
        "tool": "send_email",
        "action": "require_approval",
        "condition": { "user_id": "untrusted_user" }
      },
      {
        "tool": "web_search",
        "action": "allow"
      }
    ]
  }
}
```

## Kural Aksiyonları

| Aksiyon | Açıklama |
|---------|----------|
| `allow` | Araç otomatik çalışır |
| `deny` | Araç engellenir |
| `require_approval` | İnsan onayı bekler |
| `log_only` | Çalışır ama kayıt alınır |

## Deny-Before-Allow Prensibi

Bir araç hem `deny` hem `allow` kuralına giriyorsa, **deny her zaman önceliklidir**:

```json5
{
  "rules": [
    { "tool": "run_command", "action": "allow", "condition": { "user_id": "admin" } },
    { "tool": "run_command", "action": "deny",  "condition": { "contains": "rm -rf" } }
  ]
}
// "rm -rf" içeren komutlar admin bile olsa engellenir
```

## Koşullar

```json5
{
  "rules": [
    {
      "tool": "write_file",
      "action": "allow",
      "condition": {
        "user_id": "trusted_user",
        "path_prefix": "~/.elyan/workspace/",
        "file_extension": [".txt", ".md", ".json"]
      }
    }
  ]
}
```

Desteklenen koşullar:

| Koşul | Açıklama |
|-------|----------|
| `user_id` | Kullanıcı ID |
| `channel` | Kanal tipi (`telegram`, `discord`...) |
| `path_prefix` | Dosya yolu başlangıcı |
| `file_extension` | İzin verilen uzantılar |
| `contains` | Parametrede geçen ifade |
| `time_range` | Saat aralığı (`"09:00-18:00"`) |

## Araç Risk Seviyeleri

Elyan, araçları otomatik olarak risk seviyesine göre sınıflandırır:

| Seviye | Araçlar |
|--------|---------|
| **Düşük** | `web_search`, `screenshot`, `list_files`, `get_time` |
| **Orta** | `write_file`, `create_word`, `open_app`, `set_volume` |
| **Yüksek** | `send_email`, `delete_file`, `run_command` |
| **Kritik** | `format_disk`, `sudo_command` (varsayılan: yasak) |

## CLI ile Politika Yönetimi

```bash
# Mevcut politikaları görüntüle
elyan security status

# Araç politikasını sorgula (planlanan)
elyan security policy web_search
```

## Güncellemeler Sonrası Yeniden Yükleme

Politika dosyasını değiştirdikten sonra:

```bash
elyan gateway reload
```

Yeniden başlatma gerekmez.
