"""Channel adapters package with optional dependency-safe imports."""
from importlib import import_module
from typing import Type

from .base import BaseChannelAdapter


def _missing_dependency_adapter(class_name: str, err: Exception) -> Type[BaseChannelAdapter]:
    """Create a placeholder adapter class for missing optional dependencies."""
    class _MissingDependencyAdapter(BaseChannelAdapter):
        missing_dependency_error = str(err)

        def __init__(self, config):
            super().__init__(config)
            self._is_connected = False

        async def connect(self):
            raise RuntimeError(f"{class_name} unavailable: {err}")

        async def disconnect(self):
            self._is_connected = False

        async def send_message(self, chat_id: str, response):
            raise RuntimeError(f"{class_name} unavailable: {err}")

        def get_status(self) -> str:
            return "unavailable"

        def get_capabilities(self):
            return {}

    _MissingDependencyAdapter.__name__ = class_name
    return _MissingDependencyAdapter


def _load_adapter(module_name: str, class_name: str) -> Type[BaseChannelAdapter]:
    try:
        module = import_module(f".{module_name}", package=__name__)
        return getattr(module, class_name)
    except ModuleNotFoundError as err:
        return _missing_dependency_adapter(class_name, err)


TelegramAdapter = _load_adapter("telegram", "TelegramAdapter")
DiscordAdapter = _load_adapter("discord", "DiscordAdapter")
SlackAdapter = _load_adapter("slack", "SlackAdapter")
WhatsAppAdapter = _load_adapter("whatsapp", "WhatsAppAdapter")
WebChatAdapter = _load_adapter("webchat", "WebChatAdapter")
SignalAdapter = _load_adapter("signal_adapter", "SignalAdapter")
MatrixAdapter = _load_adapter("matrix_adapter", "MatrixAdapter")
TeamsAdapter = _load_adapter("teams_adapter", "TeamsAdapter")
GoogleChatAdapter = _load_adapter("google_chat_adapter", "GoogleChatAdapter")
IMessageAdapter = _load_adapter("imessage_adapter", "IMessageAdapter")
SmsAdapter = _load_adapter("sms_adapter", "SmsAdapter")

__all__ = [
    "BaseChannelAdapter",
    "TelegramAdapter",
    "DiscordAdapter",
    "SlackAdapter",
    "WhatsAppAdapter",
    "WebChatAdapter",
    "SignalAdapter",
    "MatrixAdapter",
    "TeamsAdapter",
    "GoogleChatAdapter",
    "IMessageAdapter",
    "SmsAdapter",
]

# Kanal tipi → sınıf eşlemesi
ADAPTER_REGISTRY = {
    "telegram": TelegramAdapter,
    "discord": DiscordAdapter,
    "slack": SlackAdapter,
    "whatsapp": WhatsAppAdapter,
    "webchat": WebChatAdapter,
    "signal": SignalAdapter,
    "matrix": MatrixAdapter,
    "teams": TeamsAdapter,
    "google_chat": GoogleChatAdapter,
    "imessage": IMessageAdapter,
    "sms": SmsAdapter,
}


def get_adapter_class(channel_type: str):
    """Kanal türüne göre adapter sınıfını döndür."""
    return ADAPTER_REGISTRY.get(channel_type)
