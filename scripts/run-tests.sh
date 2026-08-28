#!/usr/bin/env bash
#
# Test kapısı — parçalı, zaman aşımlı, teşhis edilebilir.
#
# NEDEN VAR: `node --test <293 dosya>` tek seferde koşturulduğunda kapı
# güvenilir biçimde ASILIYORDU. İki sebep birleşiyordu:
#
#   1. `--test-timeout` varsayılanı SONSUZ. Takılan tek bir test, tüm paketi
#      süresiz bekletiyor; deploy script'inin yerel kapısı bu yüzden dakikalarca
#      %0 CPU'da duruyor ve hiçbir şey söylemiyordu. Bir arıza, teşhis
#      edilemiyorsa arıza değil sadece bir duraktır.
#   2. 293 dosya `--test-isolation=process` ile CPU sayısı kadar eşzamanlı
#      koşuyor. Aynı dosyalar KÜÇÜK gruplar halinde temiz bitiyor — sorun
#      dosyalarda değil, ölçekte.
#
# ÇÖZÜM ÜÇ PARÇA:
#   - `--test-timeout`: takılan test artık ADIYLA düşer, sonsuza kadar beklemez.
#   - `--test-force-exit`: testler bittikten SONRA açık kalan bir tanıtıcı
#     (worker, soket, timer) süreci rehin alamaz. Testin kendi takılması hâlâ
#     yukarıdaki zaman aşımıyla yakalanır; bu yalnız bitiş sonrası sızıntıya
#     karşıdır.
#   - Parçalama: paket dört gruba bölünür ve SIRAYLA koşar. Böylece hem tepe
#     kaynak kullanımı düşer hem de bir arıza hangi grupta olduğuyla birlikte
#     raporlanır.
#
# Kullanım:
#   bash scripts/run-tests.sh              # dört parça sırayla
#   bash scripts/run-tests.sh brain        # tek parça
#   TEST_TIMEOUT_MS=90000 bash scripts/run-tests.sh
#
# Not: `dist` derlenmiş olmalı (npm run build). Bu script derleme yapmaz —
# çağıran taraf neyi test ettiğini bilerek çağırsın.

set -uo pipefail

TIMEOUT_MS="${TEST_TIMEOUT_MS:-60000}"
CONCURRENCY="${TEST_CONCURRENCY:-4}"
REQUESTED="${1:-all}"

if [[ ! -d dist ]]; then
  echo "dist/ yok. Önce: npm run build" >&2
  exit 1
fi

# Parçalar kaynak ağacındaki gerçek kümelenmeyi izler; keyfi bölme değildir.
#   brain          114 dosya — semantik/gömme ağırlıklı, en pahalı grup
#   tasks           55 dosya
#   understanding   24 dosya
#   rest           100 dosya — geri kalan her şey
shard_files() {
  case "$1" in
    brain)         find dist/modules/brain -name '*.test.js' -type f ;;
    tasks)         find dist/modules/tasks -name '*.test.js' -type f ;;
    understanding) find dist/core/understanding -name '*.test.js' -type f ;;
    rest)
      find dist -name '*.test.js' -type f \
        -not -path 'dist/modules/brain/*' \
        -not -path 'dist/modules/tasks/*' \
        -not -path 'dist/core/understanding/*'
      ;;
    *) return 1 ;;
  esac
}

run_shard() {
  local shard="$1"
  local files
  files="$(shard_files "$shard" | sort)"

  if [[ -z "${files}" ]]; then
    echo "[${shard}] test dosyası bulunamadı" >&2
    return 1
  fi

  local count
  count="$(printf '%s\n' "${files}" | wc -l | tr -d ' ')"
  echo "==> ${shard} (${count} dosya)"

  local started
  started="$(date +%s)"

  # Çıktı hem GÖSTERİLİR hem saklanır: bir başarısızlığın SEBEBİNİ söylemek
  # için sonradan okunması gerekiyor.
  local logfile
  logfile="$(mktemp -t elyan-test-XXXXXX)"

  # shellcheck disable=SC2086
  node --test \
    --test-timeout="${TIMEOUT_MS}" \
    --test-concurrency="${CONCURRENCY}" \
    --test-force-exit \
    ${files} 2>&1 | tee "${logfile}"
  local status=${PIPESTATUS[0]}

  local elapsed=$(( $(date +%s) - started ))
  if [[ ${status} -ne 0 ]]; then
    echo "==> ${shard} BAŞARISIZ (${elapsed}s, çıkış ${status})" >&2
    # ZAMAN AŞIMI ≠ GERÇEK HATA.
    #
    # Bu kapı bir asılmanın adıyla düşmesi için zaman aşımlı kuruldu. Bedeli:
    # makine yüklüyken (ör. paralel bir Xcode derlemesi) sağlam testler de
    # zaman aşımına uğrayıp kırmızı veriyor. Aynı paket tek başına koşunca
    # geçiyor. Hangi durumda olduğunu söylemeyen bir kapı, birkaç yanlış
    # alarmdan sonra görmezden gelinir — ki bu, kapının hiç olmamasıdır.
    if grep -q "test timed out" "${logfile}"; then
      echo "    NOT: en az bir test ZAMAN AŞIMINA uğradı (${TIMEOUT_MS}ms)." >&2
      echo "    Sistem yükü: $(uptime | sed 's/.*averages*: //')" >&2
      echo "    Yük yüksekse tek başına doğrula: bash scripts/run-tests.sh ${shard}" >&2
    else
      echo "    Doğrulama hatası (zaman aşımı yok) — gerçek bir gerileme." >&2
    fi
    rm -f "${logfile}"
    return "${status}"
  fi
  rm -f "${logfile}"
  echo "==> ${shard} tamam (${elapsed}s)"
  return 0
}

if [[ "${REQUESTED}" != "all" ]]; then
  run_shard "${REQUESTED}" || exit $?
  exit 0
fi

# Ucuz olandan pahalıya: bir arıza varsa erken ve hızlı görünsün.
FAILED=()
for shard in understanding rest tasks brain; do
  run_shard "${shard}" || FAILED+=("${shard}")
done

echo
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "BAŞARISIZ PARÇA: ${FAILED[*]}" >&2
  echo "Tek parçayı yeniden koş: bash scripts/run-tests.sh ${FAILED[0]}" >&2
  exit 1
fi

echo "Tüm parçalar geçti."
