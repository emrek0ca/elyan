from .appearance import toggle_dark_mode, get_appearance, set_brightness, get_brightness
from .network import wifi_status, wifi_toggle, bluetooth_status, get_wifi_details, get_public_ip, scan_local_network
from .calendar_reminders import (
    get_today_events, create_event,
    get_reminders, create_reminder
)
from .spotlight import spotlight_search
from .preferences import get_system_preferences

__all__ = [
    "toggle_dark_mode", "get_appearance", "set_brightness", "get_brightness",
    "wifi_status", "wifi_toggle", "bluetooth_status",
    "get_wifi_details", "get_public_ip", "scan_local_network",
    "get_today_events", "create_event",
    "get_reminders", "create_reminder",
    "spotlight_search",
    "get_system_preferences",
]
