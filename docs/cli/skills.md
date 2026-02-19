# elyan skills

Beceri eklentileri (skills), Elyan'ın yeteneklerini genişletir. Araştırma, ofis belgeleri, tarayıcı otomasyonu gibi modüler işlevler skill olarak paketlenir.

## Komutlar

### `skills list`

Tüm becerileri listeler.

```bash
elyan skills list                  # Tüm beceriler
elyan skills list --enabled        # Yalnızca aktifler
elyan skills list --available      # Yüklenebilecekler
```

Çıktı örneği:
```
AD              DURUM      SÜRÜM   AÇIKLAMA
research        ✅ aktif    1.2.0   Web araştırma ve rapor
browser         ✅ aktif    1.0.0   Tarayıcı otomasyonu
document        ✅ aktif    1.1.0   Word/Excel/PDF oluştur
voice           ⚪ pasif    1.0.0   Ses tanıma
calendar        ⚪ pasif    0.9.0   Takvim entegrasyonu
```

### `skills info`

Beceri detaylarını gösterir.

```bash
elyan skills info research
```

Çıktı:
```
Ad:          research
Sürüm:       1.2.0
Durum:       aktif
Araçlar:     web_search, summarize, deep_research, report_generate
Bağımlılık:  beautifulsoup4, lxml
```

### `skills install`

Yeni beceri yükler.

```bash
elyan skills install voice
elyan skills install calendar
```

### `skills enable` / `disable`

Beceri etkinleştirme.

```bash
elyan skills enable voice
elyan skills disable calendar
```

### `skills update`

Beceri(leri) günceller.

```bash
elyan skills update research        # Tek beceri
elyan skills update --all           # Tümü
```

### `skills remove`

Beceri kaldırır.

```bash
elyan skills remove calendar
```

### `skills search`

Kullanılabilir becerilerde arama.

```bash
elyan skills search "takvim"
elyan skills search "excel"
```

## Dahili Beceriler

| Beceri | Araçlar | Açıklama |
|--------|---------|----------|
| `research` | `web_search`, `summarize`, `deep_research` | Web araştırması |
| `browser` | `screenshot`, `navigate`, `extract` | Tarayıcı otomasyonu |
| `document` | `create_word`, `create_excel`, `create_pdf` | Belge oluşturma |
| `system` | `set_volume`, `open_app`, `list_files` | Sistem kontrolü |
| `voice` | `transcribe`, `speak` | Ses işleme |

## Skill Yapısı

Bir skill, `core/skills/` altındaki bir Python modülüdür:

```python
# core/skills/my_skill.py
SKILL_META = {
    "name": "my_skill",
    "version": "1.0.0",
    "tools": ["my_tool"],
}

async def my_tool(params: dict) -> dict:
    ...
```

Kendi becerini yazmak için [Kanal Adaptörü Yazma →](../development/writing-adapters.md) bölümüne bakın.
