#!/usr/bin/env bash
# Elyan masaüstü ajanı kurulumu (macOS + Linux).
#   curl -fsSL https://elyan.dev/install.sh | bash
# veya mevcut checkout içinde:  bash scripts/install.sh
set -euo pipefail

REPO_URL="${ELYAN_REPO_URL:-https://github.com/elyan-dev/elyan.git}"
INSTALL_DIR="${ELYAN_HOME:-$HOME/.elyan}"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

# 1) Python 3.10–3.13 (LangGraph/Pydantic zincirinin desteklediği aralık)
PY_BIN=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  resolved="$(command -v "$candidate" || true)"
  if [ -n "$resolved" ] && "$resolved" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)'; then
    PY_BIN="$resolved"
    break
  fi
done
if [ -z "$PY_BIN" ]; then
  say "HATA: uyumlu Python bulunamadı. Python 3.10–3.13 kur."
  exit 1
fi

# 2) Kaynak: checkout içindeysek onu kullan, değilsek klonla
if [ -f "$(dirname "$0")/../runtime/bridge.py" ] 2>/dev/null; then
  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
else
  say "Elyan indiriliyor → $INSTALL_DIR"
  if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only
  else
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  fi
  ROOT="$INSTALL_DIR"
fi

# 3) venv + bağımlılıklar
say "Sanal ortam hazırlanıyor…"
cd "$ROOT"
if [ -x venv/bin/python ] && ! venv/bin/python -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)'; then
  say "Uyumsuz Python sanal ortamı yenileniyor…"
  rm -rf -- "$ROOT/venv"
fi
[ -d venv ] || "$PY_BIN" -m venv venv
./venv/bin/python -m pip install --quiet --upgrade pip
./venv/bin/python -m pip install --quiet -r requirements-core.txt
if ! ./venv/bin/python scripts/install_extras.py; then
  say "NOT: Bazı opsiyonel yetenekler kurulamadı; çekirdek çalışma hazır. Ayrıntı için: elyan doctor"
fi

# 4) `elyan` komutu
BIN_TARGET="$HOME/.local/bin"
mkdir -p "$BIN_TARGET"
ln -sf "$ROOT/bin/elyan" "$BIN_TARGET/elyan"
case ":$PATH:" in
  *":$BIN_TARGET:"*) ;;
  *) say "NOT: $BIN_TARGET PATH'te değil — kabuk profiline ekle: export PATH=\"\$PATH:$BIN_TARGET\"" ;;
esac

# 5) Sağlık kontrolü + yönlendirme
say ""
"$ROOT/bin/elyan" doctor || true
say ""
say "Kurulum tamam. Sıradaki adımlar:"
say "  1) elyan pair              # QR'ı iOS uygulamasıyla okut"
say "  2) elyan service install   # açılışta otomatik başlat"
