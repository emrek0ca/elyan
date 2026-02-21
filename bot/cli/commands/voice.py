"""
CLI: voice commands — Full implementation
"""
import asyncio
import click
from pathlib import Path


@click.group("voice")
def voice_group():
    """Ses modu yönetimi."""
    pass


@voice_group.command("start")
def voice_start():
    """Ses modunu başlat (wake word dinleme)."""
    click.echo("🎤 Ses modu başlatılıyor...")
    try:
        from core.voice.voice_manager import VoiceManager
        vm = VoiceManager()
        asyncio.run(vm.start())
        click.echo("✓ Ses modu aktif. Wake word: 'elyan'")
    except ImportError:
        click.echo("⚠️  Ses modülü bulunamadı. Yüklemek için: pip install openai-whisper pyttsx3", err=True)
    except Exception as e:
        click.echo(f"✗ Ses modu başlatılamadı: {e}", err=True)


@voice_group.command("stop")
def voice_stop():
    """Ses modunu durdur."""
    click.echo("Ses modu durduruluyor...")
    try:
        from core.voice.voice_manager import VoiceManager
        vm = VoiceManager()
        asyncio.run(vm.stop())
        click.echo("✓ Ses modu durduruldu.")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@voice_group.command("status")
def voice_status():
    """Ses modu durumunu göster."""
    try:
        from core.voice.voice_manager import VoiceManager
        vm = VoiceManager()
        status = vm.get_status()
        click.echo(f"Ses Modu: {'✓ Aktif' if status.get('running') else '✗ Pasif'}")
        click.echo(f"STT:      {status.get('stt_provider', 'whisper')}")
        click.echo(f"TTS:      {status.get('tts_provider', 'pyttsx3')}")
        click.echo(f"Wake:     {status.get('wake_word', 'elyan')}")
    except Exception as e:
        click.echo(f"Ses modu durumu alınamadı: {e}", err=True)


@voice_group.command("test")
def voice_test():
    """Mikrofon testi yap."""
    click.echo("🎤 Mikrofon test ediliyor (3 saniye)...")
    try:
        import sounddevice as sd
        import numpy as np
        duration = 3
        fs = 16000
        recording = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='float32')
        sd.wait()
        level = float(np.abs(recording).mean())
        click.echo(f"✓ Ses seviyesi: {level:.4f} {'(iyi)' if level > 0.001 else '(çok düşük - mikrofon kontrol edin)'}")
    except ImportError:
        click.echo("⚠️  sounddevice kurulu değil: pip install sounddevice", err=True)
    except Exception as e:
        click.echo(f"✗ Mikrofon testi başarısız: {e}", err=True)


@voice_group.command("transcribe")
@click.argument("file", type=click.Path(exists=True))
def voice_transcribe(file):
    """Ses dosyasını metne çevir."""
    click.echo(f"📝 Transkripsiyon başlatılıyor: {file}")
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(file)
        click.echo(f"\n{result['text']}")
    except ImportError:
        click.echo("⚠️  whisper kurulu değil: pip install openai-whisper", err=True)
    except Exception as e:
        click.echo(f"✗ Transkripsiyon başarısız: {e}", err=True)


@voice_group.command("speak")
@click.argument("text")
@click.option("--provider", default="pyttsx3", help="TTS sağlayıcı: pyttsx3 veya elevenlabs")
def voice_speak(text, provider):
    """Metni seslendir."""
    click.echo(f"🔊 Seslendiriliyor ({provider})...")
    try:
        if provider == "pyttsx3":
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            click.echo("✓ Tamamlandı.")
        else:
            click.echo(f"⚠️  '{provider}' sağlayıcısı henüz desteklenmiyor.", err=True)
    except ImportError:
        click.echo("⚠️  pyttsx3 kurulu değil: pip install pyttsx3", err=True)
    except Exception as e:
        click.echo(f"✗ Seslendirme başarısız: {e}", err=True)


@voice_group.command("set-wake-word")
@click.argument("word")
def voice_set_wake_word(word):
    """Uyandırma kelimesini ayarla."""
    try:
        from core.config_manager import config_manager
        config_manager.set("voice.wake_word", word)
        click.echo(f"✓ Uyandırma kelimesi ayarlandı: '{word}'")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


# Register with main CLI
def register(cli):
    cli.add_command(voice_group, name="voice")
