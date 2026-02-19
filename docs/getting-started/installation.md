# Kurulum

## Gereksinimler

| Gereksinim | Minimum | Önerilen |
|------------|---------|----------|
| Python | 3.11 | 3.12 |
| RAM | 1 GB | 4 GB |
| Disk | 500 MB | 2 GB |
| İşletim Sistemi | macOS 12+ / Ubuntu 20.04+ | - |

## Otomatik Kurulum (Önerilen)

```bash
git clone https://github.com/your-org/elyan.git
cd elyan
bash install.sh
```

Kurulum betiği:

1. Python 3.11+ varlığını kontrol eder
2. `.venv` sanal ortamı oluşturur
3. Tüm bağımlılıkları yükler
4. `elyan` CLI komutunu kayıt eder
5. `~/.elyan/` dizin yapısını oluşturur
6. Shell completion kurar

### Bayraklar

```bash
bash install.sh --headless    # UI gerektirmeyen sunucu kurulumu
bash install.sh --no-ui       # PyQt6 yükleme
```

## Manuel Kurulum

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
mkdir -p ~/.elyan/{memory,projects,logs,skills,sandbox,browser}
```

## Bağımlılıkları Doğrula

```bash
elyan doctor
```

Beklenen çıktı:
```
✓ Python 3.12.x
✓ Tüm paketler kurulu
✓ Port 18789 müsait
✓ ~/.elyan/ dizini mevcut
```
