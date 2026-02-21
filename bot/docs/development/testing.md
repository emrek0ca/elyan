# Test Rehberi

Elyan, pytest tabanlı kapsamlı bir test süiteye sahiptir.

## Dizin Yapısı

```
tests/
├── unit/
│   ├── test_intent_parser.py         # Intent parsing unit testleri
│   ├── test_fuzzy_intent.py          # Fuzzy matching testleri
│   ├── test_gateway_adapters.py      # Kanal adapter testleri
│   ├── test_gateway_router.py        # Gateway routing testleri
│   ├── test_response_cache.py        # Cache testleri
│   └── ...
├── integration/
│   ├── test_intent_to_tool_pipeline.py  # 25 senaryo uçtan uca
│   └── ...
└── conftest.py                       # Paylaşılan fixture'lar
```

## Çalıştırma

```bash
# Tüm testler
pytest tests/ -v

# Yalnızca unit testler
pytest tests/unit/ -v

# Belirli dosya
pytest tests/unit/test_intent_parser.py -v

# Belirli test
pytest tests/unit/test_intent_parser.py::TestVolumeCommands::test_mute -v

# Integration testler (CI'da PR için)
pytest tests/integration/ -v
```

## Coverage

```bash
pytest tests/ \
  --cov=core --cov=config --cov=security --cov=tools \
  --cov-report=term-missing \
  --cov-report=html:htmlcov
```

HTML raporu: `htmlcov/index.html`

## Test Yazma

### Unit Test Şablonu

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestMyFeature:
    """MyFeature için unit testler."""

    def test_basic_case(self):
        """Temel durum testi."""
        from core.my_module import my_function
        result = my_function("input")
        assert result == "expected_output"

    def test_edge_case(self):
        """Sınır durumu."""
        from core.my_module import my_function
        result = my_function("")
        assert result is None
```

### Async Test

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    from core.my_module import async_function
    result = await async_function("input")
    assert result == "expected"
```

### Mock Kullanımı

```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_with_mock():
    with patch("aiohttp.ClientSession") as mock_session:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"key": "value"}
        mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

        from core.my_adapter import MyAdapter
        adapter = MyAdapter({"url": "http://test"})
        result = await adapter.fetch()
        assert result == {"key": "value"}
```

## Benchmark

```bash
# Tüm benchmark suitleri
python scripts/benchmark.py

# Belirli suite
python scripts/benchmark.py --suite intent --samples 50

# JSON çıktı
python scripts/benchmark.py --json --output results.json

# Baseline ile karşılaştır
python scripts/benchmark.py --compare baseline.json
```

Mevcut suitler: `intent`, `fuzzy`, `cache`, `settings`, `quick_intent`, `fast_response`, `memory`

## CI Pipeline

CI 8 job çalıştırır (`.github/workflows/ci.yml`):

| Job | Ne yapar |
|-----|----------|
| `lint` | ruff + black + isort |
| `typecheck` | mypy |
| `security` | bandit + pip-audit |
| `test` | pytest (Python 3.11 + 3.12) |
| `benchmark` | Performans testi |
| `regression` | Regresyon pipeline |
| `docker` | Docker build |
| `integration` | PR için integration testleri |

## Test Yazmak Zorunda Olmadığınız Durumlar

- Yalnızca CLI şablonu değişiklikleri
- Dokümantasyon güncellemeleri
- Sadece log mesajı değişiklikleri

Ancak yeni araç, adapter veya önemli mantık değişikliklerinde test **zorunludur**.

## Conftest Fixture'ları

`tests/conftest.py`:

```python
import pytest

@pytest.fixture
def mock_settings():
    """Test için sahte settings."""
    from unittest.mock import MagicMock
    settings = MagicMock()
    settings.llm_provider = "groq"
    settings.security_mode = "permissive"
    return settings

@pytest.fixture
def event_loop_policy():
    """asyncio event loop politikası."""
    import asyncio
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
```
