#!/bin/bash
# Wiqo Başlatıcı - Tek komutla çalışır

cd "$(dirname "$0")"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  WIQO - Akıllı Asistan"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Virtual environment aktif et
if [ ! -d "venv" ]; then
    echo "venv bulunamadı!"
    exit 1
fi

source venv/bin/activate
echo "Sistem hazır"
echo ""

# Eski instance'ları kapat
pkill -f "python3 main.py" 2>/dev/null
sleep 0.5

# Başlat
echo "Başlatılıyor..."
echo "Üst menü çubuğunda MAVİ NOKTA arayın"
echo ""

python3 main.py

echo ""
echo "Kapatıldı."
