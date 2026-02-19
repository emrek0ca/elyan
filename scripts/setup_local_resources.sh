#!/bin/bash

echo "🚀 Elyan Yerel Kaynak Kurulum Sihirbazı"
echo "======================================"

# 1. Ollama Modellerini Çek
echo "📥 Ollama modelleri kontrol ediliyor..."
ollama pull llama3.1:8b
ollama pull deepseek-r1:8b
ollama pull llava:7b # Vision için

# 2. Piper TTS Modellerini İndir
echo "📥 Yerel Ses (Piper TTS) modelleri indiriliyor..."
VOICE_DIR="$HOME/.elyan/models/voice"
mkdir -p "$VOICE_DIR"

if [ ! -f "$VOICE_DIR/tr_TR-ahmet-medium.onnx" ]; then
    echo "   -> Türkçe ses modeli indiriliyor..."
    curl -L "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-tr-tr-ahmet-medium.onnx" -o "$VOICE_DIR/tr_TR-ahmet-medium.onnx"
    curl -L "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-tr-tr-ahmet-medium.onnx.json" -o "$VOICE_DIR/tr_TR-ahmet-medium.onnx.json"
fi

# 3. Whisper Modeli Kontrol (İlk kullanımda otomatik iner ama burada garantileyelim)
echo "📥 Whisper STT modeli hazırlanıyor..."
python3 -c "import whisper; whisper.load_model('base')"

echo "✅ Tüm yerel kaynaklar hazır. Elyan artık tamamen ücretsiz çalışabilir!"
