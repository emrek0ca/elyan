"""
Extended Telegram Commands
Advanced features and utilities for Telegram handler
"""

from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import get_logger
from pathlib import Path
import os

logger = get_logger("telegram_extensions")


async def cmd_execute_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute Python, JavaScript, or shell code"""
    if not context.args:
        await update.message.reply_text(
            "Kod çalıştırma\n"
            "──────────────\n\n"
            "Kullanım:\n"
            "/code python <kod>\n"
            "/code javascript <kod>\n"
            "/code shell <komut>\n\n"
            "Örnek:\n"
            "/code python print('Merhaba')"
        )
        return

    language = context.args[0] if context.args else "python"
    code = " ".join(context.args[1:]) if len(context.args) > 1 else ""

    if not code:
        await update.message.reply_text("Lütfen kod sağlayın")
        return

    try:
        await update.message.reply_text(f" {language} kodu çalıştırılıyor...")

        from tools.code_execution_tools import (
            execute_python_code,
            execute_javascript_code,
            execute_shell_command
        )

        if language == "python":
            result = await execute_python_code(code)
        elif language == "javascript":
            result = await execute_javascript_code(code)
        elif language == "shell":
            result = await execute_shell_command(code)
        else:
            await update.message.reply_text(f"Bilinmeyen dil: {language}")
            return

        # Format output
        output_text = f"<b>{language.upper()}</b>\n\n"

        if result.get("success"):
            output_text += f"<b>✓ Başarılı</b> ({result.get('execution_time', 0):.2f}s)\n"
            if result.get("output"):
                output_text += f"\n<code>{result['output'][:500]}</code>"
        else:
            output_text += f"<b>✗ Hata</b>\n"
            if result.get("error"):
                output_text += f"<code>{result['error'][:500]}</code>"

        await update.message.reply_text(output_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Code execution error: {e}")
        await update.message.reply_text(f"Hata: {str(e)}")


async def cmd_send_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send email command"""
    if not context.args or len(context.args) < 3:
        await update.message.reply_text(
            "E-posta gönder\n"
            "──────────────\n"
            "Kullanım: /email <alıcı> <konu> <mesaj>\n"
            "Örnek: /email test@example.com 'Merhaba' 'İçerik'"
        )
        return

    try:
        to = context.args[0]
        subject = context.args[1]
        body = " ".join(context.args[2:])

        from tools.email_tools import send_email

        await update.message.reply_text(" E-posta gönderiliyor...")

        result = await send_email(to, subject, body)

        if result.get("success"):
            await update.message.reply_text(f"✓ E-posta başarıyla gönderildi: {to}")
        else:
            await update.message.reply_text(
                f"✗ E-posta gönderilemedi:\n{result.get('error')}"
            )

    except Exception as e:
        logger.error(f"Email send error: {e}")
        await update.message.reply_text(f"Hata: {str(e)}")


async def cmd_check_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check incoming emails"""
    try:
        from tools.email_tools import get_emails, get_unread_emails

        await update.message.reply_text(" E-postalar kontrol ediliyor...")

        # Get unread count
        unread = await get_unread_emails()
        unread_count = unread.get("unread_count", 0) if unread.get("success") else "?"

        # Get recent emails
        emails = await get_emails(limit=5)

        if not emails.get("success"):
            await update.message.reply_text(f"✗ E-postalar yüklenemedi")
            return

        message = f" <b>E-Postalarınız</b>\n"
        message += f"Okunmamış: <b>{unread_count}</b>\n\n"

        for email in emails.get("emails", [])[:5]:
            message += f"<b>Gönderen:</b> {email['from']}\n"
            message += f"<b>Konu:</b> {email['subject']}\n"
            message += f"<b>Tarih:</b> {email['date']}\n"
            message += "─────────\n"

        await update.message.reply_text(message, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Email check error: {e}")
        await update.message.reply_text(f"✗ Hata: {str(e)}")


async def cmd_parallel_operations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available parallel operations"""
    message = (
        "<b>⚡ Paralel İşlemler</b>\n"
        "──────────────────\n\n"
        "Bot birden fazla işlemi paralel olarak çalıştırabiliyor:\n\n"
        "• <b>Dosya işlemleri:</b> Çoklu dosyayı eşzamanlı işle\n"
        "• <b>Belge işlemleri:</b> Birden fazla belgeyi eşzamanlı analiz et\n"
        "• <b>Web araştırması:</b> Birden fazla kaynağı eşzamanlı kontrol et\n"
        "• <b>Kod çalıştırma:</b> Birden fazla script'i sırayla çalıştır\n\n"
        "Örnek:\n"
        '/cmd dosya1.txt dosya2.txt dosya3.txt "işlem"'
    )

    await update.message.reply_text(message, parse_mode="HTML")


async def cmd_streaming_operations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show streaming operation status"""
    try:
        from core.advanced_features import get_streaming_processor

        processor = get_streaming_processor()
        streams = processor.get_streams()

        if not streams:
            await update.message.reply_text("Aktif streaming işlemi yok")
            return

        message = "<b> Aktif Streaming İşlemleri</b>\n──────────────────\n\n"

        for req_id, stream in streams.items():
            progress = (len(stream.content) / max(1, len(stream.content) + 100)) * 100
            message += f"<b>{req_id}</b>\n"
            message += f"İlerleme: {progress:.1f}%\n"
            message += f"Veri: {len(stream.content)} byte\n"
            message += "─────────\n"

        await update.message.reply_text(message, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Streaming status error: {e}")
        await update.message.reply_text(f"Hata: {str(e)}")


async def cmd_suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get proactive suggestions"""
    try:
        from core.advanced_features import get_suggestion_engine
        from core.memory import get_memory

        suggestion_engine = get_suggestion_engine()
        memory = get_memory()

        user_id = update.effective_user.id

        # Get recent commands
        recent_convs = memory.get_recent_conversations(user_id, limit=20)
        recent_commands = [c[1] for c in recent_convs] if recent_convs else []

        # Get user preferences
        prefs = memory.get_user_preferences(user_id) or {}

        # Get suggestions
        suggestions = suggestion_engine.analyze_user_behavior(recent_commands, prefs)

        if not suggestions:
            await update.message.reply_text("Şu anda öneri yok")
            return

        message = "<b> Önerilenler</b>\n──────────────\n\n"

        for i, suggestion in enumerate(suggestions[:5], 1):
            message += f"{i}. <b>{suggestion.task}</b>\n"
            message += f"   {suggestion.description}\n"
            message += f"   Güven: {suggestion.confidence * 100:.0f}%\n"
            message += f"   Sebep: {suggestion.reason}\n\n"

        await update.message.reply_text(message, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Suggestions error: {e}")
        await update.message.reply_text(f"Hata: {str(e)}")


async def cmd_anomalies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detected anomalies"""
    try:
        from core.advanced_features import get_anomaly_detector

        detector = get_anomaly_detector()
        anomalies = detector.get_anomalies(limit=5)

        if not anomalies:
            await update.message.reply_text("Anormal davranış algılanmadı")
            return

        message = "<b> Anormal Davranışlar</b>\n────────────────────\n\n"

        for anomaly in anomalies:
            message += f"<b>Tür:</b> {anomaly['type']}\n"
            message += f"<b>Zaman:</b> {str(anomaly['timestamp'])[:16]}\n"
            if "command" in anomaly:
                message += f"<b>Komut:</b> {anomaly['command'][:50]}\n"
            message += "─────────\n"

        await update.message.reply_text(message, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Anomaly check error: {e}")
        await update.message.reply_text(f"Hata: {str(e)}")


async def cmd_context_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show enriched context information"""
    try:
        from core.advanced_features import get_context_enricher
        from core.memory import get_memory

        enricher = get_context_enricher()
        memory = get_memory()

        user_id = update.effective_user.id
        recent_convs = memory.get_recent_conversations(user_id, limit=5)
        recent_commands = [c[1] for c in recent_convs] if recent_convs else []

        prefs = memory.get_user_preferences(user_id) or {}

        # Get enriched context
        context_data = await enricher.enrich_context(
            "Kontekst sorgusu",
            recent_commands,
            prefs
        )

        message = "<b> Kontekst Bilgisi</b>\n──────────────────\n\n"
        message += f"<b>Kullanıcı Profili:</b>\n"
        profile = context_data.get("user_profile", {})
        message += f"  Dil: {profile.get('language')}\n"
        message += f"  Araştırma Sıklığı: {profile.get('research_frequency')}\n\n"

        message += f"<b>Zamansal Bağlam:</b>\n"
        temporal = context_data.get("temporal_context", {})
        message += f"  Çalışma Saatleri: {'Evet' if temporal.get('is_working_hours') else 'Hayır'}\n"
        message += f"  Hafta Sonu: {'Evet' if temporal.get('is_weekend') else 'Hayır'}\n\n"

        message += f"<b>Son Komutlar:</b>\n"
        for cmd in recent_commands[-3:]:
            message += f"  • {cmd[:50]}\n"

        await update.message.reply_text(message, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Context info error: {e}")
        await update.message.reply_text(f"Hata: {str(e)}")


async def cmd_performance_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyze system performance"""
    try:
        from core.monitoring import get_monitoring

        monitoring = get_monitoring()
        dashboard = monitoring.get_dashboard()

        message = "<b> Performans Analizi</b>\n───────────────────\n\n"

        ops = dashboard.get("operations", {})
        message += "<b>İşlem Istatistikleri:</b>\n"
        message += f"  Toplam: {ops.get('total_operations', 0)}\n"
        message += f"  Ort. Süre: {ops.get('avg_duration_ms', 0):.0f}ms\n"
        message += f"  Min Süre: {ops.get('min_duration_ms', 0):.0f}ms\n"
        message += f"  Max Süre: {ops.get('max_duration_ms', 0):.0f}ms\n\n"

        message += "<b>Hata Analizi:</b>\n"
        message += f"  Başarı Oranı: {ops.get('success_rate', '0%')}\n"
        message += f"  Son 5 dakika hatası: {dashboard.get('recent_errors', 0)}\n\n"

        message += "<b>En İyi Araçlar:</b>\n"
        tools = dashboard.get("tool_stats", {})
        for tool, stats in list(tools.items())[:3]:
            message += f"  • {tool}: %{stats.get('success_rate', 0)}\n"

        await update.message.reply_text(message, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Performance analysis error: {e}")
        await update.message.reply_text(f"Hata: {str(e)}")


# Extension commands mapping
EXTENSION_COMMANDS = {
    "code": cmd_execute_code,
    "email": cmd_send_email,
    "emails": cmd_check_emails,
    "parallel": cmd_parallel_operations,
    "streaming": cmd_streaming_operations,
    "suggestions": cmd_suggestions,
    "anomalies": cmd_anomalies,
    "context": cmd_context_info,
    "perf": cmd_performance_analysis,
}


def get_extension_handlers() -> Dict[str, callable]:
    """Get all extension command handlers"""
    return EXTENSION_COMMANDS.copy()
