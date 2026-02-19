# elyan memory

Bellek ve vektör indeks yönetimi. Elyan, konuşmaları ve öğrendiklerini yerel bir vektör veritabanında saklar.

## Komutlar

### `memory status`

Bellek sisteminin genel durumunu gösterir.

```bash
elyan memory status
```

Çıktı örneği:
```
Bellek Sistemi:  ✅ Aktif
Toplam Girdi:    1,247
İndeks Boyutu:   24.3 MB
Son İndeks:      2025-08-14 15:32
Kullanıcılar:    3
```

### `memory index`

Mevcut konuşmaları/dosyaları yeniden indeksler.

```bash
elyan memory index
elyan memory index --user user123
```

| Seçenek | Açıklama |
|---------|----------|
| `--user` | Belirli kullanıcıyı indeksle |

### `memory search`

Bellek içinde anlam bazlı arama yapar.

```bash
elyan memory search "uçuş rezervasyonu"
elyan memory search "python hata" --user user123
```

### `memory export`

Belleği dosyaya aktarır.

```bash
elyan memory export                          # JSON çıktı (stdout)
elyan memory export --file backup.json
elyan memory export --format jsonl --file backup.jsonl
```

| Seçenek | Varsayılan | Açıklama |
|---------|-----------|----------|
| `--format` | `json` | `json` veya `jsonl` |
| `--file` | stdout | Çıktı dosyası |
| `--user` | tümü | Filtre kullanıcı |

### `memory import`

Dışa aktarılmış belleği geri yükler.

```bash
elyan memory import --file backup.json
```

### `memory clear`

Belleği temizler.

```bash
elyan memory clear                    # Tüm bellek
elyan memory clear --user user123     # Belirli kullanıcı
```

!!! warning "Geri alınamaz"
    `memory clear` işlemi geri alınamaz. Önce `memory export` ile yedekleyin.

### `memory stats`

Ayrıntılı istatistikleri gösterir.

```bash
elyan memory stats
elyan memory stats --size
```

Çıktı:
```
Toplam Konuşma: 847
Toplam Mesaj:   12,483
Vektör Sayısı:  12,483
Embed Modeli:   all-minilm-l6-v2
Bellek Kullanımı: 156 MB
```

## Bellek Mimarisi

```
~/.elyan/
├── memory.db          # SQLite konuşma geçmişi
├── vectors/           # Vektör indeks dosyaları
│   ├── index.faiss
│   └── metadata.json
└── embeddings.cache   # Embed önbelleği
```

## Vektör Arama

Elyan, `core/semantic_memory.py` ile anlam tabanlı arama yapar. Basit anahtar kelime eşleşmesi yerine cümle gömülümleri (sentence embeddings) kullanır.

Desteklenen embed modelleri:

| Model | Boyut | Hız |
|-------|-------|-----|
| `all-minilm-l6-v2` | 384 | ⚡ Hızlı |
| `all-mpnet-base-v2` | 768 | 🔍 Daha doğru |

```bash
# Embed modelini değiştir
elyan config set memory.embed_model all-mpnet-base-v2
# Yeniden indeksle
elyan memory index
```
