"""
Unified Error Handling and Recovery System
"""

from typing import Optional, Dict, Any
from enum import Enum
from utils.logger import get_logger

logger = get_logger("error_handler")


class ErrorCategory(Enum):
    """Error categories for better user feedback"""
    TOOL_NOT_FOUND = "tool_not_found"
    PERMISSION_DENIED = "permission_denied"
    INVALID_PARAMETERS = "invalid_parameters"
    NETWORK_ERROR = "network_error"
    RESOURCE_LIMIT = "resource_limit"
    TIMEOUT = "timeout"
    FILE_NOT_FOUND = "file_not_found"
    LLM_ERROR = "llm_error"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker"
    UNKNOWN = "unknown"


class ErrorHandler:
    """Handles errors and provides user-friendly messages with recovery suggestions"""

    @staticmethod
    def categorize_error(error_msg: str, tool_name: Optional[str] = None) -> ErrorCategory:
        """Categorize error message"""
        error_lower = error_msg.lower()

        if "bulunamadı" in error_lower or "not found" in error_lower:
            if "tool" in error_lower:
                return ErrorCategory.TOOL_NOT_FOUND
            return ErrorCategory.FILE_NOT_FOUND

        if "permission" in error_lower or "yetkisiz" in error_lower:
            return ErrorCategory.PERMISSION_DENIED

        if "timeout" in error_lower or "zaman aşımı" in error_lower:
            return ErrorCategory.TIMEOUT

        if "network" in error_lower or "bağlantı" in error_lower:
            return ErrorCategory.NETWORK_ERROR

        if "circuit breaker" in error_lower or "koruma modu" in error_lower:
            return ErrorCategory.CIRCUIT_BREAKER_OPEN

        if "invalid" in error_lower or "geçersiz" in error_lower:
            return ErrorCategory.INVALID_PARAMETERS

        if "resource" in error_lower or "bellek" in error_lower or "disk" in error_lower:
            return ErrorCategory.RESOURCE_LIMIT

        if "llm" in error_lower or "model" in error_lower or "ollama" in error_lower:
            return ErrorCategory.LLM_ERROR

        return ErrorCategory.UNKNOWN

    @staticmethod
    def get_user_message(category: ErrorCategory, tool_name: Optional[str] = None) -> str:
        """Get user-friendly error message with recovery suggestions"""

        messages = {
            ErrorCategory.TOOL_NOT_FOUND: (
                f" **Araç Bulunamadı**: '{tool_name}' aracı mevcut değil.\n\n"
                " **Çözüm**:\n"
                "- Yazımı kontrol edin\n"
                "- `/help` komutu ile kullanılabilir araçları görebilirsiniz\n"
                "- Doğal dilde tarif etmeyi deneyin"
            ),
            ErrorCategory.PERMISSION_DENIED: (
                " **Erişim Reddedildi**: Bu işlemi yapmak için izniniz yok.\n\n"
                " **Çözüm**:\n"
                "- Dosya izinlerini kontrol edin\n"
                "- Başka bir dosya/klasör ile deneyin"
            ),
            ErrorCategory.FILE_NOT_FOUND: (
                " **Dosya Bulunamadı**: Belirtilen dosya/klasör mevcut değil.\n\n"
                " **Çözüm**:\n"
                "- Dosya yolunu kontrol edin\n"
                "- 'Masaüstümde ne var?' diyerek konumu doğrulayın\n"
                "- Doğru klasöre başvurduğunuzdan emin olun"
            ),
            ErrorCategory.TIMEOUT: (
                "⏱️ **Zaman Aşımı**: İşlem çok uzun sürdü.\n\n"
                " **Çözüm**:\n"
                "- `/cancel` komutu ile işlemi iptal edebilirsiniz\n"
                "- Daha sonra tekrar deneyin\n"
                "- Sistem yük altındaysa lütfen bekleyin"
            ),
            ErrorCategory.NETWORK_ERROR: (
                " **Ağ Hatası**: İnternet bağlantısı sorunu.\n\n"
                " **Çözüm**:\n"
                "- İnternet bağlantınızı kontrol edin\n"
                "- WiFi'yi tekrar bağlanmayı deneyin\n"
                "- Bir kaç saniye bekleyip tekrar deneyin"
            ),
            ErrorCategory.RESOURCE_LIMIT: (
                " **Kaynaklar Tükendi**: Sistem bellek veya disk alanı yetersiz.\n\n"
                " **Çözüm**:\n"
                "- Disk alanını kontrol edin\n"
                "- Gereksiz dosyaları silin\n"
                "- Sistem belleğini boşalt"
            ),
            ErrorCategory.CIRCUIT_BREAKER_OPEN: (
                " **Sistem Koruma Modu**: Çok fazla hata nedeniyle sistem kendini koru\n\n"
                " **Çözüm**:\n"
                "- Lütfen 30 saniye bekleyin\n"
                "- Sistem otomatik olarak kurtarma moduna geçer\n"
                "- `/status` ile durumunu kontrol edin"
            ),
            ErrorCategory.INVALID_PARAMETERS: (
                " **Geçersiz Parametreler**: Komut parametreleri yanlış.\n\n"
                " **Çözüm**:\n"
                "- Komutu daha açık şekilde yazın\n"
                "- Örnek: 'Dosya yolu' yerine tam yol girin\n"
                "- Doğal dilde tarif etmeyi deneyin"
            ),
            ErrorCategory.LLM_ERROR: (
                " **AI Modeli Hatası**: LLM hizmetinde sorun.\n\n"
                " **Çözüm**:\n"
                "- Ollama sunucusunun çalışıp çalışmadığını kontrol edin\n"
                "- Terminal'de: `ollama serve` komutunu çalıştırın\n"
                "- Sistem belleğini kontrol edin"
            ),
            ErrorCategory.UNKNOWN: (
                " **Bilinmeyen Hata**: İşlem başarısız oldu.\n\n"
                " **Çözüm**:\n"
                "- Komutu tekrar deneyin\n"
                "- Sistem durumunu kontrol edin: `/status`\n"
                "- Daha basit bir komutla başlamayı deneyin"
            ),
        }

        return messages.get(category, messages[ErrorCategory.UNKNOWN])

    @staticmethod
    def format_error_response(error_msg: str, tool_name: Optional[str] = None) -> str:
        """Format error with category and suggestion"""
        category = ErrorHandler.categorize_error(error_msg, tool_name)
        user_message = ErrorHandler.get_user_message(category, tool_name)

        # Log for debugging
        logger.error(f"Error [{category.value}] in {tool_name}: {error_msg}")

        return user_message

    @staticmethod
    def should_retry(category: ErrorCategory) -> bool:
        """Determine if operation should be retried"""
        retryable = {
            ErrorCategory.TIMEOUT,
            ErrorCategory.NETWORK_ERROR,
            ErrorCategory.RESOURCE_LIMIT,
        }
        return category in retryable
