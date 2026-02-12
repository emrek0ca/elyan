"""
Telegram commands for Email Inbox Triage (Phase 12.4)
"""

from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import get_logger
import os

logger = get_logger("telegram_email")


async def cmd_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get inbox summary"""
    try:
        from core.proactive.email_triage import get_email_triage_service
        
        # Check if email is configured
        email_service = get_email_triage_service()
        
        if not email_service:
            await update.message.reply_text(
                " **Email Yapılandırması Gerekli**\n\n"
                "Önce email ayarlarını yap:\n"
                "`/setup_email imap.gmail.com your@email.com your_password`\n\n"
                "**Gmail için:**\n"
                "1. IMAP'ı aktifleştir (Settings → Forwarding and POP/IMAP)\n"
                "2. App-specific password oluştur (güvenlik için)\n"
                "3. `/setup_email imap.gmail.com your@gmail.com app_password`",
                parse_mode='Markdown'
            )
            return
        
        # Get inbox summary
        await update.message.reply_text("📬 Inbox kontrol ediliyor...")
        
        result = await email_service.get_inbox_summary()
        
        if not result.get("success"):
            await update.message.reply_text(
                f" Inbox okunamadı: {result.get('error', 'Unknown error')}"
            )
            return
        
        summary = result["summary"]
        unread_count = result.get("unread_count", 0)
        
        await update.message.reply_text(
            f"**📬 Inbox Özeti**\n\n{summary}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Inbox command error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_setup_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Setup email configuration"""
    try:
        if len(context.args) != 3:
            await update.message.reply_text(
                " **Email Kurulumu**\n\n"
                "**Kullanım:**\n"
                "`/setup_email <imap_server> <email> <password>`\n\n"
                "**Örnekler:**\n"
                "• Gmail: `/setup_email imap.gmail.com user@gmail.com app_password`\n"
                "• Outlook: `/setup_email imap-mail.outlook.com user@outlook.com password`\n"
                "• Yahoo: `/setup_email imap.mail.yahoo.com user@yahoo.com password`\n\n"
                "**NOT:** Gmail için app-specific password kullanın (2FA varsa zorunlu)",
                parse_mode='Markdown'
            )
            return
        
        imap_server, email_address, password = context.args
        
        # Test connection
        await update.message.reply_text("🔌 Bağlantı test ediliyor...")
        
        from core.proactive.email_triage import EmailTriageService
        
        service = EmailTriageService(imap_server, email_address, password)
        
        if not service.connect():
            await update.message.reply_text(
                " **Bağlantı Başarısız**\n\n"
                "Kontrol edin:\n"
                "• IMAP server doğru mu?\n"
                "• Email ve şifre doğru mu?\n"
                "• IMAP aktif mi? (email settings)\n"
                "• 2FA varsa app password kullandınız mı?",
                parse_mode='Markdown'
            )
            return
        
        # Get unread count to verify
        unread_info = service.get_unread_count()
        service.disconnect()
        
        if not unread_info.get("success"):
            await update.message.reply_text(" Inbox okunamadı, ayarları kontrol edin")
            return
        
        # Save to environment (for this session only)
        # NOTE: For production, save to .env or database
        os.environ['EMAIL_IMAP_SERVER'] = imap_server
        os.environ['EMAIL_ADDRESS'] = email_address
        os.environ['EMAIL_PASSWORD'] = password
        
        # Initialize global service
        from core.proactive.email_triage import get_email_triage_service
        get_email_triage_service(imap_server, email_address, password)
        
        unread_count = unread_info.get("unread_count", 0)
        total = unread_info.get("total_messages", 0)
        
        await update.message.reply_text(
            f" **Email Yapılandırıldı!**\n\n"
            f" Email: `{email_address}`\n"
            f"📬 Okunmamış: **{unread_count}**\n"
            f" Toplam: {total}\n\n"
            f"Kullanım:\n"
            f"• `/inbox` - Inbox özeti\n"
            f"• `/unread` - Okunmamış sayısı\n\n"
            f"**NOT:** Ayarlar bu oturum için geçerli. Kalıcı yapmak için `.env` dosyasına ekleyin.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Setup email error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_unread(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get unread email count"""
    try:
        from core.proactive.email_triage import get_email_triage_service
        
        email_service = get_email_triage_service()
        
        if not email_service:
            await update.message.reply_text(
                " Email yapılandırılmamış. Önce `/setup_email` kullanın.",
                parse_mode='Markdown'
            )
            return
        
        result = email_service.get_unread_count()
        
        if not result.get("success"):
            await update.message.reply_text(f" Hata: {result.get('error')}")
            return
        
        unread = result["unread_count"]
        total = result.get("total_messages", 0)
        
        if unread == 0:
            await update.message.reply_text(" Inbox temiz! Okunmamış email yok. 🎉")
        else:
            await update.message.reply_text(
                f"📬 **{unread} okunmamış email**\n"
                f" Toplam: {total}\n\n"
                f"Detay için: `/inbox`",
                parse_mode='Markdown'
            )
        
    except Exception as e:
        logger.error(f"Unread command error: {e}")
        await update.message.reply_text(f" Hata: {e}")
