import logging
import os
import sys
from pathlib import Path

# Ayarlara bağımlı kalmadan varsayılan bir log dizini belirle
DEFAULT_LOG_DIR = Path.home() / ".elyan" / "logs"

def get_logger(name: str):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Konsol Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # Dosya Handler (Hata almamak için güvenli oluşturma)
        try:
            log_dir = DEFAULT_LOG_DIR
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_dir / "elyan.log", encoding='utf-8')
            file_handler.setFormatter(console_formatter)
            logger.addHandler(file_handler)
        except Exception:
            # Log dosyası oluşturulamazsa konsola devam et
            pass
            
    return logger
