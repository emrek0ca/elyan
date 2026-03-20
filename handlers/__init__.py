from core.dependencies.autoinstall_hook import activate as _activate_autoinstall_hook

_activate_autoinstall_hook()

from .telegram_handler import setup_handlers
from .command_router import CommandRouter
