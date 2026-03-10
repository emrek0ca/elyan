"""
CLI: voice commands — Full implementation
"""
import asyncio
import click


def _run_voice_start() -> None:
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


def _run_voice_stop() -> None:
    click.echo("Ses modu durduruluyor...")
    try:
        from core.voice.voice_manager import VoiceManager
        vm = VoiceManager()
        asyncio.run(vm.stop())
        click.echo("✓ Ses modu durduruldu.")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


def _run_voice_status() -> None:
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


def _run_voice_test() -> None:
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


def _run_voice_transcribe(file: str) -> None:
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


def _run_voice_speak(text: str, provider: str) -> None:
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


def _run_set_wake_word(word: str) -> None:
    try:
        from core.config_manager import config_manager
        config_manager.set("voice.wake_word", word)
        click.echo(f"✓ Uyandırma kelimesi ayarlandı: '{word}'")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@click.group("voice")
def voice_group():
    """Ses modu yönetimi."""
    pass


@voice_group.command("start")
def voice_start():
    """Ses modunu başlat (wake word dinleme)."""
    _run_voice_start()


@voice_group.command("stop")
def voice_stop():
    """Ses modunu durdur."""
    _run_voice_stop()


@voice_group.command("status")
def voice_status():
    """Ses modu durumunu göster."""
    _run_voice_status()


@voice_group.command("test")
def voice_test():
    """Mikrofon testi yap."""
    _run_voice_test()


@voice_group.command("transcribe")
@click.argument("file", type=click.Path(exists=True))
def voice_transcribe(file):
    """Ses dosyasını metne çevir."""
    _run_voice_transcribe(file)


@voice_group.command("speak")
@click.argument("text")
@click.option("--provider", default="pyttsx3", help="TTS sağlayıcı: pyttsx3 veya elevenlabs")
def voice_speak(text, provider):
    """Metni seslendir."""
    _run_voice_speak(text, provider)


@voice_group.command("set-wake-word")
@click.argument("word")
def voice_set_wake_word(word):
    """Uyandırma kelimesini ayarla."""
    _run_set_wake_word(word)


# Register with main CLI
def register(cli):
    cli.add_command(voice_group, name="voice")


def handle_voice(args) -> int:
    action = str(getattr(args, "action", "") or "").strip().lower()
    text = str(getattr(args, "text", "") or "").strip()
    file_path = str(getattr(args, "file", "") or "").strip()

    if action == "start":
        _run_voice_start()
        return 0
    if action == "stop":
        _run_voice_stop()
        return 0
    if action == "status":
        _run_voice_status()
        return 0
    if action == "test":
        _run_voice_test()
        return 0
    if action == "transcribe":
        if not file_path:
            print("Ses dosyasi gerekli: elyan voice transcribe --file /path/audio.wav")
            return 1
        _run_voice_transcribe(file_path)
        return 0
    if action == "speak":
        if not text:
            print("Seslendirilecek metin gerekli.")
            return 1
        _run_voice_speak(text, "pyttsx3")
        return 0
    if action == "set-wake-word":
        if not text:
            print("Wake word gerekli.")
            return 1
        _run_set_wake_word(text)
        return 0
    if action in {"set-tts", "set-stt", "listen"}:
        print(f"'{action}' komutu icin interactive voice manager entegrasyonu gerekli; CLI yuzeyi su an bilgi seviyesinde.")
        return 0
    print(f"Bilinmeyen voice komutu: {action or '-'}")
    return 1
