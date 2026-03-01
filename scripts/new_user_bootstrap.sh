#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$(pwd)}"
FRESH_HOME="${ELYAN_FRESH_HOME:-$HOME/.elyan_fresh_user}"
VENV_DIR="${ELYAN_VENV_DIR:-$HOME/.venvs/elyan-fresh}"

if [[ ! -f "$PROJECT_DIR/pyproject.toml" ]]; then
  echo "Hata: pyproject.toml bulunamadı: $PROJECT_DIR"
  echo "Kullanim: bash scripts/new_user_bootstrap.sh /Users/emrekoca/Desktop/bot"
  exit 1
fi

PY="${ELYAN_PY:-}"
if [[ -n "$PY" && ! -x "$PY" ]]; then
  echo "Hata: ELYAN_PY calistirilabilir degil: $PY"
  exit 1
fi
if [[ -z "$PY" ]]; then
  for c in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 python3.13 python3.12 python3.11; do
    if command -v "$c" >/dev/null 2>&1; then
      cand="$(command -v "$c")"
      if [[ "$cand" == "$VENV_DIR/"* ]]; then
        continue
      fi
      if [[ -x "$cand" ]]; then
        PY="$cand"
        break
      fi
    fi
  done
fi
if [[ -z "$PY" ]]; then
  echo "Hata: Python >=3.11 bulunamadi."
  echo "Kur: brew install python@3.11"
  exit 1
fi

pkill -f "elyan|python.*elyan" >/dev/null 2>&1 || true

rm -rf "$FRESH_HOME" "$VENV_DIR"
mkdir -p "$FRESH_HOME" "$(dirname "$VENV_DIR")"

cd "$PROJECT_DIR"
"$PY" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python -m pip install -U pip setuptools wheel >/dev/null
pip install -e ".[dev,telegram]"

USER_BIN_DIR="$HOME/.local/bin"
mkdir -p "$USER_BIN_DIR"
ln -sf "$VENV_DIR/bin/elyan" "$USER_BIN_DIR/elyan"

case ":$PATH:" in
  *":$USER_BIN_DIR:"*) ;;
  *)
    RC_FILE="$HOME/.zshrc"
    if [[ "${SHELL:-}" == */bash ]]; then
      RC_FILE="$HOME/.bashrc"
    fi
    touch "$RC_FILE"
    if ! grep -Fq "export PATH=\"$USER_BIN_DIR:\$PATH\"" "$RC_FILE"; then
      echo "export PATH=\"$USER_BIN_DIR:\$PATH\"" >> "$RC_FILE"
    fi
    ;;
esac

echo
echo "Kurulum tamamlandi."
echo "Onboarding basliyor (yeni kullanici HOME): $FRESH_HOME"
HOME="$FRESH_HOME" "$VENV_DIR/bin/elyan" onboard --force

echo
echo "Gateway baslatiliyor..."
HOME="$FRESH_HOME" "$VENV_DIR/bin/elyan" gateway start --daemon
echo
echo "Kullanim:"
echo "HOME=\"$FRESH_HOME\" \"$VENV_DIR/bin/elyan\" gateway status"
echo "HOME=\"$FRESH_HOME\" \"$VENV_DIR/bin/elyan\" dashboard"
echo "Global komut (yeni terminalde): elyan gateway status"
echo "Binary: $USER_BIN_DIR/elyan"
