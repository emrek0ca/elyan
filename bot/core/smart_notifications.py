"""
Smart Notification System
Priority-based, context-aware, intelligent notifications
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
from collections import deque

from utils.logger import get_logger

logger = get_logger("notifications")


class NotificationPriority(Enum):
    """Notification priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationCategory(Enum):
    """Notification categories"""
    SYSTEM = "system"
    TASK = "task"
    ERROR = "error"
    SUCCESS = "success"
    WARNING = "warning"
    INFO = "info"
    SUGGESTION = "suggestion"


@dataclass
class Notification:
    """Represents a notification"""
    notification_id: str
    title: str
    message: str
    priority: NotificationPriority
    category: NotificationCategory
    timestamp: float
    read: bool = False
    dismissed: bool = False
    action_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SmartNotifications:
    """
    Smart Notification System
    - Priority-based delivery
    - Context-aware timing
    - Intelligent grouping
    - User preference learning
    """

    def __init__(self):
        self.notifications: deque = deque(maxlen=100)
        self.delivery_callbacks: List[Callable] = []
        self.quiet_hours_start = 22  # 10 PM
        self.quiet_hours_end = 8  # 8 AM
        self.notification_count = 0

        # User preferences (learned over time)
        self.user_preferences = {
            "quiet_hours_enabled": True,
            "min_priority": NotificationPriority.MEDIUM,
            "categories_enabled": {cat: True for cat in NotificationCategory}
        }

        logger.info("Smart Notification System initialized")

    def register_delivery_callback(self, callback: Callable):
        """Register a callback for notification delivery"""
        self.delivery_callbacks.append(callback)

    async def send_notification(
        self,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        category: NotificationCategory = NotificationCategory.INFO,
        action_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        force: bool = False
    ) -> str:
        """Send a smart notification"""
        import uuid
        notification_id = str(uuid.uuid4())[:8]

        notification = Notification(
            notification_id=notification_id,
            title=title,
            message=message,
            priority=priority,
            category=category,
            timestamp=time.time(),
            action_url=action_url,
            metadata=metadata or {}
        )

        # Check if should deliver
        if not force and not self._should_deliver(notification):
            logger.debug(f"Notification suppressed: {title}")
            return notification_id

        # Store notification
        self.notifications.append(notification)
        self.notification_count += 1

        # Deliver via callbacks
        await self._deliver_notification(notification)

        logger.info(f"Notification sent: {title} ({priority.value})")
        return notification_id

    def _should_deliver(self, notification: Notification) -> bool:
        """Determine if notification should be delivered"""
        # Check category enabled
        if not self.user_preferences["categories_enabled"].get(notification.category, True):
            return False

        # Check minimum priority
        priority_levels = {
            NotificationPriority.LOW: 0,
            NotificationPriority.MEDIUM: 1,
            NotificationPriority.HIGH: 2,
            NotificationPriority.CRITICAL: 3
        }

        min_priority = self.user_preferences.get("min_priority", NotificationPriority.MEDIUM)
        if priority_levels[notification.priority] < priority_levels[min_priority]:
            return False

        # Check quiet hours (except critical)
        if (notification.priority != NotificationPriority.CRITICAL and
            self.user_preferences.get("quiet_hours_enabled", True)):
            hour = datetime.now().hour
            if self.quiet_hours_start <= hour or hour < self.quiet_hours_end:
                logger.debug("Quiet hours active, suppressing non-critical notification")
                return False

        return True

    async def _deliver_notification(self, notification: Notification):
        """Deliver notification via registered callbacks"""
        for callback in self.delivery_callbacks:
            try:
                await callback(notification)
            except Exception as e:
                logger.error(f"Notification delivery error: {e}")

    def mark_as_read(self, notification_id: str):
        """Mark notification as read"""
        for notif in self.notifications:
            if notif.notification_id == notification_id:
                notif.read = True
                break

    def dismiss(self, notification_id: str):
        """Dismiss a notification"""
        for notif in self.notifications:
            if notif.notification_id == notification_id:
                notif.dismissed = True
                break

    def get_unread_count(self) -> int:
        """Get count of unread notifications"""
        return sum(1 for n in self.notifications if not n.read and not n.dismissed)

    def get_notifications(
        self,
        unread_only: bool = False,
        priority: Optional[NotificationPriority] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get notifications with filters"""
        notifications = list(self.notifications)

        # Filter
        if unread_only:
            notifications = [n for n in notifications if not n.read and not n.dismissed]

        if priority:
            notifications = [n for n in notifications if n.priority == priority]

        # Sort by timestamp (newest first)
        notifications.sort(key=lambda x: x.timestamp, reverse=True)

        # Limit
        notifications = notifications[:limit]

        # Format
        return [
            {
                "id": n.notification_id,
                "title": n.title,
                "message": n.message,
                "priority": n.priority.value,
                "category": n.category.value,
                "timestamp": datetime.fromtimestamp(n.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                "read": n.read,
                "dismissed": n.dismissed,
                "action_url": n.action_url
            }
            for n in notifications
        ]

    def get_summary(self) -> Dict[str, Any]:
        """Get notification summary"""
        total = len(self.notifications)
        unread = self.get_unread_count()

        priority_counts = {
            "critical": sum(1 for n in self.notifications if n.priority == NotificationPriority.CRITICAL),
            "high": sum(1 for n in self.notifications if n.priority == NotificationPriority.HIGH),
            "medium": sum(1 for n in self.notifications if n.priority == NotificationPriority.MEDIUM),
            "low": sum(1 for n in self.notifications if n.priority == NotificationPriority.LOW)
        }

        return {
            "total_notifications": total,
            "unread_notifications": unread,
            "priority_breakdown": priority_counts,
            "quiet_hours_active": self._is_quiet_hours(),
            "total_sent": self.notification_count
        }

    def _is_quiet_hours(self) -> bool:
        """Check if currently in quiet hours"""
        if not self.user_preferences.get("quiet_hours_enabled", True):
            return False

        hour = datetime.now().hour
        return self.quiet_hours_start <= hour or hour < self.quiet_hours_end


# Global instance
_smart_notifications: Optional[SmartNotifications] = None


def get_smart_notifications() -> SmartNotifications:
    """Get or create global smart notifications instance"""
    global _smart_notifications
    if _smart_notifications is None:
        _smart_notifications = SmartNotifications()
    return _smart_notifications
