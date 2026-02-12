"""
Proactive Intelligence Module

This module provides autonomous capabilities for Wiqo:
- Scheduled task automation
- Morning intelligence briefings
- Smart monitoring and alerts
- Email inbox triage
"""

from .scheduler import get_scheduler, schedule_job
from .briefing import schedule_morning_briefing
from .alerts import get_alert_manager

__all__ = [
    'get_scheduler',
    'schedule_job',
    'schedule_morning_briefing',
    'get_alert_manager'
]
