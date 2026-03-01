#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT_DEFAULT=18789
PORT="${ELYAN_PORT:-$PORT_DEFAULT}"

ok() { printf "[OK] %s\n" "$1"; }
warn() { printf "[WARN] %s\n" "$1"; }
fail() { printf "[FAIL] %s\n" "$1"; exit 1; }

cd "$ROOT_DIR"

command -v python3 >/dev/null 2>&1 || fail "python3 bulunamadı."
ok "python3: $(python3 --version 2>/dev/null || true)"

if [[ -x ".venv/bin/python" ]]; then
  ok ".venv bulundu: $(.venv/bin/python --version 2>/dev/null || true)"
  PTH_DIR=".venv/lib/python3.12/site-packages"
  if [[ -d "$PTH_DIR" ]]; then
    if ls "$PTH_DIR"/*.pth >/dev/null 2>&1; then
      if ls -lO "$PTH_DIR"/*.pth 2>/dev/null | grep -q ' hidden '; then
        chflags nohidden "$PTH_DIR"/*.pth >/dev/null 2>&1 || true
        warn ".pth dosyalarında hidden flag bulundu; nohidden uygulandı."
      else
        ok ".pth flag kontrolü temiz."
      fi
    fi
  fi
else
  warn ".venv yok veya aktif değil."
fi

if command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:"$PORT" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    warn "Port $PORT kullanımda."
  else
    ok "Port $PORT boş."
  fi
else
  warn "lsof bulunamadı; port kontrolü atlandı."
fi

if command -v ollama >/dev/null 2>&1; then
  if ollama list >/dev/null 2>&1; then
    ok "Ollama erişilebilir."
  else
    warn "Ollama kurulu fakat yanıt vermiyor."
  fi
else
  warn "Ollama bulunamadı (local-first modda gerekli olabilir)."
fi

if [[ -f ".env" ]]; then
  ok ".env mevcut."
else
  warn ".env dosyası yok."
fi

ok "Doctor tamamlandı."
