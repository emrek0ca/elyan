# Operator Modları

Elyan, üç farklı güvenlik operatör modu destekler. Mod, sistemi kimin kullandığına ve ne kadar güvenilir bir ortamda çalıştığına göre seçilmelidir.

## Modlar

### `strict` — Sıkı Mod

Her araç çalıştırılmadan önce insan onayı gerektirir.

**Kullanım:** Üretim ortamları, hassas verilerle çalışan sistemler.

```bash
elyan config set security.mode strict
```

Davranış:
- Tüm araç çağrıları onay kuyruğuna düşer
- Onay Dashboard veya CLI üzerinden verilir
- Yalnızca `read-only` araçlar (saat, hava durumu, arama) otomatik çalışır

### `balanced` — Dengeli Mod (Varsayılan)

Riskli araçlar onay gerektirir, güvenli araçlar otomatik çalışır.

**Kullanım:** Çoğu üretim ve geliştirme kurulumu.

```bash
elyan config set security.mode balanced
```

Otomatik çalışan araçlar:
- `web_search`, `summarize`
- `screenshot`, `list_files`
- `set_volume`, `open_app`

Onay gerektiren araçlar:
- `write_file`, `delete_file`
- `send_email`, `send_message`
- `run_command`, `execute_script`

### `permissive` — İzin Verici Mod

Tüm araçlar otomatik çalışır, onay istenmez.

**Kullanım:** Yerel geliştirme, test ortamı, güvenilir otomasyon.

```bash
elyan config set security.mode permissive
```

!!! warning "Üretimde Kullanmayın"
    `permissive` mod üretim ortamında tehlikelidir. Yalnızca kontrollü geliştirme ortamlarında kullanın.

## Mod Yapılandırması

```json5
{
  "security": {
    "mode": "balanced",
    "auto_approve_tools": ["web_search", "screenshot", "list_files"],
    "always_deny_tools": ["rm_rf", "format_disk"],
    "approval_timeout_seconds": 300
  }
}
```

## Kullanıcı Bazlı Modlar

Farklı kullanıcılara farklı modlar atanabilir:

```json5
{
  "security": {
    "mode": "balanced",
    "user_overrides": {
      "admin_user_id": {"mode": "permissive"},
      "readonly_user_id": {"mode": "strict", "allowed_tools": ["web_search"]}
    }
  }
}
```

## Mod Geçmişi

Operatör modu değişiklikleri denetim loguna kaydedilir:

```
2025-08-14 15:32  AUDIT  mode_change: balanced → strict  by: admin
```

## Onay Süreci

`strict` veya `balanced` modda bir araç onay bekliyorsa:

```
[ONAY BEKLENİYOR]
Kullanıcı:  user123
Araç:       send_email
Parametreler: to="boss@example.com", subject="Rapor"
Zaman:      2025-08-14 15:32:41
Timeout:    300 saniye

[O] Onayla  [R] Reddet
```

Timeout dolduğunda işlem otomatik olarak reddedilir.
