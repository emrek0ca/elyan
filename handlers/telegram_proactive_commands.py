"""
Telegram command extensions for Phase 12 - Proactive Features

New commands:
- /schedule - View and manage scheduled jobs
- /schedule_briefing - Schedule morning briefing
- /trigger_briefing - Manually trigger briefing now
- /alerts - View active alerts
- /check_disk - Check disk space
"""

from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import get_logger

logger = get_logger("telegram_proactive")


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all scheduled jobs"""
    try:
        from core.proactive import get_scheduler
        
        scheduler = get_scheduler()
        jobs = scheduler.get_jobs()
        
        if not jobs:
            await update.message.reply_text(" Zamanlanmış görev bulunamadı.")
            return
        
        text = "📅 **Zamanlanmış Görevler**\n\n"
        for job in jobs:
            text += f"• **{job['id']}**\n"
            text += f"  └ Sonraki: {job['next_run'] or 'Bilinmiyor'}\n"
            text += f"  └ Tetikleyici: {job['trigger']}\n\n"
        
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Schedule command error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_schedule_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Schedule morning briefing at specific time"""
    try:
        # Parse arguments: /schedule_briefing 08:30
        if not context.args:
            await update.message.reply_text(
                "📅 Kullanım: /schedule_briefing HH:MM\n"
                "Örnek: /schedule_briefing 08:30"
            )
            return
        
        time_str = context.args[0]
        hour, minute = map(int, time_str.split(':'))
        
        if not (0 <= hour < 24 and 0 <= minute < 60):
            await update.message.reply_text(" Geçersiz saat formatı. 00:00-23:59 arası olmalı.")
            return
        
        from core.proactive import schedule_morning_briefing
        
        # Reschedule briefing
        schedule_morning_briefing(hour=hour, minute=minute)
        
        await update.message.reply_text(
            f" Sabah brifingi {hour:02d}:{minute:02d}'de zamanlandı.\n"
            f"Her gün bu saatte otomatik brief alacaksınız."
        )
        
    except ValueError:
        await update.message.reply_text(" Geçersiz format. Kullanım: /schedule_briefing 08:30")
    except Exception as e:
        logger.error(f"Schedule briefing error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_trigger_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger briefing now"""
    await update.message.reply_text(" Briefing hazırlanıyor...")
    
    try:
        from core.proactive.briefing import trigger_briefing_now
        
        # Create simple notification callback
        async def send_message(msg):
            await update.message.reply_text(msg, parse_mode='Markdown')
        
        # Mock a simple telegram handler with send_message_to_all method
        class SimpleTelegramHandler:
            async def send_message_to_all(self, message):
                await send_message(message)
        
        handler = SimpleTelegramHandler()
        await trigger_briefing_now(telegram_handler=handler)
        
    except Exception as e:
        logger.error(f"Trigger briefing error: {e}")
        await update.message.reply_text(f" Briefing oluşturulamadı: {e}")


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View active alerts"""
    try:
        from core.proactive.alerts import get_alert_manager
        
        alert_manager = get_alert_manager()
        alerts = alert_manager.get_active_alerts()
        
        if not alerts:
            await update.message.reply_text(" Aktif uyarı yok.")
            return
        
        text = " **Aktif Uyarılar**\n\n"
        for alert in alerts:
            alert_type = alert.get('type', 'unknown')
            text += f"• **{alert['id']}** ({alert_type})\n"
            
            if alert_type == 'deadline':
                text += f"  └ Görev: {alert.get('task')}\n"
                text += f"  └ Deadline: {alert.get('deadline')}\n"
            
            text += "\n"
        
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Alerts command error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_check_disk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check disk space"""
    await update.message.reply_text(" Disk alanı kontrol ediliyor...")
    
    try:
        from core.proactive.alerts import get_alert_manager
        import asyncio
        
        # Get disk info via df
        disk_proc = await asyncio.create_subprocess_shell("df -g / | tail -1 | awk '{print $2, $3, $4, $5}'", stdout=asyncio.subprocess.PIPE)
        disk_out, _ = await disk_proc.communicate()
        disk_parts = disk_out.decode().strip().split()
        
        if len(disk_parts) >= 4:
            total_gb = float(disk_parts[0])
            used_gb = float(disk_parts[1])
            free_gb = float(disk_parts[2])
            usage_percent = float(disk_parts[3].replace('%', ''))
        else:
            total_gb, used_gb, free_gb, usage_percent = 0, 0, 0, 0
        
        # Determine status icon
        if usage_percent < 70:
            status_icon = ""
            status_text = "İyi"
        elif usage_percent < 90:
            status_icon = ""
            status_text = "Dikkat"
        else:
            status_icon = ""
            status_text = "Kritik"
        
        text = (
            f"{status_icon} **Disk Durumu: {status_text}**\n\n"
            f" Kullanım: {usage_percent:.1f}%\n"
            f" Boş Alan: {free_gb:.1f} GB / {total_gb:.1f} GB\n"
            f"📁 Kullanılan: {disk.used / (1024**3):.1f} GB"
        )
        
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Check disk error: {e}")
        await update.message.reply_text(f" Hata: {e}")
