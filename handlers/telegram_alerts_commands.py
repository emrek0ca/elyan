"""
Extended Telegram commands for Smart Alerts (Phase 12.3)
"""

from telegram import Update
from telegram.ext import ContextTypes
from datetime import datetime, timedelta
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("telegram_alerts")


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start watching a directory for file changes"""
    try:
        if not context.args:
            await update.message.reply_text(
                "📁 **Kullanım:** `/watch <dizin_yolu> [pattern]`\n\n"
                "**Örnekler:**\n"
                "• `/watch ~/Desktop` - Tüm dosyalar\n"
                "• `/watch ~/Documents *.pdf` - Sadece PDF'ler\n"
                "• `/watch ~/Downloads *.zip,*.rar` - ZIP ve RAR",
                parse_mode='Markdown'
            )
            return
        
        directory = context.args[0].replace('~', str(Path.home()))
        patterns = context.args[1].split(',') if len(context.args) > 1 else None
        
        # Validate directory
        dir_path = Path(directory)
        if not dir_path.exists():
            await update.message.reply_text(f" Dizin bulunamadı: {directory}")
            return
        
        if not dir_path.is_dir():
            await update.message.reply_text(f" Bu bir dizin değil: {directory}")
            return
        
        # Start watching
        from core.proactive.alerts import get_alert_manager
        alert_manager = get_alert_manager()
        
        # Set notification callback to send to Telegram
        async def send_notification(title, message):
            await update.message.reply_text(f"**{title}**\n\n{message}", parse_mode='Markdown')
        
        alert_manager.set_notify_callback(send_notification)
        
        success = alert_manager.watch_directory(
            path=str(dir_path),
            alert_id=f"watch_{dir_path.name}",
            patterns=patterns
        )
        
        if success:
            pattern_text = f"Pattern: {', '.join(patterns)}" if patterns else "Tüm dosyalar"
            await update.message.reply_text(
                f" **Dizin izleniyor**\n\n"
                f"📁 Dizin: `{dir_path.name}`\n"
                f" {pattern_text}\n\n"
                f"Değişiklikler bu sohbete bildirilecek.\n"
                f"Durdurmak için: `/unwatch {dir_path.name}`",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                " Dizin izleme başlatılamadı.\n"
                "watchdog yüklü mü kontrol edin: `pip install watchdog`",
                parse_mode='Markdown'
            )
        
    except Exception as e:
        logger.error(f"Watch command error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop watching a directory"""
    try:
        if not context.args:
            # List all watchers
            from core.proactive.alerts import get_alert_manager
            alert_manager = get_alert_manager()
            watchers = alert_manager.get_watchers()
            
            if not watchers:
                await update.message.reply_text("ℹ️ Aktif izleme yok.")
                return
            
            text = "📁 **Aktif İzlemeler:**\n\n"
            for w in watchers:
                text += f"• `{w['id']}` - {w['path']}\n"
            text += "\n`/unwatch <id>` ile durdurabilirsiniz."
            
            await update.message.reply_text(text, parse_mode='Markdown')
            return
        
        alert_id = context.args[0]
        
        from core.proactive.alerts import get_alert_manager
        alert_manager = get_alert_manager()
        
        success = alert_manager.stop_watching(alert_id)
        
        if success:
            await update.message.reply_text(f" İzleme durduruldu: `{alert_id}`", parse_mode='Markdown')
        else:
            await update.message.reply_text(f" İzleme bulunamadı: `{alert_id}`", parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Unwatch command error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a deadline reminder"""
    try:
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                " **Kullanım:** `/deadline <görev> <tarih_saat>`\n\n"
                "**Örnekler:**\n"
                "• `/deadline \"Proje raporu\" 2026-02-10 18:00`\n"
                "• `/deadline Meeting 15:30` (bugün)\n\n"
                "1 saat önce hatırlatma alacaksınız.",
                parse_mode='Markdown'
            )
            return
        
        # Parse task name (might be quoted)
        if context.args[0].startswith('"'):
            # Find closing quote
            task_parts = []
            in_quote = False
            for arg in context.args:
                if arg.startswith('"'):
                    in_quote = True
                    task_parts.append(arg[1:])
                elif arg.endswith('"'):
                    task_parts.append(arg[:-1])
                    break
                elif in_quote:
                    task_parts.append(arg)
            task_name = ' '.join(task_parts)
            time_args = context.args[len(task_parts)+1:]
        else:
            task_name = context.args[0]
            time_args = context.args[1:]
        
        # Parse datetime
        if len(time_args) == 2:  # Date and time
            date_str, time_str = time_args
            deadline = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        elif len(time_args) == 1:  # Just time (today)
            time_str = time_args[0]
            today = datetime.now().strftime("%Y-%m-%d")
            deadline = datetime.strptime(f"{today} {time_str}", "%Y-%m-%d %H:%M")
        else:
            await update.message.reply_text(" Geçersiz tarih/saat formatı")
            return
        
        # Check if deadline is in the future
        if deadline <= datetime.now():
            await update.message.reply_text(" Deadline geçmişte olamaz")
            return
        
        # Add deadline
        from core.proactive.alerts import get_alert_manager
        alert_manager = get_alert_manager()
        
        # Set notification callback
        async def send_notification(title, message):
            await update.message.reply_text(f"**{title}**\n\n{message}", parse_mode='Markdown')
        
        alert_manager.set_notify_callback(send_notification)
        
        alert_id = await alert_manager.add_deadline_reminder(task_name, deadline)
        
        time_until = deadline - datetime.now()
        hours = int(time_until.total_seconds() / 3600)
        
        await update.message.reply_text(
            f" **Deadline Eklendi**\n\n"
            f" Görev: {task_name}\n"
            f" Deadline: {deadline.strftime('%d %B %H:%M')}\n"
            f" Kalan: {hours} saat\n\n"
            f"1 saat önce hatırlatılacaksınız.\n"
            f"ID: `{alert_id}`",
            parse_mode='Markdown'
        )
        
    except ValueError as e:
        await update.message.reply_text(
            f" Tarih formatı hatası\n\n"
            f"Doğru format:\n"
            f"• `2026-02-10 18:00` (tam tarih)\n"
            f"• `15:30` (bugün)",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Deadline command error: {e}")
        await update.message.reply_text(f" Hata: {e}")
