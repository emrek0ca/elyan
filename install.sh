#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  Elyan — Tek Komutla Kurulum (macOS / Linux)
#  Kullanim:
#    bash install.sh              # interaktif kurulum
#    bash install.sh --headless   # sessiz kurulum
#    bash install.sh --no-desktop # desktop derlemeden kur
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'
YELLOW='\033[0;33m'; BOLD='\033[1m'; NC='\033[0m'

log()    { echo -e "${BLUE}▸${NC}  $*"; }
ok()     { echo -e "${GREEN}✓${NC}  $*"; }
warn()   { echo -e "${YELLOW}⚠${NC}  $*"; }
err()    { echo -e "${RED}✗${NC}  $*"; exit 1; }
header() { echo ""; echo -e "${BOLD}${BLUE}── $1 ──${NC}"; echo ""; }
pip()    { "$VENV_PY" -m pip "$@"; }   # pip wrapper — path-safe

HEADLESS=0; NO_DESKTOP=0
for arg in "$@"; do
  case "$arg" in
    --headless)   HEADLESS=1 ;;
    --no-desktop) NO_DESKTOP=1 ;;
  esac
done

# Homebrew ve sistem path'lerini ekle
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$SCRIPT_DIR"
[[ ! -f "$PROJECT_DIR/main.py" ]] && err "main.py bulunamadi. Elyan proje kokunde calistir."

echo ""
echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${BLUE}  🧠 ELYAN — KURULUM                              ${NC}"
echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
log "Proje: $PROJECT_DIR"

# ── 1. Python ─────────────────────────────────────────────────────────────────
header "1/7  Python"
PY=""
for c in \
  /opt/homebrew/bin/python3.12 \
  /opt/homebrew/bin/python3.11 \
  /usr/local/bin/python3.12 \
  /usr/local/bin/python3.11 \
  python3.12 python3.11 python3; do
  BIN=""
  [[ -x "$c" ]] && BIN="$c" || BIN="$(command -v "$c" 2>/dev/null || true)"
  [[ -z "$BIN" || ! -x "$BIN" ]] && continue
  v="$("$BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")"
  maj="${v%.*}"; min="${v#*.}"
  if [[ "$maj" -ge 3 && "$min" -ge 11 ]]; then PY="$BIN"; break; fi
done
[[ -z "$PY" ]] && err "Python 3.11+ bulunamadi.\nKur: brew install python@3.11"
ok "Python: $("$PY" --version)"

# ── 2. Sanal Ortam ────────────────────────────────────────────────────────────
header "2/7  Sanal Ortam"
VENV_DIR="$PROJECT_DIR/.venv"
if [[ -d "$VENV_DIR" && -f "$VENV_DIR/bin/python3" ]]; then
  v="$("$VENV_DIR/bin/python3" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")"
  maj="${v%.*}"; min="${v#*.}"
  if [[ "$maj" -ge 3 && "$min" -ge 11 ]]; then
    ok "Mevcut .venv kullaniliyor (Python $v)"
  else
    warn "Eski .venv ($v), yeniden olusturuluyor..."
    rm -rf "$VENV_DIR"
    "$PY" -m venv "$VENV_DIR"
    ok ".venv olusturuldu"
  fi
else
  log ".venv olusturuluyor..."
  "$PY" -m venv "$VENV_DIR"
  ok ".venv olusturuldu"
fi
VENV_PY="$VENV_DIR/bin/python3"
log "pip yukseltiliyor..."
"$VENV_PY" -m pip install --quiet --upgrade pip setuptools wheel
ok "pip hazir"

# ── 3. Python Bagimliliklari ──────────────────────────────────────────────────
header "3/7  Python Bagimliliklari"
log "requirements.txt yukleniyor..."
if "$VENV_PY" -m pip install --quiet -r "$PROJECT_DIR/requirements.txt"; then
  ok "Bagimliliklar yuklendi"
else
  warn "Tam yukleme basarisiz — kritikler deneniyor..."
  "$VENV_PY" -m pip install --quiet \
    flask flask-cors python-socketio python-engineio \
    pydantic aiohttp httpx click psutil cryptography \
    python-dotenv sqlalchemy python-telegram-bot groq \
    sentence-transformers pytest pytest-asyncio
  ok "Kritik bagimliliklar yuklendi"
fi
"$VENV_PY" -m pip install --quiet -e "$PROJECT_DIR" 2>/dev/null \
  || warn "Editable install atlandı (opsiyonel)"

# ── 4. .env ───────────────────────────────────────────────────────────────────
header "4/7  Ortam Yapilandirmasi"
ENV_FILE="$PROJECT_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  log ".env olusturuluyor..."
  cat > "$ENV_FILE" << 'ENVEOF'
# Elyan Ortam Yapılandırması
OLLAMA_HOST=http://localhost:11434
MODEL_NAME=llama3.2:3b
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
GROQ_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ELYAN_AUTO_INSTALL=0
ELYAN_GENESIS_ENABLED=0
ELYAN_PORT=18789
ENVEOF
  ok ".env olusturuldu"
else
  ok ".env mevcut"
fi

# ── 5. Dizinler ───────────────────────────────────────────────────────────────
header "5/7  Uygulama Dizinleri"
mkdir -p "$HOME/.elyan/logs" "$HOME/.elyan/memory" "$HOME/.elyan/workspace"
ok "Dizinler hazir: $HOME/.elyan"

# ── 6. Global CLI ─────────────────────────────────────────────────────────────
header "6/7  CLI Kurulumu"
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"

# Launcher — tırnak sorununu önlemek için cat + heredoc yerine printf
LAUNCHER="$LOCAL_BIN/elyan"
printf '#!/usr/bin/env bash\n' > "$LAUNCHER"
printf 'export ELYAN_PROJECT_DIR="%s"\n' "$PROJECT_DIR" >> "$LAUNCHER"
printf 'export ELYAN_AUTO_INSTALL=0\n' >> "$LAUNCHER"
printf 'export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n' >> "$LAUNCHER"
printf 'cd "%s" || exit 1\n' "$PROJECT_DIR" >> "$LAUNCHER"
printf 'exec "%s" "%s/main.py" "$@"\n' "$VENV_PY" "$PROJECT_DIR" >> "$LAUNCHER"
chmod +x "$LAUNCHER"
ok "CLI: $LAUNCHER"

SHELL_NAME="$(basename "${SHELL:-bash}")"
case "$SHELL_NAME" in
  zsh)  RC="$HOME/.zshrc" ;;
  bash) RC="$HOME/.bashrc" ;;
  *)    RC="$HOME/.profile" ;;
esac
touch "$RC"
if ! grep -q '\.local/bin' "$RC" 2>/dev/null; then
  { printf '\n# Elyan CLI\n'; printf 'export PATH="$HOME/.local/bin:$PATH"\n'; } >> "$RC"
  ok "PATH guncellendi: $RC"
else
  ok "PATH zaten hazir"
fi
export PATH="$LOCAL_BIN:$PATH"

# ── 7. Desktop ────────────────────────────────────────────────────────────────
header "7/7  Desktop Uygulamasi"
DESKTOP_DIR="$PROJECT_DIR/apps/desktop"
if [[ "$NO_DESKTOP" == "0" ]]; then
  NPM_BIN="$(command -v npm 2>/dev/null || echo /opt/homebrew/bin/npm)"
  if [[ -x "$NPM_BIN" ]]; then
    NODE_VER="$(node --version 2>/dev/null || echo N/A)"
    log "Node.js: $NODE_VER"
    log "npm install baslatiliyor..."
    if (cd "$DESKTOP_DIR" && "$NPM_BIN" install --silent 2>/dev/null); then
      ok "npm install tamamlandi"
    else
      warn "npm install basarisiz (desktop olmadan devam)"
    fi
  else
    warn "Node.js bulunamadi — desktop atlanıyor (kur: brew install node)"
  fi
else
  warn "--no-desktop: desktop atlanıyor"
fi

# ── Ortam Dogrulama ───────────────────────────────────────────────────────────
echo ""
log "Ortam dogrulanıyor..."
"$VENV_PY" "$PROJECT_DIR/validate_environment.py" 2>&1 || true

# ── Sonuc ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${GREEN}  ✅  Elyan kurulumu tamamlandi!${NC}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Sonraki adımlar:"
echo ""
echo "  1)  Terminali yenile:    source $RC"
echo "  2)  API anahtarı gir:    nano $ENV_FILE"
echo "  3)  Gateway'i baslat:    elyan start"
echo "  4)  Desktop'u aç:        elyan desktop"
echo "  5)  Durum kontrol:       elyan doctor"
echo ""
