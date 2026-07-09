# Elyan Desktop

Telefonundan bilgisayarını yöneten kişisel ajan. GUI yok: CLI ile kurulur,
arka planda sessizce yaşar, mobilden gelen görevleri bilgisayarında yürütür.
macOS'ta menü çubuğunda, Windows'ta sistem tepsisinde, Linux'ta göstergede
küçük bir ikon durur — aktif görevler oradan görünür.

## Kurulum

```bash
curl -fsSL https://elyan.dev/install.sh | bash   # veya: bash scripts/install.sh
```

## Hızlı başlangıç

```bash
elyan pair              # terminalde QR çıkar → Elyan iOS uygulamasıyla okut
elyan service install   # açılışta otomatik başlat (launchd/systemd/schtasks)
```

Hepsi bu. Telefondan gönderdiğin görevler ("sunum hazırla", "dosyayı bul",
"uygulamayı aç"...) bilgisayarında gerçekten yürütülür ve sonuç mobile
raporlanır.

## Komutlar

| Komut | İş |
|---|---|
| `elyan pair` | QR ile telefona bağla (kurulumun tamamı) |
| `elyan login` | E-posta/şifre ile giriş (QR'sız alternatif) |
| `elyan start` / `stop` / `restart` | Daemon'u yönet |
| `elyan status` | Bağlantı + eşleştirme + görev durumu |
| `elyan tasks` | Son görevler |
| `elyan doctor` | Kurulum sağlık kontrolü |
| `elyan service install` | Açılışta otomatik başlat |
| `elyan run` | Ön planda çalıştır (hata ayıklama) |

## Mimari

- **Motor**: Python runtime (`runtime/`) — üç işletim sisteminde aynı kod.
  Deterministik komutlar yerelde anında çalışır; serbest görevler VPS'teki
  **server_brain**'e yapılandırılmış JSON zarfıyla gider (`elyan.plan.v1`),
  dönen plan tek noktada doğrulanıp masaüstünde yürütülür. Düz metin bağlam
  taşınmaz; yerel LLM yoktur.
- **Görev akışı**: iOS → backend → WebSocket `task.dispatch` → masaüstü
  yürütür → adım adım durum + artefaktlar geri raporlanır (polling yedeği ile).
- **Daemon**: `runtime/daemon.py` — pidfile, çökme sonrası kendini toparlar,
  bayat cihaz kayıtlarını kendisi temizler (desktop_limit self-heal).
- **Tepsi ikonu**: `runtime/tray.py` (pystray) — durum + aktif görevler + çıkış.

## Geliştirme

```bash
./venv/bin/python -m pytest tests/ -q   # test süiti
./bin/elyan run                          # daemon'u ön planda izle
```

Ayrıntılı devir notları: `HANDOFF.md`.
