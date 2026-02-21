"""
Morning Briefing Scheduler

Provides scheduled morning intelligence briefing delivery.
"""

import asyncio
from datetime import datetime
from typing import Optional
from utils.logger import get_logger
from core.briefing_manager import get_briefing_manager
from .scheduler import get_scheduler

logger = get_logger("briefing_scheduler")


async def send_morning_briefing_telegram(telegram_handler=None):
    """
    Generate and send morning briefing via Telegram.
    
    This function is scheduled to run daily.
    """
    try:
        logger.info("🌅 Generating morning briefing...")
        
        # Get briefing manager
        manager = get_briefing_manager()
        briefing = await manager.get_proactive_briefing()
        
        if not briefing.get("success"):
            logger.error(f"Briefing generation failed: {briefing.get('error')}")
            return
        
        # Format message
        message = f"""**Stratejik Günlük Özet: Kurumsal Brifing**

{briefing.get('briefing', 'Veri sentezi henüz tamamlanmadı.')}

---
Sistem Durumu: {briefing.get('metrics', {}).get('health_score', 0)}/100
İşlem Kaynakları: CPU %{briefing.get('metrics', {}).get('cpu', 0):.1f} | RAM %{briefing.get('metrics', {}).get('mem', 0):.1f}

_Brifing Zamanı: {datetime.now().strftime("%H:%M")}_
"""
        
        # Send via Telegram if handler provided
        if telegram_handler:
            await telegram_handler.send_message_to_all(message)
            logger.info(" Morning briefing sent via Telegram")
        else:
            logger.warning("No Telegram handler provided, briefing not sent")
            logger.info(f"Briefing content: {message}")
        
    except Exception as e:
        logger.error(f"Morning briefing error: {e}", exc_info=True)


async def send_briefing_ui(ui_app=None):
    """
    Generate and display briefing in UI.
    """
    try:
        manager = get_briefing_manager()
        briefing = await manager.get_proactive_briefing()
        
        if briefing.get("success") and ui_app:
            # Update UI with briefing
            if hasattr(ui_app, 'show_notification'):
                ui_app.show_notification(
                    "Stratejik Özet",
                    briefing.get('briefing', '')
                )
        
    except Exception as e:
        logger.error(f"UI briefing error: {e}")


async def run_morning_briefing_task():
    """Top-level task function for APScheduler (must be pickleable)"""
    # Note: Handlers will be looked up within the functions if needed
    # or passed as simple args if we had a registry.
    # For now, we use the default (None) which logs the briefing.
    await send_morning_briefing_telegram(None)
    await send_briefing_ui(None)


def schedule_morning_briefing(
    hour: int = 8,
    minute: int = 0,
    telegram_handler=None,
    ui_app=None
):
    """
    Schedule daily morning briefing.
    """
    scheduler = get_scheduler()

    # Use the top-level function instead of a local wrapper to avoid serialization errors
    job = scheduler.schedule_daily(
        run_morning_briefing_task,
        hour=hour,
        minute=minute,
        job_id='morning_briefing'
    )

    logger.info(f"📅 Morning briefing scheduled for {hour:02d}:{minute:02d} daily")
    return job


async def trigger_briefing_now(telegram_handler=None, ui_app=None):
    """
    Manually trigger briefing immediately (for testing or on-demand).
    
    Args:
        telegram_handler: Telegram handler
        ui_app: UI application
    
    Returns:
        Briefing result
    """
    await send_morning_briefing_telegram(telegram_handler)
    await send_briefing_ui(ui_app)
