from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from core.agent import Agent
from config.settings import HOME_DIR, LOGS_DIR
from security.rate_limiter import rate_limiter
from elyan.approval.legacy_adapter import get_approval_manager
from security.validator import sanitize_input, validate_input
from core.error_handler import ErrorHandler
from core.tool_health import get_tool_health_manager, ToolStatus
from core.briefing_manager import get_briefing_manager
from config.settings_manager import SettingsPanel
from utils.logger import get_logger
from pathlib import Path
from typing import Any, Optional
import asyncio
import os
import json
import logging
import re
import time

logger = get_logger("telegram")

agent: Agent = None
telegram_app: Optional[Application] = None
pending_approvals = {}  # request_id -> {"user_id": int, "future": asyncio.Future, "loop": asyncio.AbstractEventLoop}
pending_requests = {}  # user_id -> set[request_id] for cancellation tracking


def _track_pending_request(user_id: int, request_id: str):
    """Track pending approval request per user (supports multiple pending IDs)."""
    if not user_id or not request_id:
        return
    reqs = pending_requests.setdefault(user_id, set())
    reqs.add(request_id)


def _untrack_pending_request(user_id: int, request_id: str):
    """Remove a tracked request id; cleanup empty user bucket."""
    reqs = pending_requests.get(user_id)
    if not reqs:
        return
    reqs.discard(request_id)
    if not reqs:
        pending_requests.pop(user_id, None)


def _get_user_pending_request_ids(user_id: int) -> set[str]:
    """
    Return all pending request IDs for a user.
    Includes tracked IDs and orphaned entries still present in pending_approvals.
    """
    tracked = set(pending_requests.get(user_id, set()))
    orphaned = {
        rid for rid, req in pending_approvals.items()
        if int(req.get("user_id", 0) or 0) == user_id
    }
    return tracked.union(orphaned)


def _resolve_pending_request(request_id: str, approved: bool) -> bool:
    """Resolve pending approval future in a loop-safe way.

    BUG-FUNC-002: call_soon_threadsafe must only be used from OUTSIDE the
    running loop. If we are already inside the loop (async handler), call
    future.set_result() directly so the awaiting coroutine is resumed in the
    same scheduler tick rather than being re-queued via the thread-safe pipe.
    """
    pending = pending_approvals.get(request_id)
    if not pending:
        logger.debug(f"_resolve_pending_request: no pending entry for {request_id}")
        return False

    future = pending.get("future")
    loop = pending.get("loop")
    if not future or future.done():
        logger.debug(f"_resolve_pending_request: future already done for {request_id}")
        return False

    try:
        # Detect whether the caller is running inside the same event loop.
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None and running_loop is loop:
            # Already inside the loop — set directly (no threadsafe bridge needed).
            future.set_result(bool(approved))
        elif loop and loop.is_running():
            # Called from a different thread while the loop is running.
            loop.call_soon_threadsafe(future.set_result, bool(approved))
        else:
            future.set_result(bool(approved))

        logger.info(f"Approval resolved: request_id={request_id} approved={approved}")
        return True
    except Exception as exc:
        logger.error(f"Failed to resolve approval request {request_id}: {exc}")
        return False


def _parse_allowed_ids(raw_ids: Any) -> list[int]:
    """Normalize allow-list values from settings/env to integer user IDs."""
    normalized: list[int] = []
    if isinstance(raw_ids, str):
        raw_ids = [x.strip() for x in raw_ids.split(",") if x.strip()]
    if not isinstance(raw_ids, list):
        return normalized
    for item in raw_ids:
        try:
            user_id = int(str(item).strip())
            if user_id > 0 and user_id not in normalized:
                normalized.append(user_id)
        except Exception:
            continue
    return normalized


def _get_allowed_user_ids() -> list[int]:
    """Read allow-list dynamically so runtime config changes take effect immediately."""
    try:
        settings_ids = _parse_allowed_ids(SettingsPanel().get("allowed_user_ids", []))
        if settings_ids:
            return settings_ids
    except Exception:
        pass
    return _parse_allowed_ids(os.getenv("ALLOWED_USER_IDS", ""))


def _allow_public_telegram() -> bool:
    """Emergency compatibility switch. Secure default remains deny-by-default."""
    raw = str(os.getenv("ELYAN_TELEGRAM_ALLOW_PUBLIC", "") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    try:
        return bool(SettingsPanel().get("telegram_allow_public", False))
    except Exception:
        return False


def _get_save_dir(setting_key: str, default_relative: str) -> Path:
    """Resolve Telegram save directories from settings with safe fallback."""
    try:
        settings = SettingsPanel()
        raw_path = str(settings.get(setting_key, default_relative) or default_relative).strip()
    except Exception:
        raw_path = default_relative

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (HOME_DIR / path).resolve()
    return path


class StatusMessageManager:
    """Manages a single status message that updates in real-time"""
    def __init__(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.update = update
        self.context = context
        self.message = None
        self.last_text = ""

    async def update_status(self, text: str):
        if not text or text == self.last_text:
            return
            
        self.last_text = text
        try:
            if not self.message:
                self.message = await self.update.message.reply_text(text, parse_mode=None)
            else:
                await self.context.bot.edit_message_text(
                    chat_id=self.update.effective_chat.id,
                    message_id=self.message.message_id,
                    text=text,
                    parse_mode=None
                )
        except Exception as e:
            logger.debug(f"Status update failed (likely same content or message deleted): {e}")
            # Fallback if edit fails
            if "Message is not modified" not in str(e):
                self.message = await self.update.message.reply_text(text, parse_mode=None)

def init_handlers(agent_instance: Agent):
    global agent
    agent = agent_instance

    # Setup notification delivery callback
    from core.smart_notifications import get_smart_notifications
    notif_system = get_smart_notifications()

    async def telegram_notification_callback(notification):
        """Deliver notifications via Telegram"""
        try:
            # This would need the bot application instance and user chat_id
            # For now, just log it. In production, store user chat_ids and send messages
            logger.info(f"Notification: [{notification.priority.value}] {notification.title}")
        except Exception as e:
            logger.error(f"Telegram notification delivery error: {e}")

    notif_system.register_delivery_callback(telegram_notification_callback)

async def check_user(update: Update) -> bool:
    async def _deny(message: str, *, show_alert: bool = True) -> None:
        try:
            query = getattr(update, "callback_query", None)
            if query is not None:
                await query.answer(message, show_alert=show_alert)
                return
        except Exception:
            pass
        try:
            target = getattr(update, "effective_message", None)
            if target is not None:
                await target.reply_text(message)
                return
        except Exception:
            pass

    allowed_user_ids = _get_allowed_user_ids()
    if not allowed_user_ids:
        if _allow_public_telegram():
            return True
        logger.warning("Telegram erisimi reddedildi: allowed_user_ids bos")
        deny_msg = "Bot erisimi kisitli. Lutfen allowed_user_ids ayarini yapilandirin."
        await _deny(deny_msg)
        return False

    user = getattr(update, "effective_user", None)
    user_id = int(getattr(user, "id", 0) or 0)
    if user_id <= 0:
        logger.warning("Telegram erisimi reddedildi: kullanici kimligi yok")
        await _deny("Kullanici kimligi dogrulanamadi.")
        return False

    if user_id not in allowed_user_ids:
        logger.warning(f"Yetkisiz erisim: {user_id}")
        await _deny("Bu botu kullanma yetkiniz yok.")
        return False

    return True

async def approval_callback(approval_request):
    """Callback for requesting user approval of high-risk operations"""
    user_id = 0
    try:
        if telegram_app is None:
            return None

        user_id = int(getattr(approval_request, "user_id", 0) or 0)
        if user_id <= 0:
            # Non-Telegram request (desktop UI/local) - let fallback callback handle it.
            return None

        allowed_user_ids = _get_allowed_user_ids()
        if allowed_user_ids and user_id not in allowed_user_ids:
            logger.warning(f"Unauthorized approval request blocked for user {user_id}")
            return False

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        # BUG-FUNC-002: Ensure no stale pending approvals remain for this user.
        for previous_req_id in _get_user_pending_request_ids(user_id):
            if previous_req_id == approval_request.id:
                continue
            resolved = _resolve_pending_request(previous_req_id, False)
            pending_approvals.pop(previous_req_id, None)
            _untrack_pending_request(user_id, previous_req_id)
            logger.warning(
                f"Cleared stale pending approval: user={user_id} request_id={previous_req_id} resolved={resolved}"
            )

        pending_approvals[approval_request.id] = {
            "user_id": user_id,
            "future": future,
            "loop": loop,
        }
        _track_pending_request(user_id, approval_request.id)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Onayla", callback_data=f"approval:{approval_request.id}:approve"),
            InlineKeyboardButton("Reddet", callback_data=f"approval:{approval_request.id}:deny"),
        ]])

        message = (
            "Onay gerekli\n\n"
            f"İşlem: {approval_request.operation}\n"
            f"Açıklama: {approval_request.description}\n"
            f"Risk: {approval_request.risk_level.value.upper()}\n\n"
            "Devam etmek istiyor musunuz?"
        )

        await telegram_app.bot.send_message(
            chat_id=user_id,
            text=message,
            reply_markup=keyboard,
            parse_mode=None,
        )
        logger.info(f"Approval request sent via Telegram: request_id={approval_request.id} user_id={user_id} op={approval_request.operation}")

        approved = await future
        logger.info(f"Approval resolved via Telegram: request_id={approval_request.id} approved={bool(approved)}")
        return bool(approved)

    except Exception as e:
        logger.error(f"Approval callback error: {e}")
        return False
    finally:
        req_id = getattr(approval_request, "id", "")
        if req_id:
            pending_approvals.pop(req_id, None)
        if user_id and req_id:
            _untrack_pending_request(user_id, req_id)


async def approval_query_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle approval decision button clicks."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    parts = data.split(":")
    if len(parts) != 3:
        await query.edit_message_text("Geçersiz onay isteği.")
        return

    _, request_id, decision = parts
    pending = pending_approvals.get(request_id)
    if not pending:
        await query.edit_message_text("Bu onay isteği artık geçerli değil.")
        return

    expected_user = int(pending.get("user_id", 0) or 0)
    actor_id = int(query.from_user.id) if query.from_user else 0
    if expected_user and actor_id != expected_user:
        await query.answer("Bu onay isteği size ait değil.", show_alert=True)
        return

    approved = decision == "approve"
    _resolve_pending_request(request_id, approved)
    logger.info(f"Approval button clicked: request_id={request_id} actor_id={actor_id} approved={approved}")

    pending_approvals.pop(request_id, None)
    if expected_user:
        _untrack_pending_request(expected_user, request_id)

    if approved:
        await query.edit_message_text("Onay alındı. İşlem devam ediyor.")
    else:
        await query.edit_message_text("İşlem reddedildi.")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update):
        return

    welcome = (
        "Merhaba! Ben senin bilgisayar asistaninim.\n\n"
        "Yapabileceklerim:\n"
        "  - Dosya listeleme, okuma, yazma, tasima, silme\n"
        "  - Belge olusturma ve duzenleme (Word, Excel, PDF)\n"
        "  - Arastirma yapip rapor olusturma\n"
        "  - Not alma ve yonetme\n"
        "  - Gorev planlama\n"
        "  - Ekran goruntusu alma ve gonderme\n"
        "  - Gorselleri kaydetme\n"
        "  - Sistem bilgisi\n"
        "  - Uygulama kontrolu\n\n"
        "Dogal dilde konusabilirsin:\n"
        "  \"Masaustunde ne var?\"\n"
        "  \"rapor.pdf oku ve ozetle\"\n"
        "  \"yapay zeka hakkinda arastirma yap\"\n"
        "  \"ekran goruntusu al\"\n\n"
        "Komutlar: /help /status /stats /reset /screenshot /myid"
    )
    await update.message.reply_text(welcome)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update):
        return

    help_text = (
        "Kullanim Rehberi\n"
        "-----------------\n\n"
        "Dosya Islemleri:\n"
        "  - \"Masaustunde ne var?\"\n"
        "  - \"test.txt dosyasini oku\"\n"
        "  - \"dosyayi Documents'a tasi\"\n"
        "  - \"test.txt sil\"\n\n"
        "Belge Islemleri:\n"
        "  - \"rapor.pdf oku\"\n"
        "  - \"rapor.docx ozetle\"\n"
        "  - \"word belgesi olustur\"\n"
        "  - \"1.pdf ve 2.pdf birlestir\"\n\n"
        "Arastirma:\n"
        "  - \"yapay zeka hakkinda arastirma yap\"\n"
        "  - \"blockchain konusunu arastir\"\n\n"
        "Not Sistemi:\n"
        "  - \"not olustur: Toplanti notlari\"\n"
        "  - \"notlarimi goster\"\n\n"
        "Ekran ve Gorseller:\n"
        "  - \"ekran goruntusu al\" veya /screenshot\n"
        "  - Gorsel gonderdiginizde otomatik kaydedilir\n\n"
        "Sistem:\n"
        "  - \"sistem durumu\"\n"
        "  - \"Safari ac\"\n"
        "  - \"YouTube'a git\"\n\n"
        "Komutlar:\n"
        "  /status - Sistem durumu\n"
        "  /stats - İstatistikler\n"
        "  /dashboard - İzleme paneli\n"
        "  /health - Sistem sağlığı\n"
        "  /cancel - İşlemi iptal et\n"
        "  /screenshot - Ekran görüntüsü\n"
        "  /myid - Telegram kullanıcı/chat ID göster\n"
        "  /reset - Sistemi sıfırla\n\n"
        "Akıllı Asistan:\n"
        "  /smart_insights - Davranış analizi\n"
        "  /proactive - Proaktif öneriler\n"
        "  /auto_check - Otomatikleştirme fırsatları\n\n"
        "Otomasyon & Sistem:\n"
        "  /automate - Otomasyon görevleri\n"
        "  /routine - Rutinleri listele\n"
        "  /routine_add - Saat + adımla rutin ekle\n"
        "  /routine_run - Rutin manuel çalıştır\n"
        "  /routine_on /routine_off - Rutin aktif/pasif\n"
        "  /routine_rm - Rutin sil\n"
        "  /routine_templates - Hazır template listesi\n"
        "  /routine_from - Template ile rutin oluştur\n"
        "  /health - Self-healing durumu\n\n"
        "Analytics & Bildirimler:\n"
        "  /analytics - Analytics dashboard\n"
        "  /insights - Sistem öngörüleri\n"
        "  /notifications - Bildirim yönetimi\n\n"
        "Gelişmiş Sistem:\n"
        "  /plan - Akıllı görev planlama\n"
        "  /predict - Öngörücü bakım\n"
        "  /security - Güvenlik raporu\n"
        "  /improve - Self-improvement metrikleri\n"
        "  /feedback 1-5 <yorum> - Geri bildirim"
    )
    await update.message.reply_text(help_text)

async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show Telegram identifiers needed for allow-list setup."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    allowed = _get_allowed_user_ids()
    is_allowed = user_id in allowed if allowed else True
    status = "izinli" if is_allowed else "izinli degil"

    text = (
        "Telegram Kimlik Bilgisi\n"
        f"Kullanici ID: `{user_id}`\n"
        f"Chat ID: `{chat_id}`\n"
        f"Erisim durumu: {status}\n\n"
        "Ayarlar > Telegram bolumune bu kullanici ID'yi ekleyebilirsiniz."
    )
    await update.message.reply_text(text, parse_mode=None)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update):
        return

    from tools.system_tools import get_system_info, get_battery_status
    result = await get_system_info()

    if result.get("success"):
        sys_info = result.get("system", {})
        cpu = result.get("cpu", {})
        mem = result.get("memory", {})
        disk = result.get("disk", {})
        battery = result.get("battery")

        status = (
            f"Sistem Durumu\n"
            f"{'─'*20}\n"
            f"OS: {sys_info.get('os')} {sys_info.get('os_version', '')}\n"
            f"CPU: %{cpu.get('percent')}\n"
            f"RAM: %{mem.get('percent')} ({mem.get('used_gb')}/{mem.get('total_gb')} GB)\n"
            f"Disk: %{disk.get('percent')} ({disk.get('free_gb')} GB bos)"
        )

        if battery:
            charging = "sarj oluyor" if battery.get('charging') else "sarj olmuyor"
            status += f"\nPil: %{battery.get('percent')} ({charging})"

        cb = agent.executor.circuit_breaker
        status += f"\n\nBot Durumu: {'Koruma Modu' if cb.is_open else 'Normal'}"
    else:
        status = "Sistem bilgisi alinamadi"

    await update.message.reply_text(status)

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update):
        return

    agent.executor.reset_circuit_breaker()
    await update.message.reply_text("Sistem sifirlandi")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot performans istatistiklerini goster"""
    if not await check_user(update):
        return

    stats = agent.executor.get_stats()

    cb_status = "ACIK (Koruma)" if stats.get("circuit_breaker_open") else "KAPALI (Normal)"

    stats_text = (
        f"Bot Istatistikleri\n"
        f"{'─'*25}\n\n"
        f"Gorev Ozeti:\n"
        f"  - Toplam: {stats.get('total', 0)}\n"
        f"  - Basarili: {stats.get('success', 0)}\n"
        f"  - Basarisiz: {stats.get('failed', 0)}\n"
        f"  - Basari Orani: {stats.get('success_rate', '0%')}\n\n"
        f"Performans:\n"
        f"  - Ort. Sure: {stats.get('avg_time', '0s')}\n\n"
        f"Circuit Breaker:\n"
        f"  - Durum: {cb_status}\n"
        f"  - Hata Sayisi: {stats.get('failure_count', 0)}/5"
    )

    await update.message.reply_text(stats_text)


async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sistem monitoring dashboard'unu goster"""
    if not await check_user(update):
        return

    try:
        from core.monitoring import get_monitoring
        monitoring = get_monitoring()
        dashboard = monitoring.get_dashboard()

        ops = dashboard.get("operations", {})
        dashboard_text = (
            f" Sistem Dashboard\n"
            f"{'─'*30}\n\n"
            f"İşlemler:\n"
            f"  Toplam: {ops.get('total_operations', 0)}\n"
            f"  Başarılı: {ops.get('successful', 0)}\n"
            f"  Başarısız: {ops.get('failed', 0)}\n"
            f"  Başarı Oranı: {ops.get('success_rate', '0%')}\n"
            f"  Ort. Süre: {ops.get('avg_duration_ms', '0')}ms\n"
        )

        # Tool stats
        tool_stats = dashboard.get("tool_stats", {})
        if tool_stats:
            dashboard_text += f"\nEn Çok Kullanılan Araçlar:\n"
            for tool, stats in list(tool_stats.items())[:5]:
                if stats.get('total', 0) > 0:
                    dashboard_text += f"  • {tool}: {stats.get('success_rate', '0%')} başarı\n"

        health = monitoring.get_health_status()
        dashboard_text += (
            f"\n{health['status_code']} Sistem Sağlığı: {health['status']}\n"
            f"  Son 5 dakika hata: {health['recent_errors_5min']}"
        )

        await update.message.reply_text(dashboard_text)
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        await update.message.reply_text("Dashboard bilgisi yüklenemedi")


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sistem sağlık durumunu kontrol et"""
    if not await check_user(update):
        return

    try:
        from core.monitoring import get_monitoring
        from core.tool_health import get_tool_health_manager

        monitoring = get_monitoring()
        health = monitoring.get_health_status()
        tool_health = get_tool_health_manager()
        tool_summary = tool_health.get_health_summary()

        health_text = (
            f"{health['status_code']} Sistem Sağlığı\n"
            f"{'─'*25}\n\n"
            f"Durum: {health['status']}\n"
            f"Başarı Oranı: {health['success_rate']}\n"
            f"Son Hata (5min): {health['recent_errors_5min']}\n"
            f"Toplam İşlem: {health['total_operations']}\n\n"
            f"Araçlar:\n"
            f"  Sağlıklı: {tool_summary.get('healthy', 0)}/{tool_summary.get('total_tools', 0)}\n"
            f"  Sağlık Yüzdesi: {tool_summary.get('health_percentage', 0):.1f}%"
        )

        await update.message.reply_text(health_text)
    except Exception as e:
        logger.error(f"Health check error: {e}")
        await update.message.reply_text("Sağlık kontrol başarısız")


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sistem ve cache bilgisi göster"""
    if not await check_user(update):
        return

    try:
        from core.smart_cache import get_smart_cache
        from core.semantic_memory import get_semantic_memory
        from core.fast_response import get_fast_response_system
        from core.response_cache import get_response_cache
        from core.llm_optimizer import get_llm_optimizer
        from core.quick_intent import get_quick_intent_detector

        cache = get_smart_cache()
        cache_stats = cache.get_statistics()

        semantic = await get_semantic_memory()
        conv_summary = semantic.get_context_summary(top_k=3)

        # Fast response stats
        fast_resp = get_fast_response_system()
        fast_stats = fast_resp.get_stats()

        # Response cache stats
        resp_cache = get_response_cache()
        resp_stats = resp_cache.get_stats()

        # LLM optimizer stats
        llm_opt = get_llm_optimizer()
        llm_stats = llm_opt.get_stats()

        # Quick intent stats
        quick_int = get_quick_intent_detector()
        intent_stats = quick_int.get_stats()

        info_text = (
            f"Sistem Bilgisi v18.0\n"
            f"{'─'*30}\n\n"
            f"Hızlı Yanıt:\n"
            f"  Toplam: {fast_stats['total_requests']}\n"
            f"  Hızlı: {fast_stats['fast_responses']}\n"
            f"  Oran: {fast_stats['hit_rate']}\n"
            f"  Süre: {fast_stats['avg_response_time']}\n\n"
            f"Yanıt Cache:\n"
            f"  Boyut: {resp_stats['cache_size']}/{resp_stats['max_size']}\n"
            f"  Hit: {resp_stats['hit_rate']}\n"
            f"  Fuzzy: {resp_stats['fuzzy_rate']}\n\n"
            f"LLM Optimizasyon:\n"
            f"  Toplam: {llm_stats['total_optimizations']}\n"
            f"  Token tasarruf: {llm_stats['tokens_saved']}\n\n"
            f"Intent Tespiti:\n"
            f"  Toplam: {intent_stats['total_detections']}\n"
            f"  Süre: {intent_stats['avg_detection_time']}\n\n"
            f"Smart Cache:\n"
            f"  Boyut: {cache_stats['size']}/{cache_stats['max_size']}\n"
            f"  Hit: {cache_stats['hit_rate']}\n\n"
            f"Konuşmalar:\n"
            f"  Toplam: {len(semantic.conversations)}\n"
            f"  Bugün: {len(semantic.get_recent(days=1))}"
        )

        await update.message.reply_text(info_text)
    except Exception as e:
        logger.error(f"Info error: {e}")
        await update.message.reply_text("Bilgi yüklenemedi")


async def cmd_research_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Araştırma durumunu kontrol et"""
    if not await check_user(update):
        return

    try:
        if not context.args:
            await update.message.reply_text("Kullanım: /research_status <research_id>")
            return

        research_id = context.args[0]

        from tools.research_tools.advanced_research import get_research_status

        result = get_research_status(research_id)

        if not result.get("success"):
            await update.message.reply_text(f"Araştırma bulunamadı: {research_id}")
            return

        status_text = (
            f"Araştırma Durumu\n"
            f"{'─'*30}\n\n"
            f"Durum: {result['status']}\n"
            f"İlerleme: {result['progress']}%\n"
            f"Konu: {result['topic']}\n"
            f"Derinlik: {result['depth']}\n"
            f"Kaynaklar: {result['source_count']}\n"
            f"Bulgular: {result['finding_count']}"
        )

        if result.get('summary'):
            status_text += f"\n\nÖzet: {result['summary'][:200]}..."

        await update.message.reply_text(status_text)

    except Exception as e:
        logger.error(f"Research status error: {e}")
        await update.message.reply_text("Durum kontrolü başarısız")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mevcut işlemi iptal eder"""
    user_id = update.effective_user.id
    if not await check_user(update): return

    # BUG-FUNC-002: Cancel ALL pending approval requests for this user.
    pending_ids = sorted(_get_user_pending_request_ids(user_id))
    if pending_ids:
        resolved_count = 0
        for pending_id in pending_ids:
            if _resolve_pending_request(pending_id, False):
                resolved_count += 1
            pending_approvals.pop(pending_id, None)
            _untrack_pending_request(user_id, pending_id)
            logger.info(f"cmd_cancel: user={user_id} request_id={pending_id} cancelled")

        msg = f"{len(pending_ids)} bekleyen onay iptal edildi ({resolved_count} çözümlendi)."
        await update.message.reply_text(msg)
        return

    if agent:
        # Check if agent is currently running for this user
        if hasattr(agent, 'agent_loop') and agent.agent_loop.state:
             agent.agent_loop.state.should_cancel = True
             await update.message.reply_text("🛑 İşlem iptal ediliyor...")
        else:
             await update.message.reply_text("Çalışan bir işlem bulunamadı.")
    else:
        await update.message.reply_text("Agent hazır değil.")

async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Araç sağlığı ve listesini gösterir"""
    if not await check_user(update): return

    manager = get_tool_health_manager()
    summary = manager.get_health_summary()
    
    tools = manager.get_available_tools()
    
    text = f" **Araç Durumu ({summary['total_tools']} Toplam)**\n"
    text += f" Sağlıklı: {summary['healthy']}\n"
    text += f" Sorunlu: {summary['degraded']}\n"
    text += f" Kapalı: {summary['unavailable']}\n"
    text += f" Sağlık Oranı: %{summary['health_percentage']:.1f}\n\n"
    
    text += "**Tüm Araçlar:**\n"
    for t in sorted(tools):
        status = manager.get_tool_status(t)
        icon = "" if status == ToolStatus.HEALTHY else "" if status == ToolStatus.DEGRADED else ""
        text += f"{icon} `{t}`\n"
        
    await update.message.reply_text(text, parse_mode=None)

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sistem ayarlarını gösterir (maskelenmiş)"""
    if not await check_user(update): return
    
    import config.settings as settings
    
    text = " **Sistem Ayarları**\n\n"
    
    # Masking keys
    keys_to_show = [
        "APP_NAME", "VERSION", "ENVIRONMENT", "AGENT_AUTONOMOUS",
        "TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"
    ]
    
    for key in keys_to_show:
        if hasattr(settings, key):
            val = getattr(settings, key)
            if any(secret in key for secret in ["TOKEN", "KEY", "PASSWORD", "SECRET"]):
                if val:
                    val = val[:4] + "****" + val[-4:] if len(str(val)) > 8 else "****"
                else:
                    val = "Tanımlı Değil"
            text += f"• `{key}`: {val}\n"
            
    await update.message.reply_text(text, parse_mode=None)

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Son log kayıtlarını gösterir"""
    if not await check_user(update): return
    
    log_file = LOGS_DIR / "bot.log"
    if not log_file.exists():
        await update.message.reply_text("Log dosyası bulunamadı.")
        return
        
    try:
        # Read last 20 lines
        with open(log_file, "r") as f:
            lines = f.readlines()
            last_lines = lines[-20:]
            
        content = "".join(last_lines)
        if len(content) > 4000:
            content = "..." + content[-3900:]
            
        await update.message.reply_text(f" **Son Loglar:**\n```\n{content}\n```", parse_mode=None)
    except Exception as e:
        await update.message.reply_text(f"Log okuma hatası: {e}")

async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sistem ozeti ve proaktif oneriler sunar"""
    if not await check_user(update): return
    
    await update.message.reply_text(" Brifing hazırlanıyor...")
    
    try:
        manager = get_briefing_manager()
        result = await manager.get_proactive_briefing()
        
        if result.get("success"):
            briefing = result.get("briefing")
            metrics = result.get("metrics", {})
            
            # Formatted header with metrics
            header = f" **Elyan Günlük Brifing**\n"
            header += f"━━━━━━━━━━━━━━━━━━━━\n"
            header += f" Sağlık Skoru: %{metrics.get('health_score')}\n"
            header += f" CPU: %{metrics.get('cpu')} |  MEM: %{metrics.get('mem')}\n\n"
            
            full_text = header + briefing
            await update.message.reply_text(full_text, parse_mode=None)
        else:
            await update.message.reply_text(f" Brifing oluşturulamadı: {result.get('error')}")
            
    except Exception as e:
        logger.error(f"Briefing command error: {e}")
        await update.message.reply_text(" Brifing sırasında bir hata oluştu.")


async def cmd_smart_insights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Akıllı davranış öngörüleri ve pattern analizi"""
    if not await check_user(update): return

    try:
        from core.context_intelligence import get_context_intelligence
        ci = get_context_intelligence()

        # Get insights
        insights = await ci.get_smart_insights()
        summary = ci.get_context_summary()

        text = "Akıllı Davranış Analizi\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"

        text += f"Öğrenilmiş Pattern: {summary['total_patterns']}\n"
        text += f"Zaman Bazlı: {summary['time_based_patterns']}\n"
        text += f"Sıralı Pattern: {summary['sequence_patterns']}\n"
        text += f"Yüksek Güvenli: {summary['high_confidence_patterns']}\n\n"

        if insights:
            text += "Öngörüler:\n"
            for insight in insights:
                text += f"• {insight}\n"
        else:
            text += "Henüz yeterli veri yok. Sistemi kullanmaya devam edin.\n"

        await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Smart insights error: {e}")
        await update.message.reply_text(f"Analiz hatası: {e}")


async def cmd_proactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proaktif öneriler al"""
    if not await check_user(update): return

    try:
        from core.context_intelligence import get_context_intelligence
        ci = get_context_intelligence()

        # Get proactive suggestions
        suggestions = await ci.get_proactive_suggestions(limit=5)

        if not suggestions:
            text = "Şu anda öneri yok.\n\n"
            text += "Sistemi daha fazla kullandıkça, davranış pattern'lerinizi öğreneceğim ve proaktif önerilerde bulunabileceğim."
            await update.message.reply_text(text)
            return

        text = "Proaktif Öneriler\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, sug in enumerate(suggestions, 1):
            confidence_bar = "▓" * int(sug["confidence"] * 10) + "░" * (10 - int(sug["confidence"] * 10))
            text += f"{i}. {sug['action']}\n"
            text += f"   Neden: {sug['reason']}\n"
            text += f"   Güven: [{confidence_bar}] {sug['confidence']:.0%}\n\n"

        await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Proactive suggestions error: {e}")
        await update.message.reply_text(f"Öneri hatası: {e}")


async def cmd_auto_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Otomatikleştirme fırsatlarını kontrol et"""
    if not await check_user(update): return

    try:
        from core.context_intelligence import get_context_intelligence
        ci = get_context_intelligence()

        # Check automation opportunities
        automation_candidates = []
        for pattern_key, pattern in ci.patterns.items():
            if pattern.confidence > 0.7 and pattern.frequency > 5:
                should_auto, reason = await ci.should_automate(pattern.actions[0])
                if should_auto:
                    automation_candidates.append({
                        "action": pattern.actions[0],
                        "reason": reason,
                        "confidence": pattern.confidence,
                        "frequency": pattern.frequency
                    })

        if not automation_candidates:
            text = "Otomatikleştirme fırsatı bulunamadı.\n\n"
            text += "Düzenli olarak tekrarlanan işlemler otomatik algılanacak."
            await update.message.reply_text(text)
            return

        text = "Otomatikleştirme Fırsatları\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, auto in enumerate(automation_candidates[:5], 1):
            text += f"{i}. {auto['action']}\n"
            text += f"   {auto['reason']}\n"
            text += f"   Güven: {auto['confidence']:.0%} | Sıklık: {auto['frequency']} kez\n\n"

        text += "\nBu işlemleri otomatikleştirebilirim. Zamanlanmış görev olarak ayarlayalım mı?"

        await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Auto check error: {e}")
        await update.message.reply_text(f"Kontrol hatası: {e}")


async def cmd_automate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Otomasyon görevlerini yönet"""
    if not await check_user(update): return

    try:
        from core.automation_engine import get_automation_engine
        engine = get_automation_engine()

        # Parse command arguments
        args = context.args
        if not args:
            # Show summary
            summary = engine.get_summary()
            tasks = engine.list_tasks()

            text = "Otomasyon Motoru\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"
            text += f"Toplam Görev: {summary['total_tasks']}\n"
            text += f"Aktif: {summary['enabled_tasks']}\n"
            text += f"Zamanlanmış: {summary['scheduled_tasks']}\n"
            text += f"Çalışıyor: {summary['running_tasks']}\n\n"

            if tasks:
                text += "Görevler:\n"
                for task in tasks[:10]:
                    status_icon = "" if task['enabled'] else ""
                    text += f"{status_icon} {task['name']}\n"
                    text += f"  Durum: {task['status']}\n"
                    text += f"  Son: {task['last_run'] or 'Hiç'}\n\n"
            else:
                text += "Henüz otomasyon görevi yok.\n"
                text += "Kullanım: /automate create <isim> <action>\n"

            await update.message.reply_text(text)
            return

        # Create new task
        if args[0] == "create" and len(args) >= 3:
            name = args[1]
            action = args[2]
            params = {}

            task_id = engine.create_task(
                name=name,
                action=action,
                params=params,
                trigger_type="SCHEDULED" if len(args) > 3 else "PENDING"
            )

            await update.message.reply_text(f"Otomasyon görevi oluşturuldu: {task_id}\n{name}")

    except Exception as e:
        logger.error(f"Automate command error: {e}")
        await update.message.reply_text(f"Otomasyon hatası: {e}")


async def cmd_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Advanced analytics dashboard"""
    if not await check_user(update): return

    try:
        from core.advanced_analytics import get_analytics
        analytics = get_analytics()

        dashboard = analytics.get_dashboard_data()
        summary = analytics.get_summary()

        text = "Advanced Analytics Dashboard\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"

        text += f"Toplam Metrik: {summary['total_metrics']}\n"
        text += f"Toplam Sayaç: {summary['total_counters']}\n"
        text += f"Toplam Zamanlayıcı: {summary['total_timers']}\n"
        text += f"Aktif Trend: {summary['active_trends']}\n\n"

        # Top timers
        if dashboard['timings']:
            text += "En Yavaş İşlemler:\n"
            sorted_timings = sorted(
                dashboard['timings'].items(),
                key=lambda x: x[1]['mean'],
                reverse=True
            )[:5]
            for name, stats in sorted_timings:
                text += f"  {name}: {stats['mean']:.0f}ms (p95: {stats['p95']:.0f}ms)\n"
            text += "\n"

        # Recent trends
        if dashboard['trends']:
            text += "Trendler:\n"
            for trend in dashboard['trends'][-5:]:
                direction = trend['direction']
                icon = "↗" if direction == "up" else "↘" if direction == "down" else "→"
                text += f"  {icon} {trend['metric']}: {trend['change']} ({trend['period']})\n"
            text += "\n"

        # Insights
        insights = dashboard['insights']
        if insights:
            text += "Öngörüler:\n"
            for insight in insights[:5]:
                text += f"  • {insight}\n"

        await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Analytics command error: {e}")
        await update.message.reply_text(f"Analytics hatası: {e}")


async def cmd_insights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-generated system insights"""
    if not await check_user(update): return

    try:
        from core.advanced_analytics import get_analytics
        analytics = get_analytics()

        # Analyze trends first
        analytics.analyze_trends()

        insights = analytics.generate_insights()

        if not insights:
            await update.message.reply_text("Şu anda öngörü bulunmuyor. Sistemi kullanmaya devam edin.")
            return

        text = "Sistem Öngörüleri\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, insight in enumerate(insights, 1):
            text += f"{i}. {insight}\n"

        await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Insights command error: {e}")
        await update.message.reply_text(f"Öngörü hatası: {e}")


async def cmd_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Smart notification management"""
    if not await check_user(update): return

    try:
        from core.smart_notifications import get_smart_notifications
        notif_system = get_smart_notifications()

        args = context.args

        # /notifications list
        if not args or args[0] == "list":
            summary = notif_system.get_summary()
            notifications = notif_system.get_notifications(unread_only=False, limit=10)

            text = "Bildirimler\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"

            text += f"Toplam: {summary['total_notifications']}\n"
            text += f"Okunmamış: {summary['unread_notifications']}\n"
            text += f"Sessiz Saat: {'Aktif' if summary['quiet_hours_active'] else 'Kapalı'}\n\n"

            if notifications:
                text += "Son Bildirimler:\n"
                for notif in notifications:
                    read_icon = "✓" if notif['read'] else "•"
                    priority = notif['priority']
                    text += f"{read_icon} [{priority.upper()}] {notif['title']}\n"
                    text += f"   {notif['timestamp']}\n"
            else:
                text += "Bildirim yok.\n"

            await update.message.reply_text(text)

        # /notifications unread
        elif args[0] == "unread":
            notifications = notif_system.get_notifications(unread_only=True, limit=20)

            if not notifications:
                await update.message.reply_text("Okunmamış bildirim yok.")
                return

            text = f"Okunmamış Bildirimler ({len(notifications)})\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"

            for notif in notifications:
                text += f"[{notif['priority'].upper()}] {notif['title']}\n"
                text += f"{notif['message']}\n"
                text += f"{notif['timestamp']}\n\n"

            await update.message.reply_text(text)

        # /notifications clear
        elif args[0] == "clear":
            # Mark all as read
            for notif in notif_system.notifications:
                notif.read = True
            await update.message.reply_text("Tüm bildirimler okundu olarak işaretlendi.")

        else:
            await update.message.reply_text(
                "Kullanım:\n"
                "/notifications list - Bildirimleri listele\n"
                "/notifications unread - Okunmamışları göster\n"
                "/notifications clear - Tümünü okundu işaretle"
            )

    except Exception as e:
        logger.error(f"Notifications command error: {e}")
        await update.message.reply_text(f"Bildirim hatası: {e}")


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Intelligent task planning"""
    if not await check_user(update): return

    try:
        from core.intelligent_planner import get_intelligent_planner
        planner = get_intelligent_planner()

        args = context.args

        # /plan status
        if args and args[0] == "status":
            if len(args) < 2:
                await update.message.reply_text("Kullanım: /plan status <plan_id>")
                return

            plan_id = args[1]
            status = planner.get_plan_status(plan_id)

            if not status:
                await update.message.reply_text(f"Plan bulunamadı: {plan_id}")
                return

            text = f"Plan Durumu: {plan_id}\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"
            text += f"Açıklama: {status['description']}\n"
            text += f"Toplam Task: {status['total_tasks']}\n"
            text += f"Tamamlanan: {status['completed']}\n"
            text += f"Başarısız: {status['failed']}\n"
            text += f"Çalışan: {status['running']}\n"
            text += f"Süre: {status['duration']:.2f}s\n"
            text += f"Durum: {'Başarılı' if status['success'] else 'Devam Ediyor'}\n"

            await update.message.reply_text(text)

        # /plan list
        elif args and args[0] == "list":
            summary = planner.get_summary()

            text = "Plan Özeti\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"
            text += f"Aktif Plan: {summary['active_plans']}\n"
            text += f"Tamamlanan Plan: {summary['completed_plans']}\n"
            text += f"Toplam Task: {summary['total_tasks_executed']}\n"
            text += f"Ortalama Süre: {summary['average_plan_duration']:.2f}s\n"

            await update.message.reply_text(text)

        else:
            await update.message.reply_text(
                "Kullanım:\n"
                "/plan status <plan_id> - Plan durumunu göster\n"
                "/plan list - Tüm planları listele"
            )

    except Exception as e:
        logger.error(f"Plan command error: {e}")
        await update.message.reply_text(f"Plan hatası: {e}")


async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Predictive maintenance predictions"""
    if not await check_user(update): return

    try:
        from core.predictive_maintenance import get_predictive_maintenance
        pm = get_predictive_maintenance()

        args = context.args

        # /predict trends
        if args and args[0] == "trends":
            trends = pm.get_resource_trends()

            if "error" in trends:
                await update.message.reply_text(trends["error"])
                return

            text = "Kaynak Trendleri\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"

            for resource, data in trends.items():
                text += f"{resource.upper()}:\n"
                text += f"  Şu An: {data['current']:.1f}%\n"
                text += f"  Ortalama: {data['avg']:.1f}%\n"
                if 'max' in data:
                    text += f"  Maks: {data['max']:.1f}%\n"
                trend_icon = "↗" if data['trend'] > 0 else "↘" if data['trend'] < 0 else "→"
                text += f"  Trend: {trend_icon} {data['trend']:+.2f}\n\n"

            await update.message.reply_text(text)

        # /predict list (default)
        else:
            predictions = pm.get_predictions()

            if not predictions:
                summary = pm.get_summary()
                text = "Tahmin Özeti\n"
                text += "━━━━━━━━━━━━━━━━━━━━\n\n"
                text += f"Monitoring: {'Aktif' if summary['monitoring_active'] else 'Kapalı'}\n"
                text += f"Toplanan Metrik: {summary['metrics_collected']}\n"
                text += f"Aktif Tahmin: {summary['active_predictions']}\n\n"
                text += "Şu anda sorun öngörülmüyor."
                await update.message.reply_text(text)
                return

            text = "Sistem Tahminleri\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"

            for pred in predictions:
                severity_icon = "" if pred['severity'] == 'critical' else "" if pred['severity'] == 'warning' else ""
                text += f"{severity_icon} {pred['description']}\n"
                text += f"   Zaman: {pred['time_until']//60}dk sonra\n"
                text += f"   Güven: {pred['confidence']}\n"
                text += f"   Öneri: {pred['recommendation']}\n\n"

            await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Predict command error: {e}")
        await update.message.reply_text(f"Tahmin hatası: {e}")


async def cmd_security(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Security report"""
    if not await check_user(update): return

    try:
        from core.advanced_security import get_advanced_security
        security = get_advanced_security()

        user_id = str(update.effective_user.id)
        report = security.get_security_report(user_id)

        text = "Güvenlik Raporu\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"

        text += f"Toplam Olay: {report['total_events']}\n"
        text += f"Engellenen İşlem: {report['blocked_count']}\n\n"

        # Threat levels
        if report['threat_levels']:
            text += "Tehdit Seviyeleri:\n"
            for level, count in report['threat_levels'].items():
                text += f"  {level}: {count}\n"
            text += "\n"

        # Event types
        if report['event_types']:
            text += "Olay Tipleri:\n"
            for event_type, count in sorted(report['event_types'].items(), key=lambda x: x[1], reverse=True)[:5]:
                text += f"  {event_type}: {count}\n"
            text += "\n"

        # Critical events
        if report['critical_events']:
            text += f"Kritik Olaylar (Son {len(report['critical_events'])}):\n"
            for event in report['critical_events'][-3:]:
                text += f"  • {event['description']}\n"

        await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Security command error: {e}")
        await update.message.reply_text(f"Güvenlik raporu hatası: {e}")


async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect user feedback for continuous improvement."""
    if not await check_user(update):
        return

    try:
        args = context.args or []
        if not args:
            await update.message.reply_text("Kullanım: /feedback 1-5 <yorum>")
            return

        rating_text = args[0].strip()
        if not rating_text.isdigit():
            await update.message.reply_text("Puan 1-5 arası sayı olmalı. Örnek: /feedback 4 hızlıydı")
            return

        rating = int(rating_text)
        if rating < 1 or rating > 5:
            await update.message.reply_text("Puan 1-5 arası olmalı.")
            return

        feedback_text = " ".join(args[1:]).strip() if len(args) > 1 else None
        from core.self_improvement import get_self_improvement
        improver = get_self_improvement()
        improver.add_feedback(
            user_id=str(update.effective_user.id),
            interaction_id=f"tg_{update.effective_user.id}_{int(time.time())}",
            rating=rating,
            feedback_text=feedback_text,
        )
        await update.message.reply_text("Geri bildirim alındı. Teşekkürler.")
    except Exception as e:
        logger.error(f"Feedback command error: {e}")
        await update.message.reply_text(f"Geri bildirim kaydedilemedi: {e}")


async def cmd_improve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Self-improvement metrics and recommendations"""
    if not await check_user(update): return

    try:
        from core.self_improvement import get_self_improvement
        improver = get_self_improvement()

        args = context.args

        # /improve recommendations
        if args and args[0] == "recommendations":
            recommendations = improver.get_improvement_recommendations()

            if not recommendations:
                await update.message.reply_text("Şu anda öneri yok. Sistem iyi çalışıyor!")
                return

            text = "İyileştirme Önerileri\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"

            for i, rec in enumerate(recommendations, 1):
                text += f"{i}. {rec}\n\n"

            await update.message.reply_text(text)

        # /improve trends
        elif args and args[0] == "trends":
            trends = improver.analyze_performance_trends()

            if not trends:
                await update.message.reply_text("Henüz yeterli veri yok.")
                return

            text = "Performans Trendleri\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"

            for metric, data in list(trends.items())[:10]:
                trend_icon = "↗" if data['trend'] == 'improving' else "→" if data['trend'] == 'stable' else "↘"
                text += f"{trend_icon} {metric}\n"
                text += f"   İyileşme: {data['improvement_percent']:+.1f}%\n"
                text += f"   Eski: {data['old_avg']:.0f}ms\n"
                text += f"   Yeni: {data['new_avg']:.0f}ms\n\n"

            await update.message.reply_text(text)

        # /improve summary (default)
        else:
            summary = improver.get_summary()

            text = "Self-Improvement Özeti\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"

            text += f"Toplam İşlem: {summary['total_interactions']}\n"
            text += f"Başarı Oranı: {summary['overall_success_rate']}\n"
            text += f"Optimizasyon Kuralı: {summary['optimization_rules']}\n"
            text += f"İzlenen Tool: {summary['tracked_tools']}\n"
            text += f"Feedback: {summary['feedback_entries']}\n"
            text += f"Ortalama Puan: {summary['average_rating']}\n"
            text += f"Öğrenilen Hata Pattern: {summary['error_patterns_learned']}\n"

            await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Improve command error: {e}")
        await update.message.reply_text(f"İyileştirme hatası: {e}")


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sistem sağlık raporu ve self-healing durumu"""
    if not await check_user(update): return

    try:
        from core.self_healing import get_self_healing
        healer = get_self_healing()

        report = healer.get_health_report()

        text = "Sistem Sağlık Raporu\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"

        # System health
        health = report['system_health']
        status_icon = "" if health['status'] == 'healthy' else ""
        text += f"Durum: {status_icon} {health['status'].upper()}\n\n"

        text += f"Bellek: {health['memory_percent']:.1f}%\n"
        text += f"CPU: {health['cpu_percent']:.1f}%\n"
        text += f"Disk: {health['disk_percent']:.1f}%\n\n"

        # Auto-fix stats
        fix_stats = report['auto_fix_stats']
        text += f"Otomatik Düzeltme:\n"
        text += f"  Toplam: {fix_stats['total_fixes']}\n"
        text += f"  Başarılı: {fix_stats['successful_fixes']}\n"
        text += f"  Başarı Oranı: {fix_stats['success_rate']}\n\n"

        # Recent issues
        issues = report['recent_issues']
        if issues:
            text += f"Son Sorunlar ({len(issues)}):\n"
            for issue in issues[-5:]:
                severity_icon = "" if issue['severity'] == 'low' else "" if issue['severity'] == 'high' else ""
                text += f"{severity_icon} {issue['description']}\n"
        else:
            text += "Sorun tespit edilmedi.\n"

        await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Health command error: {e}")
        await update.message.reply_text(f"Sağlık kontrolü hatası: {e}")


async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ekran goruntusu al ve gonder"""
    if not await check_user(update):
        return

    await update.message.reply_text("Ekran goruntusu aliniyor...")

    try:
        result = await take_screenshot()

        if result.get("success"):
            screenshot_path = result.get("path")
            if screenshot_path and Path(screenshot_path).exists():
                await update.message.reply_photo(
                    photo=open(screenshot_path, 'rb'),
                    caption=f"Ekran goruntusu: {result.get('filename')}"
                )
            else:
                error_msg = "Ekran goruntusu kaydedilemedi"
                formatted_error = ErrorHandler.format_error_response(error_msg, "take_screenshot")
                await update.message.reply_text(formatted_error)
        else:
            error_msg = result.get('error', 'Bilinmiyor')
            formatted_error = ErrorHandler.format_error_response(error_msg, "take_screenshot")
            await update.message.reply_text(formatted_error)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Screenshot hatasi: {error_msg}")
        formatted_error = ErrorHandler.format_error_response(error_msg, "take_screenshot")
        await update.message.reply_text(formatted_error)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gelen gorselleri kaydet"""
    if not await check_user(update):
        return

    try:
        # En buyuk boyutlu versiyonu al
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        # Kayit dizini
        save_dir = _get_save_dir("photo_save_dir", "~/Desktop/TelegramInbox/Photos")
        save_dir.mkdir(parents=True, exist_ok=True)

        # Dosya adi
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"image_{timestamp}.jpg"
        save_path = save_dir / filename

        # Indir ve kaydet
        await file.download_to_drive(str(save_path))

        # Caption varsa not olarak kaydet
        caption = update.message.caption
        if caption:
            caption_file = save_path.with_suffix('.txt')
            caption_file.write_text(caption, encoding='utf-8')

        await update.message.reply_text(
            f" Görsel kaydedildi.\n"
            f"Boyut: {photo.width}x{photo.height}\n\n"
            f"Bu görselle ne yapmak istersiniz?",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(" Analiz Et", callback_data=f"vision:analyze:{save_path}"),
                    InlineKeyboardButton(" Metni Oku (OCR)", callback_data=f"vision:ocr:{save_path}")
                ],
                [
                    InlineKeyboardButton(" Açıkla", callback_data=f"vision:explain:{save_path}"),
                    InlineKeyboardButton(" İptal", callback_data="vision:cancel")
                ]
            ])
        )

        logger.info(f"Gorsel kaydedildi: {save_path}")

    except Exception as e:
        logger.error(f"Gorsel kaydetme hatasi: {e}")
        await update.message.reply_text(f"Gorsel kaydedilemedi: {str(e)}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gelen belgeleri kaydet"""
    if not await check_user(update):
        return

    try:
        document = update.message.document
        file = await context.bot.get_file(document.file_id)

        # Kayit dizini
        save_dir = _get_save_dir("document_save_dir", "~/Desktop/TelegramInbox/Files")
        save_dir.mkdir(parents=True, exist_ok=True)

        # Dosya adi
        filename = document.file_name or f"file_{document.file_id}"
        save_path = save_dir / filename

        # Ayni isimde varsa numara ekle
        counter = 1
        original_path = save_path
        while save_path.exists():
            stem = original_path.stem
            suffix = original_path.suffix
            save_path = save_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        # Indir ve kaydet
        await file.download_to_drive(str(save_path))

        await update.message.reply_text(
            f"Dosya kaydedildi:\n"
            f"Konum: {save_path}\n"
            f"Boyut: {document.file_size} bytes"
        )

        logger.info(f"Dosya kaydedildi: {save_path}")

    except Exception as e:
        logger.error(f"Dosya kaydetme hatasi: {e}")
        await update.message.reply_text(f"Dosya kaydedilemedi: {str(e)}")


async def vision_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vision butonlarını işle"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    if data[1] == "cancel":
        await query.edit_message_text("İşlem iptal edildi.")
        return

    action = data[1]
    image_path = ":".join(data[2:]) # Handle paths with colons if any

    prompts = {
        "analyze": "Resmi detaylıca analiz et ve önemli detayları belirt.",
        "ocr": "Resimdeki tüm metinleri çıkar ve düzenli bir şekilde yaz.",
        "explain": "Bu resimde ne olduğunu, bağlamını ve anlamını açıkla."
    }

    await query.edit_message_text(f" Görsel işleniyor ({action})...")
    
    try:
        from tools.vision_tools import analyze_image
        result = await analyze_image(image_path, prompt=prompts.get(action))
        
        if result.get("success"):
            response = f" **Vision Sonucu ({action})**\n\n{result.get('analysis')}"
            # Provider bilgisi ekle (küçük font/italic gibi görünebilir robotik dilde)
            response += f"\n\n_Kaynak: {result.get('provider')}_"
            
            if len(response) > 4000:
                await query.message.reply_text(response[:4000])
            else:
                await query.edit_message_text(response, parse_mode=None)
        else:
            await query.edit_message_text(f" Hata: {result.get('error')}")
            
    except Exception as e:
        logger.error(f"Vision callback hatası: {e}")
        await query.edit_message_text(f" Beklenmedik bir hata oluştu: {str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update):
        return

    user = update.effective_user

    # Rate limiting kontrolu
    allowed, rate_msg = await rate_limiter.is_allowed(user.id)
    if not allowed:
        await update.message.reply_text(f"Lutfen bekleyin: {rate_msg}")
        return

    raw_input = update.message.text or ""
    user_input = sanitize_input(raw_input)
    valid, validation_msg = validate_input(user_input)
    if not valid:
        await update.message.reply_text(validation_msg)
        return

    logger.info(f"[{user.id}] {user.first_name}: {user_input[:50]}...")

    await update.message.chat.send_action("typing")

    # Inline feedback capture (non-command)
    if isinstance(user_input, str):
        feedback_match = re.match(r"^\s*(feedback|puan)\s+([1-5])\s*(.*)$", user_input, flags=re.IGNORECASE)
        if feedback_match:
            rating = int(feedback_match.group(2))
            feedback_text = feedback_match.group(3).strip() or None
            from core.self_improvement import get_self_improvement
            improver = get_self_improvement()
            improver.add_feedback(
                user_id=str(user.id),
                interaction_id=f"tg_{user.id}_{int(time.time())}",
                rating=rating,
                feedback_text=feedback_text,
            )
            await update.message.reply_text("Geri bildirim alındı. Teşekkürler.")
            return

    # Set user_id for audit logging
    agent.current_user_id = user.id
    if agent.agent_loop:
        agent.agent_loop.current_user_id = user.id

    # Real-time step feedback callback
    status_manager = StatusMessageManager(update, context)

    async def notify_step(message_data: Any):
        if isinstance(message_data, dict) and message_data.get("type") == "screenshot":
            # Proactive screenshot feedback
            photo_path = message_data.get("path")
            caption = message_data.get("message", " İşlem görseli")
            if photo_path and Path(photo_path).exists():
                try:
                    await update.message.reply_photo(
                        photo=open(photo_path, 'rb'),
                        caption=caption
                    )
                except Exception as e:
                    logger.error(f"Notify screenshot error: {e}")
                    await status_manager.update_status(f" {caption}")
        else:
            # Regular text notification - Use the status manager for live updates
            text = str(message_data)
            # Add some "live" flair
            if "..." in text:
                text = f" {text}"
            else:
                text = f" {text}"
            await status_manager.update_status(text)

    try:
        response = await agent.process(user_input, notify=notify_step)

        # Check for screen recording output and send video
        video_match = re.search(r"Screen recording saved to (.+\.(?:mp4|mov|avi))", response)
        if video_match:
            video_path = video_match.group(1).strip()
            if Path(video_path).exists():
                try:
                    await update.message.reply_video(
                        video=open(video_path, 'rb'),
                        caption=" Ekran kaydı"
                    )
                except Exception as e:
                    logger.error(f"Failed to send video: {e}")

        if len(response) > 4000:
            chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(response)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Mesaj isleme hatasi: {error_msg}")
        # Use ErrorHandler for professional error message
        formatted_error = ErrorHandler.format_error_response(error_msg)
        await update.message.reply_text(formatted_error)

def setup_handlers(app: Application, agent_instance: Agent):
    global telegram_app
    telegram_app = app

    init_handlers(agent_instance)

    # Set approval callback
    approval_manager = get_approval_manager()
    previous_callback = approval_manager.approval_callback

    async def routed_approval_callback(approval_request):
        handled = await approval_callback(approval_request)
        if handled is None and previous_callback:
            return await previous_callback(approval_request)
        return bool(handled)

    approval_manager.set_approval_callback(routed_approval_callback)

    async def _enforce_command_access(update: Update) -> bool:
        if not await check_user(update):
            return False
        try:
            user_id = int(getattr(getattr(update, "effective_user", None), "id", 0) or 0)
        except Exception:
            user_id = 0
        if user_id <= 0:
            return True
        try:
            allowed, rate_msg = await rate_limiter.is_allowed(user_id)
        except Exception:
            return True
        if allowed:
            return True
        warn = f"Lutfen bekleyin: {rate_msg}"
        try:
            query = getattr(update, "callback_query", None)
            if query is not None:
                await query.answer(warn, show_alert=True)
            else:
                target = getattr(update, "effective_message", None)
                if target is not None:
                    await target.reply_text(warn)
        except Exception:
            pass
        return False

    def _secure_handler(handler_func):
        async def _wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await _enforce_command_access(update):
                return
            return await handler_func(update, context)
        return _wrapped

    # Core commands
    core_commands = [
        ("start", cmd_start),
        ("help", cmd_help),
        ("myid", cmd_myid),
        ("status", cmd_status),
        ("stats", cmd_stats),
        ("dashboard", cmd_dashboard),
        ("health", cmd_health),
        ("info", cmd_info),
        ("research_status", cmd_research_status),
        ("reset", cmd_reset),
        ("cancel", cmd_cancel),
        ("screenshot", cmd_screenshot),
        ("tools", cmd_tools),
        ("config", cmd_config),
        ("logs", cmd_logs),
        ("briefing", cmd_briefing),
    ]
    for command, handler in core_commands:
        app.add_handler(CommandHandler(command, _secure_handler(handler)))

    # Context Intelligence & Proactive AI commands
    app.add_handler(CommandHandler("smart_insights", _secure_handler(cmd_smart_insights)))
    app.add_handler(CommandHandler("proactive", _secure_handler(cmd_proactive)))
    app.add_handler(CommandHandler("auto_check", _secure_handler(cmd_auto_check)))

    # Automation & Self-Healing commands
    app.add_handler(CommandHandler("automate", _secure_handler(cmd_automate)))

    # Analytics & Notifications commands
    app.add_handler(CommandHandler("analytics", _secure_handler(cmd_analytics)))
    app.add_handler(CommandHandler("insights", _secure_handler(cmd_insights)))
    app.add_handler(CommandHandler("notifications", _secure_handler(cmd_notifications)))

    # Advanced System commands
    app.add_handler(CommandHandler("plan", _secure_handler(cmd_plan)))
    app.add_handler(CommandHandler("predict", _secure_handler(cmd_predict)))
    app.add_handler(CommandHandler("security", _secure_handler(cmd_security)))
    app.add_handler(CommandHandler("feedback", _secure_handler(cmd_feedback)))
    app.add_handler(CommandHandler("improve", _secure_handler(cmd_improve)))
    
    # Phase 12: Proactive Intelligence Commands
    try:
        from .telegram_proactive_commands import (
            cmd_schedule, cmd_schedule_briefing, cmd_trigger_briefing,
            cmd_alerts, cmd_check_disk
        )
        
        app.add_handler(CommandHandler("schedule", _secure_handler(cmd_schedule)))
        app.add_handler(CommandHandler("schedule_briefing", _secure_handler(cmd_schedule_briefing)))
        app.add_handler(CommandHandler("trigger_briefing", _secure_handler(cmd_trigger_briefing)))
        app.add_handler(CommandHandler("alerts", _secure_handler(cmd_alerts)))
        app.add_handler(CommandHandler("check_disk", _secure_handler(cmd_check_disk)))
        
        logger.info("Proactive commands registered (schedule, briefing, alerts)")
    except ImportError as e:
        logger.warning(f"Proactive commands not available: {e}")

    # Routine automation commands
    try:
        from .telegram_routines_commands import (
            cmd_routine,
            cmd_routine_add,
            cmd_routine_run,
            cmd_routine_rm,
            cmd_routine_on,
            cmd_routine_off,
            cmd_routine_templates,
            cmd_routine_from,
        )
        app.add_handler(CommandHandler("routine", _secure_handler(cmd_routine)))
        app.add_handler(CommandHandler("routine_add", _secure_handler(cmd_routine_add)))
        app.add_handler(CommandHandler("routine_run", _secure_handler(cmd_routine_run)))
        app.add_handler(CommandHandler("routine_rm", _secure_handler(cmd_routine_rm)))
        app.add_handler(CommandHandler("routine_on", _secure_handler(cmd_routine_on)))
        app.add_handler(CommandHandler("routine_off", _secure_handler(cmd_routine_off)))
        app.add_handler(CommandHandler("routine_templates", _secure_handler(cmd_routine_templates)))
        app.add_handler(CommandHandler("routine_from", _secure_handler(cmd_routine_from)))
        logger.info("Routine commands registered (routine, routine_add, routine_run...)")
    except ImportError as e:
        logger.warning(f"Routine commands not available: {e}")

    # Extended commands from telegram_extensions module
    try:
        from .telegram_extensions import (
            cmd_execute_code, cmd_send_email, cmd_check_emails,
            cmd_parallel_operations, cmd_streaming_operations,
            cmd_suggestions, cmd_anomalies, cmd_context_info,
            cmd_performance_analysis
        )

        app.add_handler(CommandHandler("code", _secure_handler(cmd_execute_code)))
        app.add_handler(CommandHandler("email", _secure_handler(cmd_send_email)))
        app.add_handler(CommandHandler("emails", _secure_handler(cmd_check_emails)))
        app.add_handler(CommandHandler("parallel", _secure_handler(cmd_parallel_operations)))
        app.add_handler(CommandHandler("streaming", _secure_handler(cmd_streaming_operations)))
        app.add_handler(CommandHandler("suggestions", _secure_handler(cmd_suggestions)))
        app.add_handler(CommandHandler("anomalies", _secure_handler(cmd_anomalies)))
        app.add_handler(CommandHandler("context", _secure_handler(cmd_context_info)))
        app.add_handler(CommandHandler("perf", _secure_handler(cmd_performance_analysis)))

        logger.info("Extended commands registered (code, email, parallel, etc.)")
    except ImportError as e:
        logger.warning(f"Extended commands not available: {e}")

    # Message handlers
    app.add_handler(CallbackQueryHandler(approval_query_callback, pattern="^approval:"))
    app.add_handler(CallbackQueryHandler(_secure_handler(vision_callback), pattern="^vision:"))
    app.add_handler(MessageHandler(filters.PHOTO, _secure_handler(handle_photo)))
    app.add_handler(MessageHandler(filters.Document.ALL, _secure_handler(handle_document)))
    
    # Phase 13: Voice message handler
    try:
        from .telegram_voice_handler import handle_voice_message, cmd_voice_status
        from .telegram_voice_commands import cmd_voice_toggle
        
        app.add_handler(MessageHandler(filters.VOICE, _secure_handler(handle_voice_message)))
        app.add_handler(CommandHandler("voice_status", _secure_handler(cmd_voice_status)))
        app.add_handler(CommandHandler("voice", _secure_handler(cmd_voice_toggle)))
        
        logger.info("Voice handler registered (Phase 13.1 + 13.2)")
    except ImportError as e:
        logger.warning(f"Voice handler not available: {e}")
    
    # Phase 14: Browser automation commands
    try:
        from .telegram_browser_commands import (
            cmd_browser_open, cmd_browser_screenshot, cmd_browser_click,
            cmd_browser_type, cmd_browser_extract, cmd_browser_status,
            cmd_browser_close, cmd_scrape
        )
        
        app.add_handler(CommandHandler("browser_open", _secure_handler(cmd_browser_open)))
        app.add_handler(CommandHandler("browser_screenshot", _secure_handler(cmd_browser_screenshot)))
        app.add_handler(CommandHandler("browser_click", _secure_handler(cmd_browser_click)))
        app.add_handler(CommandHandler("browser_type", _secure_handler(cmd_browser_type)))
        app.add_handler(CommandHandler("browser_extract", _secure_handler(cmd_browser_extract)))
        app.add_handler(CommandHandler("browser_status", _secure_handler(cmd_browser_status)))
        app.add_handler(CommandHandler("browser_close", _secure_handler(cmd_browser_close)))
        app.add_handler(CommandHandler("scrape", _secure_handler(cmd_scrape)))
        
        logger.info("Browser commands registered (Phase 14)")
    except ImportError as e:
        logger.warning(f"Browser commands not available: {e}")
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Handler'lar kaydedildi ve approval callback ayarlandi")
