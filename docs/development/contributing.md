# Katkı Rehberi

Elyan açık kaynaklı bir projedir. Katkılarınızı memnuniyetle karşılarız!

## Başlarken

### 1. Fork ve Clone

```bash
# Fork'u klonlayın
git clone https://github.com/YOUR_USERNAME/elyan.git
cd elyan

# Upstream ekleyin
git remote add upstream https://github.com/your-org/elyan.git
```

### 2. Geliştirme Ortamı

```bash
# Python ortamı
python3.12 -m venv .venv
source .venv/bin/activate

# Bağımlılıklar
pip install -r requirements.txt
pip install ruff black isort mypy pytest pytest-asyncio pytest-cov

# Geliştirme kurulumu
pip install -e .
```

### 3. Dal Oluşturun

```bash
git checkout -b feature/my-awesome-feature
# veya
git checkout -b fix/bug-description
```

## Kod Standartları

### Format ve Lint

```bash
# Format
black .
isort .

# Lint
ruff check .

# CI aynı şeyleri yapar, push öncesinde çalıştırın
```

### Type Check

```bash
mypy core/ config/ security/ --ignore-missing-imports
```

Type hataları CI'ı engellemez (`continue-on-error: true`) ama raporlanır.

### Commit Mesajı Formatı

```
<tip>(<kapsam>): <kısa açıklama>

<isteğe bağlı uzun açıklama>

<isteğe bağlı: breaking change>
```

Tipler: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Örnekler:
```
feat(channels): add WhatsApp Business API adapter
fix(intent): volume commands misrouted to enhanced_patterns
docs(security): add tool-policy examples
```

## Testler

```bash
# Tüm testler
pytest tests/ -v

# Belirli test dosyası
pytest tests/unit/test_intent_parser.py -v

# Coverage raporu
pytest tests/ --cov=core --cov-report=term-missing

# Benchmark
python scripts/benchmark.py --suite intent --samples 10
```

Her yeni özellik için test yazılması beklenir. Minimum %80 coverage hedeflenir.

## Pull Request

### PR Öncesi Kontrol Listesi

- [ ] Testler yazıldı ve geçiyor
- [ ] `black`, `isort`, `ruff` temiz
- [ ] CLAUDE.md güncellendi (gerekiyorsa)
- [ ] Dokümantasyon güncellendi
- [ ] Breaking change varsa belirtildi

### PR Başlığı

```
feat(adapters): add Google Chat Bot mode with Pub/Sub support
```

### PR Açıklaması Şablonu

```markdown
## Değişiklikler
- ...

## Test
- [ ] Unit testler eklendi
- [ ] Manuel test yapıldı

## Notlar
...
```

## Kod İnceleme Süreci

1. PR açıldığında CI otomatik çalışır
2. En az 1 onay gereklidir
3. Tüm CI kontrolleri yeşil olmalıdır
4. `main` branch'e squash merge yapılır

## Sorun Bildirme

[GitHub Issues](https://github.com/your-org/elyan/issues) üzerinden:

- **Bug:** Başlık `[BUG]` ile başlamalı
- **Özellik İsteği:** Başlık `[FEATURE]` ile başlamalı
- **Soru:** GitHub Discussions

## Geliştirme Ortamı Değişkenleri

```bash
export ELYAN_ENV=development
export GROQ_API_KEY=YOUR_GROQ_API_KEY        # Test için
export PYTHONPATH=/path/to/elyan
```

`.env` dosyası:

```env
ELYAN_ENV=development
GROQ_API_KEY=YOUR_GROQ_API_KEY
GEMINI_API_KEY=YOUR_GOOGLE_API_KEY
```

## Mimari Kararlar

Büyük mimari değişiklikler için önce bir **Issue** açın ve tartışın. Teknik tasarım belgesi (`docs/development/`) beklenir.

Mevcut mimariye genel bakış: [Mimari →](./architecture.md)
