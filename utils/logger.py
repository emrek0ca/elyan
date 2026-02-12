import logging
import sys
import json
from pathlib import Path
from datetime import datetime
from config.settings import LOGS_DIR


class JSONFormatter(logging.Formatter):
    """JSON formatında structured logging"""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Extra attributes
        if hasattr(record, "user_id"):
            log_entry["user_id"] = record.user_id
        if hasattr(record, "action"):
            log_entry["action"] = record.action
        if hasattr(record, "duration"):
            log_entry["duration"] = record.duration
        if hasattr(record, "success"):
            log_entry["success"] = record.success

        # Exception bilgisi
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


class StandardFormatter(logging.Formatter):
    """Konsol için okunabilir format"""

    def __init__(self):
        super().__init__(
            '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def get_logger(name: str) -> logging.Logger:
    """Logger instance döner"""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    # Console handler (okunabilir format)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(StandardFormatter())
    logger.addHandler(console_handler)

    # File handler (okunabilir format)
    file_handler = logging.FileHandler(LOGS_DIR / "bot.log", encoding="utf-8")
    file_handler.setFormatter(StandardFormatter())
    logger.addHandler(file_handler)

    # JSON file handler (structured logging for analytics)
    json_handler = logging.FileHandler(LOGS_DIR / "bot.jsonl", encoding="utf-8")
    json_handler.setFormatter(JSONFormatter())
    logger.addHandler(json_handler)

    return logger


def log_task(logger: logging.Logger, action: str, user_id: int = None,
             success: bool = True, duration: float = None, message: str = ""):
    """Structured task logging"""
    extra = {
        "action": action,
        "success": success,
    }
    if user_id:
        extra["user_id"] = user_id
    if duration:
        extra["duration"] = round(duration, 3)

    log_msg = f"[{action}] {message}" if message else f"[{action}]"

    if success:
        logger.info(log_msg, extra=extra)
    else:
        logger.error(log_msg, extra=extra)
