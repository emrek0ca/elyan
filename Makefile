# ── Elyan Makefile ────────────────────────────────────────────────────────────
.PHONY: install dev test lint start stop desktop clean help

VENV     := .venv
PYTHON   := $(VENV)/bin/python3
PIP      := $(VENV)/bin/pip

help:
	@echo ""
	@echo "  Elyan Komutları:"
	@echo ""
	@echo "  make install     — Tam kurulum (venv + bağımlılıklar + CLI)"
	@echo "  make dev         — Geliştirme kurulumu"
	@echo "  make test        — Test suite çalıştır"
	@echo "  make start       — Gateway'i başlat (foreground)"
	@echo "  make start-bg    — Gateway'i arka planda başlat"
	@echo "  make stop        — Gateway'i durdur"
	@echo "  make desktop     — Desktop uygulamayı başlat"
	@echo "  make validate    — Ortam doğrulama"
	@echo "  make clean       — Build artifactları temizle"
	@echo ""

install:
	@bash install.sh

dev:
	@echo "▸  Geliştirme ortamı kuruluyor..."
	$(PIP) install --quiet -r requirements.txt
	$(PIP) install --quiet -e .
	@echo "✓  Hazır. Kullanım: make start"

test:
	$(PYTHON) -m pytest tests/test_elyan_phase2.py tests/test_faz7_memory.py \
	  tests/voice/ tests/unit/ -q --tb=short

validate:
	$(PYTHON) validate_environment.py

start:
	$(PYTHON) main.py start

start-bg:
	$(PYTHON) main.py start --daemon

stop:
	$(PYTHON) main.py stop

desktop:
	$(PYTHON) main.py desktop

clean:
	rm -rf build/ dist/ *.egg-info/ __pycache__/
	find . -name "*.pyc" -delete -not -path "./.venv/*"
	@echo "✓  Temizlendi"
