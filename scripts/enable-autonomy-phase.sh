#!/usr/bin/env bash
# Elyan otonomi fazlarını production'da kademeli aç/kapat.
#
# Kullanım:
#   ./scripts/enable-autonomy-phase.sh 2        # Faz 2: understanding envelope v2 (LLM-driven intent)
#   ./scripts/enable-autonomy-phase.sh 3        # Faz 3: turn envelope + agent tool loop
#   ./scripts/enable-autonomy-phase.sh 4        # Faz 4: memory fabric + proactive + continuous learning
#   ./scripts/enable-autonomy-phase.sh status   # mevcut flag durumunu göster
#   ./scripts/enable-autonomy-phase.sh rollback <faz>  # fazın flag'lerini kapat
#
# Her aktivasyon sonrası container restart + health probe yapılır; probe
# başarısızsa flag'ler otomatik geri alınır.
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@84.247.172.213}"
REMOTE_DIR="${REMOTE_DIR:-/srv/elyan-backend}"
ENV_FILE="${REMOTE_DIR}/.env"
HEALTH_URL="${HEALTH_URL:-https://api.elyan.dev/health}"

phase2_flags=(
  "ELYAN_UNDERSTANDING_ENVELOPE_V2_ENABLED"
  "ELYAN_UNDERSTANDING_ENVELOPE_MODEL_FALLBACK_ENABLED"
)
phase3_flags=(
  "ELYAN_TURN_ENVELOPE_ENABLED"
  "ELYAN_AGENT_LOOP_ENABLED"
)
phase4_flags=(
  "ELYAN_MEMORY_FABRIC_V2_ENABLED"
  "ELYAN_PROACTIVE_ENGINE_ENABLED"
  "ELYAN_CONTINUOUS_LEARNING_V2_ENABLED"
)

flags_for_phase() {
  case "$1" in
    2) printf '%s\n' "${phase2_flags[@]}" ;;
    3) printf '%s\n' "${phase3_flags[@]}" ;;
    4) printf '%s\n' "${phase4_flags[@]}" ;;
    *) echo "Bilinmeyen faz: $1" >&2; exit 1 ;;
  esac
}

set_flags() {
  local value="$1"; shift
  local sed_script=""
  for flag in "$@"; do
    sed_script+="s|^${flag}=.*|${flag}=${value}|;"
  done
  # Dosyada olmayan flag'leri sona ekle.
  ssh "${REMOTE_HOST}" "
    set -e
    cp '${ENV_FILE}' '${ENV_FILE}.bak-autonomy'
    sed -i '${sed_script}' '${ENV_FILE}'
    $(for flag in "$@"; do
        echo "grep -q '^${flag}=' '${ENV_FILE}' || echo '${flag}=${value}' >> '${ENV_FILE}';"
      done)
  "
}

restart_and_probe() {
  echo '→ restart + health probe'
  ssh "${REMOTE_HOST}" "cd '${REMOTE_DIR}' && docker compose up -d --force-recreate api >/dev/null 2>&1 || docker compose restart api >/dev/null 2>&1"
  for i in $(seq 1 30); do
    sleep 2
    if curl -fsS --max-time 5 "${HEALTH_URL}" >/dev/null 2>&1; then
      echo "✓ health OK (deneme ${i})"
      return 0
    fi
  done
  echo '✗ health probe BAŞARISIZ — flag geri alınıyor'
  ssh "${REMOTE_HOST}" "cp '${ENV_FILE}.bak-autonomy' '${ENV_FILE}' && cd '${REMOTE_DIR}' && docker compose restart api"
  exit 1
}

case "${1:-}" in
  status)
    ssh "${REMOTE_HOST}" "grep -E 'ENVELOPE|TURN_ENVELOPE|AGENT_(LOOP|ENGINE)|LEARNING|FABRIC|PROACTIVE|COGNITIVE' '${ENV_FILE}' | sort"
    ;;
  rollback)
    phase="${2:?rollback için faz numarası gerekli}"
    mapfile -t flags < <(flags_for_phase "${phase}")
    set_flags "false" "${flags[@]}"
    restart_and_probe
    echo "Faz ${phase} kapatıldı."
    ;;
  2|3|4)
    mapfile -t flags < <(flags_for_phase "$1")
    echo "Faz $1 flag'leri açılıyor: ${flags[*]}"
    set_flags "true" "${flags[@]}"
    restart_and_probe
    echo "Faz $1 AKTİF. Hata izleme: ssh ${REMOTE_HOST} 'cd ${REMOTE_DIR} && docker compose logs --since 10m api | grep -iE \"envelope|agent|error\" | tail -50'"
    ;;
  *)
    echo "Kullanım: $0 {2|3|4|status|rollback <faz>}" >&2
    exit 1
    ;;
esac
