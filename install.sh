#!/bin/bash
# Elyan v18.0 — Kurulum Betiği
# Kullanım: curl -fsSL <url>/install.sh | bash
#       veya: bash install.sh [--headless] [--no-ui]
# ------------------------------------------------------------------

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[0;33m'; NC='\033[0m'

HEADLESS=0
NO_UI=0
for arg in "$@"; do
  [[ "$arg" == "--headless" ]] && HEADLESS=1
  [[ "$arg" == "--no-ui" ]]    && NO_UI=1
done
PROJECT_DIR="$(pwd -P)"

log()  { echo -e "${BLUE}▸${NC}  $*"; }
ok()   { echo -e "${GREEN}✓${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✗${NC}  $*"; exit 1; }

echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  ELYAN v18.0 — Kurulum Başlatıldı        ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

# ── 1. Python versiyonu ──────────────────────────────────────────────
log "Python sürümü kontrol ediliyor..."
PY=$(command -v python3.12 || command -v python3.11 || command -v python3 || true)
[[ -z "$PY" ]] && err "Python 3.11+ bulunamadı. https://python.org adresinden yükleyin."
PY_VER=$("$PY" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
log "Python: $PY_VER ($PY)"
if [[ "${PY_VER%.*}" -lt 3 ]] || [[ "${PY_VER#*.}" -lt 11 ]]; then
  err "Python 3.11+ gerekli. Mevcut: $PY_VER"
fi
ok "Python $PY_VER"

# ── 2. Sanal ortam ───────────────────────────────────────────────────
log "Sanal ortam hazırlanıyor (.venv)..."
"$PY" -m venv .venv
ok "Sanal ortam oluşturuldu"

PIP=".venv/bin/python3 -m pip"

# ── 3. pip güncelle ──────────────────────────────────────────────────
log "pip güncelleniyor..."
$PIP install --upgrade pip --quiet

# ── 4. Bağımlılıklar ────────────────────────────────────────────────
log "Bağımlılıklar yükleniyor (bu biraz sürebilir)..."
if [[ "$NO_UI" == "1" ]] || [[ "$HEADLESS" == "1" ]]; then
  # UI olmadan kur (sunucu/container mod)
  $PIP install --quiet \
    pydantic json5 httpx aiohttp python-dotenv psutil requests qasync \
    click croniter python-telegram-bot \
    groq google-generativeai \
    beautifulsoup4 lxml Pillow \
    python-docx openpyxl pdfplumber pypdf reportlab \
    apscheduler feedparser watchdog \
    cryptography keyring
else
  $PIP install --quiet -r requirements.txt
fi
ok "Bağımlılıklar yüklendi"

# ── 4.5 Node.js (WhatsApp QR bridge için) ────────────────────────────
log "Node.js kontrolü (WhatsApp QR için)..."
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  NODE_VER=$(node -v 2>/dev/null || true)
  ok "Node.js mevcut (${NODE_VER:-unknown})"
else
  warn "Node.js/npm bulunamadı. WhatsApp QR login için Node.js 18+ önerilir."
fi

# ── 5. Paketi kur ─────────────────────────────────────────────────────
log "Elyan paketi yükleniyor..."
if $PIP install --quiet -e . --config-settings editable_mode=compat; then
  ok "Editable kurulum tamamlandı (compat)."
else
  warn "Editable kurulum başarısız, standart kurulum deneniyor..."
  $PIP install --quiet .
fi

# Python 3.12+ bazı ortamlarda editable entrypoint kırılabilir; doğrulayıp fallback uygula.
if ! .venv/bin/elyan version >/dev/null 2>&1; then
  warn "CLI doğrulaması başarısız. Standart (non-editable) kurulum uygulanıyor..."
  $PIP uninstall -y elyan >/dev/null 2>&1 || true
  $PIP install --quiet .
fi
.venv/bin/elyan version >/dev/null 2>&1 || err "'elyan' CLI çalıştırılamadı. Kurulum loglarını kontrol edin."
ok "'elyan' CLI komutu kullanılabilir"

# ── 6. Dizin yapısı ──────────────────────────────────────────────────
log "Dizin yapısı oluşturuluyor..."
mkdir -p "$HOME/.elyan"/{memory,projects,logs,skills,sandbox,browser}
mkdir -p "$HOME/.local/bin"
ok "~/.elyan/ dizinleri hazır"

# ── 7. Global launcher + PATH ────────────────────────────────────────
log "Global 'elyan' komutu hazırlanıyor..."
LAUNCHER="$HOME/.local/bin/elyan"
PROJECT_DIR_ESCAPED=$(printf '%q' "$PROJECT_DIR")
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
PROJECT_DIR=$PROJECT_DIR_ESCAPED
if [[ ! -x "\$PROJECT_DIR/.venv/bin/python3" ]]; then
  echo "Elyan launcher hatası: \$PROJECT_DIR/.venv/bin/python3 bulunamadı." >&2
  exit 1
fi
export ELYAN_PROJECT_DIR="\$PROJECT_DIR"
cd "\$PROJECT_DIR" || exit 1
exec "\$PROJECT_DIR/.venv/bin/python3" -m elyan_entrypoint "\$@"
EOF
chmod +x "$LAUNCHER"

# Keep .venv/bin/elyan aligned with workspace source, even if pip falls back
# to a non-editable install.
VENV_LAUNCHER="$PROJECT_DIR/.venv/bin/elyan"
cat > "$VENV_LAUNCHER" <<EOF
#!/usr/bin/env bash
PROJECT_DIR=$PROJECT_DIR_ESCAPED
cd "\$PROJECT_DIR" || exit 1
exec "\$PROJECT_DIR/.venv/bin/python3" -m elyan_entrypoint "\$@"
EOF
chmod +x "$VENV_LAUNCHER"

SHELL_NAME=$(basename "${SHELL:-bash}")
if [[ "$SHELL_NAME" == "zsh" ]]; then
  RC_FILE="$HOME/.zshrc"
elif [[ "$SHELL_NAME" == "bash" ]]; then
  RC_FILE="$HOME/.bashrc"
else
  RC_FILE="$HOME/.profile"
fi

PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
touch "$RC_FILE"
if ! grep -Fq '.local/bin' "$RC_FILE"; then
  echo "" >> "$RC_FILE"
  echo "$PATH_LINE" >> "$RC_FILE"
  ok "PATH güncellendi: $RC_FILE"
else
  warn "PATH zaten ayarlı: $RC_FILE"
fi
export PATH="$HOME/.local/bin:$PATH"
ok "Global launcher kuruldu: $LAUNCHER"
ok "Venv launcher kuruldu: $VENV_LAUNCHER"

# ── 8. Shell completion ──────────────────────────────────────────────
log "Shell completion kuruluyor ($SHELL_NAME)..."
.venv/bin/python3 -c "
from cli.commands.completion import _install
_install('$SHELL_NAME')
" 2>/dev/null && ok "Completion kuruldu ($SHELL_NAME)" || warn "Completion kurulamadı (manuel: elyan completion install)"

# ── 9. Özet ─────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Kurulum tamamlandı!                       ${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "Başlamak için:"
echo -e "  ${BLUE}source $RC_FILE${NC}          # PATH değişikliğini uygula"
echo -e "  ${BLUE}export PATH=\"$HOME/.local/bin:$PATH\"${NC}   # Bu terminal için hızlı kullanım"
echo -e "  ${BLUE}elyan onboard${NC}               # Kurulum sihirbazı"
echo -e "  ${BLUE}elyan gateway start${NC}         # Gateway'i başlat"
echo -e "  ${BLUE}elyan dashboard${NC}             # Web panelini aç"
echo -e "  ${BLUE}$HOME/.local/bin/elyan version${NC}  # PATH olmadan doğrulama"
echo ""

# ── 10. Onboarding (headless değilse) ────────────────────────────────
if [[ "$HEADLESS" == "0" ]]; then
  read -rp "Kurulum sihirbazını şimdi başlatmak ister misiniz? (E/h): " ans
  ans_lc=$(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]')
  if [[ "$ans_lc" != "h" ]]; then
    .venv/bin/python3 main.py --onboard
  fi
fi
