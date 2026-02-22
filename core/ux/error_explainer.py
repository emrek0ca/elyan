"""
core/ux/error_explainer.py
─────────────────────────────────────────────────────────────────────────────
Human-Readable Error Explainer (Phase 33).
Converts raw Python tracebacks into user-friendly Turkish explanations
with actionable fix suggestions.
"""

import traceback
import re
from utils.logger import get_logger

logger = get_logger("error_explainer")

# Common error patterns and their Turkish explanations
ERROR_PATTERNS = {
    r"ModuleNotFoundError: No module named '(\w+)'": 
        "'{0}' modülü yüklü değil. Çözüm: `pip install {0}` komutunu çalıştırın.",
    
    r"KeyError: '(\w+)'":
        "'{0}' anahtarı bulunamadı. Muhtemelen yapılandırma dosyasında veya sözlükte bu anahtar eksik.",
    
    r"FileNotFoundError.*'(.+?)'":
        "Dosya bulunamadı: '{0}'. Dosyanın var olduğundan ve doğru yolu belirttiğinizden emin olun.",
    
    r"PermissionError.*'(.+?)'":
        "'{0}' dosyasına erişim izni yok. Dosya izinlerini kontrol edin veya `sudo` ile çalıştırın.",
    
    r"ConnectionRefusedError":
        "Bağlantı reddedildi. Hedef sunucunun çalışır durumda olduğundan ve portun açık olduğundan emin olun.",
    
    r"TimeoutError":
        "İşlem zaman aşımına uğradı. İnternet bağlantınızı kontrol edin veya zaman aşımı süresini artırın.",
    
    r"json\.decoder\.JSONDecodeError":
        "Geçersiz JSON formatı. API'den gelen yanıt beklenen formatta değil.",
    
    r"TypeError: .+ takes (\d+) positional .+ (\d+) .+ given":
        "Fonksiyona yanlış sayıda argüman gönderildi. {0} argüman bekleniyor ama {1} gönderildi.",
    
    r"AttributeError: '(\w+)' object has no attribute '(\w+)'":
        "'{0}' nesnesinin '{1}' adında bir özelliği yok. Doğru nesne tipini kullandığınızdan emin olun.",
    
    r"ValueError: invalid literal":
        "Geçersiz değer dönüşümü. Bir metni sayıya çevirmeye çalışıyorsunuz ama metin geçerli bir sayı değil.",
    
    r"MemoryError":
        "Yetersiz bellek! Çok büyük bir veri seti veya döngü var. Veriyi parçalara bölerek işleyin.",
    
    r"RecursionError":
        "Sonsuz döngü tespit edildi! Bir fonksiyon kendini sonsuz kez çağırıyor. Çıkış koşulunu kontrol edin.",
    
    r"ImportError: cannot import name '(\w+)'":
        "'{0}' içe aktarılamıyor. Modül versiyonu uyumsuz olabilir. `pip install --upgrade` deneyin.",
        
    r"OSError: \[Errno 48\] Address already in use":
        "Port zaten kullanımda. Başka bir uygulama aynı portu kullanıyor. `lsof -i :PORT` ile kontrol edin.",
}

class ErrorExplainer:
    @staticmethod
    def explain(error: Exception) -> str:
        """Convert a Python exception into a human-readable Turkish explanation."""
        error_str = str(error)
        error_type = type(error).__name__
        
        # Try to match against known patterns
        for pattern, template in ERROR_PATTERNS.items():
            match = re.search(pattern, f"{error_type}: {error_str}")
            if match:
                groups = match.groups()
                try:
                    explanation = template.format(*groups) if groups else template
                except:
                    explanation = template
                
                return f"🔴 **Hata:** {error_type}\n💡 **Açıklama:** {explanation}"
        
        # Fallback: generic explanation
        return (
            f"🔴 **Hata:** {error_type}\n"
            f"📝 **Detay:** {error_str[:200]}\n"
            f"💡 **Öneri:** Bu hatayı çözmek için hata mesajını dikkatlice okuyun."
        )
    
    @staticmethod
    def explain_traceback(tb_string: str) -> str:
        """Explain a full traceback string."""
        # Extract just the last line (the actual error)
        lines = tb_string.strip().split('\n')
        if lines:
            last_line = lines[-1]
            # Try to reconstruct the exception
            for pattern, template in ERROR_PATTERNS.items():
                match = re.search(pattern, last_line)
                if match:
                    groups = match.groups()
                    try:
                        explanation = template.format(*groups) if groups else template
                    except:
                        explanation = template
                    
                    # Find the file and line
                    file_line = ""
                    for line in lines:
                        if 'File "' in line:
                            file_line = line.strip()
                    
                    return (
                        f"🔴 **Hata:** {last_line}\n"
                        f"📍 **Konum:** {file_line}\n"
                        f"💡 **Açıklama:** {explanation}"
                    )
        
        return f"🔴 Bilinmeyen hata. Detaylar:\n```\n{tb_string[:300]}\n```"

# Global singleton
explainer = ErrorExplainer()
