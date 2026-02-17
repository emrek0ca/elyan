#!/bin/bash
# Elyan Clean Start - Tüm ayarları sıfırla ve ilk açılış gibi başlat

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ELYAN - Clean Start"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Tüm ayarlar sıfırlanıyor..."
echo ""

# Eski instance'ları kapat
pkill -f "python3 main.py" 2>/dev/null
sleep 0.5

# Config dosyalarını sil
echo "Config dosyaları siliniyor..."
rm -f .env
rm -f ~/.config/cdacs-bot/settings.json
rm -rf ~/.config/cdacs-bot/
rm -rf ~/.elyan/

echo "Learning database siliniyor..."
rm -f ~/.elyan/learning.db

echo "Session dosyaları siliniyor..."
rm -rf ~/.elyan/sessions/

echo ""
echo "Tüm ayarlar sıfırlandı!"
echo "Şimdi ./wiqo.sh ile başlatın - Setup wizard otomatik açılacak."
echo ""
