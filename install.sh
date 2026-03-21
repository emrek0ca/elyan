#!/usr/bin/env bash
# Elyan installer and remote bootstrap
# Usage:
#   curl -fsSL https://get.elyan.ai | bash
#   bash install.sh [--headless] [--no-ui]

set -euo pipefail

REPO_URL="${ELYAN_REPO_URL:-https://github.com/emrek0ca/elyan.git}"
INSTALL_DIR="${ELYAN_INSTALL_DIR:-$HOME/.local/share/elyan/src/elyan}"

HEADLESS=0
NO_UI=0
for arg in "$@"; do
  case "$arg" in
    --headless) HEADLESS=1 ;;
    --no-ui) NO_UI=1 ;;
  esac
done

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m'

log()  { echo -e "${BLUE}▸${NC}  $*"; }
ok()   { echo -e "${GREEN}✓${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✗${NC}  $*"; exit 1; }

resolve_project_dir() {
  if git_root="$(git rev-parse --show-toplevel 2>/dev/null)" && [[ -f "$git_root/pyproject.toml" ]]; then
    printf '%s\n' "$git_root"
    return 0
  fi

  local cwd
  cwd="$(pwd -P)"
  if [[ -f "$cwd/pyproject.toml" && -f "$cwd/cli/main.py" ]]; then
    printf '%s\n' "$cwd"
    return 0
  fi

  printf '%s\n' ""
}

clone_repo() {
  local target="$1"
  local parent
  parent="$(dirname "$target")"
  mkdir -p "$parent"

  if [[ -d "$target/.git" ]]; then
    log "Existing clone found: $target"
    return 0
  fi

  rm -rf "$target"
  if command -v git >/dev/null 2>&1; then
    log "Cloning Elyan from $REPO_URL"
    git clone --depth 1 "$REPO_URL" "$target"
    return 0
  fi

  if command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1; then
    log "Downloading Elyan source archive"
    local archive
    archive="$(mktemp)"
    curl -fsSL "https://codeload.github.com/emrek0ca/elyan/tar.gz/refs/heads/main" -o "$archive"
    tar -xzf "$archive" -C "$parent"
    mv "$parent/elyan-main" "$target"
    rm -f "$archive"
    return 0
  fi

  err "git or curl/tar not available; cannot fetch Elyan source."
}

PROJECT_DIR="$(resolve_project_dir)"
if [[ -z "$PROJECT_DIR" ]]; then
  log "Source tree not found, bootstrapping a fresh clone"
  clone_repo "$INSTALL_DIR"
  PROJECT_DIR="$INSTALL_DIR"
fi

cd "$PROJECT_DIR"
export ELYAN_PROJECT_DIR="$PROJECT_DIR"
WORKSPACE="$PROJECT_DIR"

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  ELYAN INSTALLER STARTED                  ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

log "Checking Python..."
PY="$(command -v python3.12 || command -v python3.11 || command -v python3 || true)"
[[ -z "$PY" ]] && err "Python 3.11+ not found."
PY_VER="$("$PY" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
log "Python: $PY_VER ($PY)"

if [[ "${PY_VER%.*}" -lt 3 ]] || [[ "${PY_VER#*.}" -lt 11 ]]; then
  err "Python 3.11+ required."
fi
ok "Python version OK"

log "Creating virtual environment"
"$PY" -m venv .venv

log "Bootstrapping pip"
if ! .venv/bin/python3 -m ensurepip --upgrade >/dev/null 2>&1; then
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o .venv/get-pip.py
    .venv/bin/python3 .venv/get-pip.py
    rm -f .venv/get-pip.py
  else
    err "ensurepip failed and curl is unavailable."
  fi
fi

PIP=".venv/bin/python3 -m pip"
log "Upgrading packaging tools"
.venv/bin/python3 -m pip install --upgrade pip setuptools wheel --quiet

log "Installing dependencies"
if [[ "$NO_UI" == "1" || "$HEADLESS" == "1" ]]; then
  $PIP install --quiet \
    pydantic json5 httpx aiohttp python-dotenv psutil requests \
    click croniter python-telegram-bot \
    groq google-generativeai \
    beautifulsoup4 lxml Pillow \
    python-docx openpyxl pdfplumber pypdf reportlab \
    apscheduler feedparser watchdog \
    cryptography keyring sqlalchemy
else
  $PIP install --quiet -r requirements.txt
fi
ok "Dependencies installed"

log "Installing Elyan package"
if $PIP install --quiet -e . --config-settings editable_mode=compat; then
  ok "Editable install complete"
else
  warn "Editable install failed, retrying as a standard install"
  $PIP install --quiet .
fi

if ! .venv/bin/elyan version >/dev/null 2>&1; then
  warn "CLI check failed, reinstalling package once"
  $PIP uninstall -y elyan >/dev/null 2>&1 || true
  $PIP install --quiet .
fi

.venv/bin/elyan version >/dev/null 2>&1 || err "'elyan' CLI is not available."
ok "CLI available"

log "Preparing runtime directories"
.venv/bin/python3 -m elyan.bootstrap dirs --home "$HOME/.elyan" >/dev/null
mkdir -p "$HOME/.local/bin"
ok "Runtime directories ready"

log "Creating launcher scripts"
PROJECT_DIR_ESCAPED=$(printf '%q' "$PROJECT_DIR")

cat > "$HOME/.local/bin/elyan" <<EOF
#!/usr/bin/env bash
PROJECT_DIR=$PROJECT_DIR_ESCAPED
export ELYAN_PROJECT_DIR="\$PROJECT_DIR"
cd "\$PROJECT_DIR" || exit 1
exec "\$PROJECT_DIR/.venv/bin/python3" -m elyan_entrypoint "\$@"
EOF
chmod +x "$HOME/.local/bin/elyan"

cat > "$PROJECT_DIR/.venv/bin/elyan" <<EOF
#!/usr/bin/env bash
PROJECT_DIR=$PROJECT_DIR_ESCAPED
export ELYAN_PROJECT_DIR="\$PROJECT_DIR"
cd "\$PROJECT_DIR" || exit 1
exec "\$PROJECT_DIR/.venv/bin/python3" -m elyan_entrypoint "\$@"
EOF
chmod +x "$PROJECT_DIR/.venv/bin/elyan"

SHELL_NAME="$(basename "${SHELL:-bash}")"
if [[ "$SHELL_NAME" == "zsh" ]]; then
  RC_FILE="$HOME/.zshrc"
elif [[ "$SHELL_NAME" == "bash" ]]; then
  RC_FILE="$HOME/.bashrc"
else
  RC_FILE="$HOME/.profile"
fi

touch "$RC_FILE"
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
if ! grep -Fq '.local/bin' "$RC_FILE"; then
  echo "" >> "$RC_FILE"
  echo "$PATH_LINE" >> "$RC_FILE"
  ok "PATH updated: $RC_FILE"
else
  warn "PATH already contains ~/.local/bin"
fi
export PATH="$HOME/.local/bin:$PATH"

log "Creating workspace bootstrap files"
if [[ "$HEADLESS" == "1" || "$NO_UI" == "1" ]]; then
  .venv/bin/python3 -m elyan.bootstrap init --workspace "$WORKSPACE" --role operator --headless >/dev/null
else
  .venv/bin/python3 -m elyan.bootstrap init --workspace "$WORKSPACE" --role operator --open-dashboard >/dev/null
fi
ok "Workspace files created"

log "Running onboarding"
if [[ "$HEADLESS" == "1" || "$NO_UI" == "1" ]]; then
  .venv/bin/elyan bootstrap onboard --headless --install-daemon || warn "Bootstrap onboarding did not complete."
else
  read -rp "Run onboarding now? (Y/n): " ans
  ans_lc="$(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]')"
  if [[ "$ans_lc" != "n" ]]; then
    .venv/bin/elyan bootstrap onboard || warn "Bootstrap onboarding did not complete."
  fi
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Elyan installation complete             ${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Next:"
echo "  source $RC_FILE"
echo "  elyan status"
echo "  elyan gateway start --daemon"
echo "  elyan dashboard"
echo ""
