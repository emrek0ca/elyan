#!/usr/bin/env bash
#
# Tüm şema bootstrap script'lerini SIRAYLA çalıştırır.
#
# NEDEN VAR: on dokuz script deploy'da elle yazılmış bir kabuk zinciriyle
# çağrılıyordu — `bash scripts/bootstrap-v1-...sh && bash scripts/bootstrap-v2-...sh && …`.
# O zincir tek bir yerde durmuyordu: deploy script'inin içinde bir satır,
# dokümanda bir başkası. Deploy'u elle yürütmek gerektiğinde (bugün iki kez
# gerekti) o sıra hafızadan yeniden kurulmak zorunda kalıyordu, ve bir
# script'in atlanması sessizce eksik şema demek.
#
# Sıra numaradan gelir, dosya adından değil: `v2` `v10`dan ÖNCE gelmeli.
# Kabuk glob'u alfabetik sıralar ve `v10` `v2`den önce gelirdi — bu, sırası
# önemli olan göçlerde sessiz bir hata sınıfıdır.
#
# Script'ler zaten idempotenttir ("already exists, skipping"); bu yüzden hepsi
# her koşuda çalışır. Uygulananları kaydedip atlamak, sonradan DÜZELTİLEN bir
# script'i bir daha hiç koşturmama riskini getirirdi — DDL ucuz, o risk değil.
#
# Kullanım:
#   bash scripts/bootstrap-all.sh
#   BOOTSTRAP_DRY_RUN=1 bash scripts/bootstrap-all.sh   # yalnız sırayı yazdır

set -uo pipefail
cd "$(dirname "$0")/.."

# `mapfile` bash 4+ gerektirir; macOS hâlâ bash 3.2 ile geliyor ve bu script
# hem yerelde hem sunucuda aynı şekilde çalışmak zorunda.
ORDERED=()
while IFS= read -r file; do
  [[ -n "${file}" ]] && ORDERED+=("${file}")
done < <(
  for file in scripts/bootstrap-v*-schema.sh; do
    [[ -e "${file}" ]] || continue
    version="$(printf '%s' "${file}" | sed -E 's|.*bootstrap-v([0-9]+).*|\1|')"
    printf '%s\t%s\n' "${version}" "${file}"
  done | sort -n -k1,1 -k2,2 | cut -f2
)

if [[ ${#ORDERED[@]} -eq 0 ]]; then
  echo "bootstrap script'i bulunamadı" >&2
  exit 1
fi

echo "==> ${#ORDERED[@]} şema script'i, sürüm sırasıyla"

if [[ -n "${BOOTSTRAP_DRY_RUN:-}" ]]; then
  printf '  %s\n' "${ORDERED[@]}"
  exit 0
fi

for script in "${ORDERED[@]}"; do
  printf '  -> %s\n' "${script}"
  if ! bash "${script}"; then
    echo "BAŞARISIZ: ${script}" >&2
    echo "Düzelttikten sonra baştan koş; script'ler idempotenttir." >&2
    exit 1
  fi
done

echo "==> şema güncel"
