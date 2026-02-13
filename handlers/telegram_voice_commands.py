from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import get_logger
from .telegram_voice_handler import VOICE_RESPONSE_ENABLED

logger = get_logger("telegram_voice_commands")

async def _send_voice_response(update: Update, response_text: str, original_text: str):
    """Send voice response using TTS"""
    import tempfile
    import os
    
    try:
        from core.voice import get_tts_service
        tts = get_tts_service()
        
        if not tts:
            # Fallback to text
            await update.message.reply_text(
                f" **Sen:** {original_text}\n\n"
                f" **Elyan:** {response_text}",
                parse_mode='Markdown'
            )
            return
        
        # Generate voice file
        temp_file = os.path.join(tempfile.gettempdir(), f"tts_{update.message.message_id}.mp3")
        
        success = await tts.synthesize(response_text, temp_file)
        
        if success and os.path.exists(temp_file):
            # Send voice message
            await update.message.reply_voice(
                voice=open(temp_file, 'rb'),
                caption=f" **Sen:** {original_text}\n\n **Elyan (Sesli)**"
            )
            
            # Cleanup
            try:
                os.remove(temp_file)
            except:
                pass
        else:
            # Fallback
            await update.message.reply_text(
                f" **Sen:** {original_text}\n\n"
                f" **Elyan:** {response_text}",
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"Voice response error: {e}")
        await update.message.reply_text(
            f" **Sen:** {original_text}\n\n"
            f" **Elyan:** {response_text}",
            parse_mode='Markdown'
        )


async def cmd_voice_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle voice responses on/off"""
    try:
        user_id = update.effective_user.id
        
        if not context.args or context.args[0] not in ['on', 'off']:
            current = "açık" if VOICE_RESPONSE_ENABLED.get(user_id, False) else "kapalı"
            await update.message.reply_text(
                f"🎤 **Sesli Yanıt:** {current}\n\n"
                f"**Kullanım:**\n"
                f"`/voice on` - Sesli yanıtları aç\n"
                f"`/voice off` - Sesli yanıtları kapat",
                parse_mode='Markdown'
            )
            return
        
        action = context.args[0]
        
        if action == 'on':
            # Check TTS availability
            from core.voice import get_tts_service
            tts = get_tts_service()
            
            if not tts:
                await update.message.reply_text(
                    " TTS servisi yüklü değil\n\n"
                    "`pip install pyttsx3`"
                )
                return
            
            VOICE_RESPONSE_ENABLED[user_id] = True
            await update.message.reply_text(
                " **Sesli yanıtlar AÇIK**\n\n"
                "Artık voice note'larına sesli yanıt vereceğim! 🎤"
            )
        else:
            VOICE_RESPONSE_ENABLED[user_id] = False
            await update.message.reply_text(
                " **Sesli yanıtlar KAPALI**\n\n"
                "Metin yanıtlarına döndüm."
            )
    
    except Exception as e:
        logger.error(f"Voice toggle error: {e}")
        await update.message.reply_text(f" Hata: {e}")
