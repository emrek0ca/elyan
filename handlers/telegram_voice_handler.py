"""
Telegram voice message handler (Phase 13.1)
"""

from telegram import Update
from telegram.ext import ContextTypes
import tempfile
import os
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("telegram_voice")

# Voice response settings (per-user)
VOICE_RESPONSE_ENABLED = {}


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Telegram voice notes"""
    try:
        voice = update.message.voice
        
        if not voice:
            return
        
        # Send processing message
        processing_msg = await update.message.reply_text("🎤 Ses kaydı işleniyor...")
        
        # Download voice file
        temp_dir = tempfile.gettempdir()
        ogg_file = os.path.join(temp_dir, f"voice_{update.message.message_id}.ogg")
        wav_file = os.path.join(temp_dir, f"voice_{update.message.message_id}.wav")
        
        try:
            # Download
            voice_file = await voice.get_file()
            await voice_file.download_to_drive(ogg_file)
            
            logger.info(f"Voice downloaded: {voice.duration}s")
            
            # Validate
            from core.voice import validate_audio_file
            is_valid, error = validate_audio_file(ogg_file)
            
            if not is_valid:
                await processing_msg.edit_text(f" {error}")
                return
            
            # Convert OGG → WAV
            from core.voice import convert_ogg_to_wav
            wav_path = convert_ogg_to_wav(ogg_file, wav_file)
            
            if not wav_path:
                await processing_msg.edit_text(
                    " Ses dönüştürülemedi\n\n"
                    "FFmpeg kurulu mu? `brew install ffmpeg`"
                )
                return
            
            # Transcribe
            from core.voice import get_stt_service
            stt = get_stt_service()
            
            if not stt:
                await processing_msg.edit_text(
                    " Whisper modeli yüklü değil\n\n"
                    "`pip install openai-whisper`"
                )
                return
            
            await processing_msg.edit_text("🎤 Transkript ediliyor...")
            
            result = await stt.transcribe(wav_path, language="tr")
            
            if not result.get("success"):
                await processing_msg.edit_text(f" Transkript hatası: {result.get('error')}")
                return
            
            transcribed_text = result["text"]
            
            if not transcribed_text:
                await processing_msg.edit_text(" Ses anlaşılamadı")
                return
            
            # Show transcription
            await processing_msg.edit_text(
                f" **Transkript:** {transcribed_text}\n\n"
                f"İşleniyor...",
                parse_mode='Markdown'
            )
            
            # Process as text command via agent
            from core.agent import Agent
            agent_instance = context.bot_data.get('agent_instance')
            
            if agent_instance:
                response = await agent_instance.process(transcribed_text)
                
                # Check if voice response is enabled
                user_id = update.effective_user.id
                voice_enabled = VOICE_RESPONSE_ENABLED.get(user_id, False)
                
                if voice_enabled:
                    # Send voice response
                    await _send_voice_response(update, response, transcribed_text)
                else:
                    # Send text response
                    await update.message.reply_text(
                        f" **Sen:** {transcribed_text}\n\n"
                        f" **Wiqo:** {response}",
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text(
                    f" **Transkript:**\n{transcribed_text}",
                    parse_mode='Markdown'
                )
            
            # Delete processing message
            try:
                await processing_msg.delete()
            except:
                pass
        
        finally:
            # Cleanup temp files
            from core.voice import cleanup_temp_files
            cleanup_temp_files(ogg_file, wav_file)
    
    except Exception as e:
        logger.error(f"Voice handler error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_voice_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check voice capabilities status"""
    try:
        from core.voice import check_ffmpeg, WHISPER_AVAILABLE
        
        # Check FFmpeg
        ffmpeg_ok = check_ffmpeg()
        
        # Check Whisper
        whisper_ok = WHISPER_AVAILABLE
        
        # Check STT service
        from core.voice import get_stt_service
        stt = get_stt_service()
        stt_ok = stt is not None
        
        status_text = "🎤 **Voice Capabilities Status**\n\n"
        
        status_text += f"FFmpeg: {' OK' if ffmpeg_ok else ' Missing'}\n"
        if not ffmpeg_ok:
            status_text += "  → Install: `brew install ffmpeg`\n"
        
        status_text += f"Whisper: {' OK' if whisper_ok else ' Missing'}\n"
        if not whisper_ok:
            status_text += "  → Install: `pip install openai-whisper`\n"
        
        status_text += f"STT Service: {' Ready' if stt_ok else ' Not ready'}\n"
        
        if stt_ok and stt:
            status_text += f"  Model: `{stt.model_name}`\n"
        
        status_text += "\n**Usage:**\n"
        status_text += "Just send a voice note → automatic transcription!\n"
        
        await update.message.reply_text(status_text, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Voice status error: {e}")
        await update.message.reply_text(f" Hata: {e}")
