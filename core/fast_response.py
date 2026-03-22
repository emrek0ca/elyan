"""
Fast Response System
Instantly answer simple questions without heavy LLM processing
"""

import time
import re
from typing import Dict, Optional, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum

from core.nlu_normalizer import normalize_turkish_text
from utils.logger import get_logger

logger = get_logger("fast_response")


class QuestionType(Enum):
    """Types of simple questions"""
    GREETING = "greeting"
    TIME = "time"
    DATE = "date"
    WEATHER = "weather"
    CALCULATION = "calculation"
    DEFINITION = "definition"
    STATUS = "status"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass
class FastResponse:
    """Fast response result"""
    answer: str
    confidence: float
    response_time: float
    question_type: QuestionType
    cached: bool = False


class FastResponseSystem:
    """
    Fast Response System
    - Detect simple questions
    - Answer instantly without LLM
    - Sub-100ms response time
    """

    def __init__(self):
        from .response_tone import get_varied_greeting, natural_response

        # Greeting patterns
        self.greeting_patterns = [
            (r'^(merhaba|selam|hey|hi|hello|sa|mrb)$', None),  # dynamic
            (r'\b(nasılsın|nasılsınız|nasilsin|nasilsiniz|how are you|naber|nbr)\b', "İyiyim, sen nasılsın?"),
            (r'\b(günaydın|good morning)\b', None),  # dynamic
            (r'\b(iyi akşamlar|good evening)\b', None),  # dynamic
            (r'\b(iyi geceler|good night)\b', "İyi geceler!"),
        ]

        # Thanks/acknowledgment patterns
        self.thanks_patterns = [
            (r'^(teşekkür|sağol|eyvallah|tşk|saol|eyv|tesekkurler|tesekkur).*$', None),  # dynamic
            (r'^(tamam|ok|peki|anladım|tamamdır|oldu)$', None),  # dynamic
            (r'^(gerek yok|gerek yok|lazım değil|lazım degil)$', "Tamam, bir şey lazım olursa buradayım."),
        ]

        # Conversational catch-all patterns (LLM yerine hızlı yanıt)
        self.conversational_patterns = [
            (r'^(napiyorsun|napıyorsun|napiosun|napıosun|napiyosun|napıyon|napiyon|naptın|naptin|ne yapıyorsun|ne yapiyorsun)\b',
             None),  # dynamic - get_varied_greeting gibi bir şey döner
            (r'^(elyan)\s*$', None),  # Sadece isim yazıldıysa
        ]

        # Identity patterns
        self.identity_patterns = [
            (r'^(sen kimsin|adın ne|adin ne|adın|adin|kimsin sen|kimsin|sen nesin|nesin sen|ismin ne|ismin)\b',
             "Ben Elyan'ım. Bilgisayarda dosya işlemleri, uygulama kontrolü, web araştırma, entegrasyon bağlama, ekran kontrolü ve çok adımlı görev planlama yapabilirim."),
            (r'\b(ne yapabilirsin|yeteneklerin|neler yapabilirsin|özelliklerin|ozelliklerin|ne iş yapıyorsun|ne is yapıyorsun|hangi alanlarda)\b',
             "Yapabileceklerim:\n"
             "- Dosya okuma, yazma, düzenleme ve arama\n"
             "- Uygulama açma/kapatma ve pencere yönetimi\n"
             "- Web araştırma ve özetleme\n"
             "- Google, e-posta ve sosyal entegrasyonlar\n"
             "- Takvim, hatırlatıcı ve scheduler işleri\n"
             "- Ekran kontrolü ve gerçek zamanlı otomasyon\n"
             "- Çok adımlı görev planlama ve sub-agent orkestrasyonu"),
        ]

        self.followup_patterns = [
            r'\b(hangi alanlarda|hangi alanlarda mesela|mesela|örnek ver|ornek ver|örnekler|ornekler|birkaç örnek|bir kac ornek|biraz daha|daha fazla örnek|daha fazla ornek|ne gibi|nerelerde|nerelerde kullanılır|nerelerde kullanilir)\b',
        ]

        self.capability_overview = (
            "Yapabileceklerim:\n"
            "- Dosya okuma, yazma, düzenleme ve arama\n"
            "- Uygulama açma/kapatma ve pencere yönetimi\n"
            "- Web araştırma ve özetleme\n"
            "- Google, e-posta ve sosyal entegrasyonlar\n"
            "- Takvim, hatırlatıcı ve scheduler işleri\n"
            "- Ekran kontrolü ve gerçek zamanlı otomasyon\n"
            "- Çok adımlı görev planlama ve sub-agent orkestrasyonu"
        )

        # Time/Date patterns
        self.time_patterns = [
            (r'\b(saat kaç|what time|current time|şu an saat)\b', self._get_current_time),
            (r'\b(bugün ne|bugün hangi|bugünün tarihi|tarih ne)\b', self._get_current_date),
        ]

        # Status patterns
        self.status_patterns = [
            (r'^(durum|status)$', "Sistem calisiyor, hazirim."),
        ]

        # Help patterns
        self.help_patterns = [
            (r'\b(yardım|help)\b',
             "Yapabileceklerim:\n"
             "- Dosya islemleri (okuma, yazma, arama)\n"
             "- Uygulama kontrolu\n"
             "- Web arastirma\n"
             "- Ekran goruntusu\n"
             "- Sistem bilgisi\n"
             "Detayli yardim icin /help yazin."),
        ]

        # Statistics
        self.stats = {
            "total_requests": 0,
            "fast_responses": 0,
            "avg_response_time": 0.0,
            "by_type": {}
        }

        logger.info("Fast Response System initialized")

    def can_answer_quickly(self, question: str) -> Tuple[bool, QuestionType]:
        """Check if question can be answered quickly"""
        question_lower = normalize_turkish_text(question)

        # Check greetings
        for pattern, _ in self.greeting_patterns:
            if re.search(pattern, question_lower):
                return True, QuestionType.GREETING

        # Check thanks/acknowledgment
        for pattern, _ in self.thanks_patterns:
            if re.search(pattern, question_lower):
                return True, QuestionType.GREETING

        # Check conversational patterns
        for pattern, _ in self.conversational_patterns:
            if re.search(pattern, question_lower):
                return True, QuestionType.GREETING

        # Check identity questions
        for pattern, _ in self.identity_patterns:
            if re.search(pattern, question_lower):
                return True, QuestionType.DEFINITION

        # Check capability follow-ups and examples
        for pattern in self.followup_patterns:
            if re.search(pattern, question_lower):
                return True, QuestionType.DEFINITION

        # Check time/date
        for pattern, _ in self.time_patterns:
            if re.search(pattern, question_lower):
                return True, QuestionType.TIME

        # Check status
        for pattern, _ in self.status_patterns:
            if re.search(pattern, question_lower):
                return True, QuestionType.STATUS

        # Check help
        for pattern, _ in self.help_patterns:
            if re.search(pattern, question_lower):
                return True, QuestionType.HELP

        # Check calculation
        if self._is_calculation(question_lower):
            return True, QuestionType.CALCULATION

        return False, QuestionType.UNKNOWN

    def get_fast_response(self, question: str, context: Optional[Dict[str, Any]] = None) -> Optional[FastResponse]:
        """Get fast response if possible"""
        start_time = time.time()
        self.stats["total_requests"] += 1

        question_lower = normalize_turkish_text(question)
        can_answer, q_type = self.can_answer_quickly(question)

        if not can_answer:
            return None

        if q_type == QuestionType.DEFINITION and context:
            contextual_answer = self._build_topic_answer_from_context(question_lower, context=context)
            if contextual_answer:
                return self._finalize_fast_response(contextual_answer, q_type, start_time)

        answer = None
        from .response_tone import get_varied_greeting, natural_response

        # Try greetings
        for pattern, response in self.greeting_patterns:
            if re.search(pattern, question_lower):
                answer = response if response else get_varied_greeting()
                break

        # Try thanks/acknowledgment
        if not answer:
            for pattern, response in self.thanks_patterns:
                if re.search(pattern, question_lower):
                    answer = response if response else natural_response("thanks_reply")
                    break

        # Try conversational catch-all
        if not answer:
            _conv_replies = [
                "Buradayım, seni dinliyorum.",
                "Seninleyim. Ne lazım?",
                "Hazırım, söyle.",
                "Dinliyorum.",
            ]
            for pattern, response in self.conversational_patterns:
                if re.search(pattern, question_lower):
                    import random as _r
                    answer = response if response else _r.choice(_conv_replies)
                    break

        # Try identity
        if not answer:
            for pattern, response in self.identity_patterns:
                if re.search(pattern, question_lower):
                    answer = response
                    break

        # Try time/date
        if not answer:
            for pattern, func in self.time_patterns:
                if re.search(pattern, question_lower):
                    answer = func()
                    break

        # Try status
        if not answer:
            for pattern, response in self.status_patterns:
                if re.search(pattern, question_lower):
                    answer = response
                    break

        # Try help
        if not answer:
            for pattern, response in self.help_patterns:
                if re.search(pattern, question_lower):
                    answer = response
                    break

        # Try calculation
        if not answer and q_type == QuestionType.CALCULATION:
            answer = self._calculate(question_lower)

        if not answer and q_type == QuestionType.DEFINITION and context:
            answer = self._build_topic_answer_from_context(question_lower, context=context)

        if not answer:
            return None

        return self._finalize_fast_response(answer, q_type, start_time)

    def _build_topic_answer_from_context(self, question: str, context: Optional[Dict[str, Any]] = None) -> str:
        ctx = dict(context or {})
        low = normalize_turkish_text(question)
        last_topic = str(ctx.get("last_topic") or "").strip().lower()
        last_task = str(ctx.get("last_task") or "").strip()
        last_app = str(ctx.get("last_app") or "").strip()
        last_url = str(ctx.get("last_url") or "").strip()
        last_file = str(ctx.get("last_file") or "").strip()

        if not last_topic and not (last_task or last_app or last_url or last_file):
            return ""

        if any(marker in low for marker in ("hangi alanlarda", "mesela", "örnek", "ornek", "hangi alanlarda mesela", "ne gibi", "nerelerde")):
            if last_topic:
                if any(marker in last_topic for marker in ("yapay zeka", "ai", "machine learning", "makine öğrenmesi", "makine ogrenmesi")):
                    return (
                        "Örneğin sağlık, eğitim, finans, müşteri hizmetleri, ulaşım, üretim ve yazılım geliştirmede kullanılıyor. "
                        "İstersen bunlardan birini seçip kısa örneklerle açayım."
                    )
                if any(marker in last_topic for marker in ("dosya", "file", "klasör", "folder")):
                    return "Dosya tarafında klasör tarama, içerik okuma, yazma, toplu düzenleme, yeniden adlandırma ve yedekleme örnekleri verebilirim."
                if any(marker in last_topic for marker in ("google", "gmail", "calendar", "drive", "docs", "sheets", "slides", "chat")):
                    return "Google tarafında Gmail, Calendar, Drive, Docs, Sheets, Slides ve Chat üzerinden örnekler verebilirim."
                if any(marker in last_topic for marker in ("browser", "web", "internet", "site", "tarayıcı", "tarayici")):
                    return "Tarayıcı tarafında site açma, form doldurma, veri çekme, ekran doğrulama ve otomatik akış örnekleri verebilirim."
                return f"{last_topic} için örnekler, avantajlar, riskler ve otomasyon akışı üzerinden devam edebilirim."

            if last_task or last_app or last_url or last_file:
                return "Önceki konuya göre örnekleri uyarlayabilirim. İstersen bunu dosya işlemleri, uygulama kontrolü, web araştırma, entegrasyonlar veya gerçek zamanlı ekran otomasyonu üzerinden açayım."

            return self.capability_overview

        if any(marker in low for marker in ("sen kimsin", "adın ne", "adin ne", "adın", "adin", "ismin ne", "ismin", "kimsin sen", "kimsin", "sen nesin", "nesin sen")):
            return "Ben Elyan'ım. Bilgisayarda dosya işlemleri, uygulama kontrolü, web araştırma, entegrasyon bağlama, takvim/e-posta yönetimi, gerçek zamanlı ekran kontrolü ve çok adımlı görev planlama yapabilirim."

        if last_topic or last_task or last_app or last_url or last_file:
            return "Bu konuya göre dosya işlemleri, uygulama kontrolü, web araştırma, entegrasyonlar ve çok adımlı görevlerde yardımcı olabilirim. İstersen örnekleri son konuya göre uyarlayayım."

        return self.capability_overview

    def _finalize_fast_response(self, answer: str, q_type: QuestionType, start_time: float) -> FastResponse:
        response_time = time.time() - start_time

        self.stats["fast_responses"] += 1
        self.stats["by_type"][q_type.value] = self.stats["by_type"].get(q_type.value, 0) + 1

        total_fast = self.stats["fast_responses"]
        old_avg = self.stats["avg_response_time"]
        self.stats["avg_response_time"] = (old_avg * (total_fast - 1) + response_time) / total_fast

        logger.info(f"Fast response: {q_type.value} in {response_time*1000:.1f}ms")

        return FastResponse(
            answer=answer,
            confidence=0.95,
            response_time=response_time,
            question_type=q_type
        )

    def _build_contextual_capability_answer(self, question: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Answer capability/follow-up questions with conversation context when possible."""
        ctx = dict(context or {})
        low = normalize_turkish_text(question)
        last_topic = str(ctx.get("last_topic") or "").strip()
        last_task = str(ctx.get("last_task") or "").strip()
        last_app = str(ctx.get("last_app") or "").strip()
        last_url = str(ctx.get("last_url") or "").strip()
        last_file = str(ctx.get("last_file") or "").strip()

        if any(marker in low for marker in ("hangi alanlarda", "mesela", "örnek", "ornek", "hangi alanlarda mesela", "ne gibi", "nerelerde")):
            if last_topic:
                topic = last_topic.lower()
                if any(marker in topic for marker in ("yapay zeka", "ai", "machine learning", "makine öğrenmesi", "makine ogrenmesi")):
                    return (
                        "Örneğin sağlık, eğitim, finans, müşteri hizmetleri, ulaşım, üretim ve yazılım geliştirmede kullanılıyor. "
                        "İstersen bunlardan birini seçip kısa örneklerle açayım."
                    )
                if any(marker in topic for marker in ("dosya", "file", "klasör", "folder")):
                    return (
                        "Dosya tarafında klasör tarama, içerik okuma, yazma, toplu düzenleme, yeniden adlandırma ve yedekleme örnekleri verebilirim."
                    )
                if any(marker in topic for marker in ("google", "gmail", "calendar", "drive", "docs", "sheets", "slides", "chat")):
                    return (
                        "Google tarafında Gmail, Calendar, Drive, Docs, Sheets, Slides ve Chat üzerinden örnekler verebilirim."
                    )
                if any(marker in topic for marker in ("browser", "web", "internet", "site", "tarayıcı", "tarayici")):
                    return (
                        "Tarayıcı tarafında site açma, form doldurma, veri çekme, ekran doğrulama ve otomatik akış örnekleri verebilirim."
                    )
                return f"{last_topic} için örnekler, avantajlar, riskler ve otomasyon akışı üzerinden devam edebilirim."

            if last_task or last_app or last_url or last_file:
                return (
                    "Önceki konuya göre örnekleri uyarlayabilirim. İstersen bunu dosya işlemleri, uygulama kontrolü, web araştırma, entegrasyonlar veya gerçek zamanlı ekran otomasyonu üzerinden açayım."
                )

            return self.capability_overview

        if any(marker in low for marker in ("sen kimsin", "adın ne", "adin ne", "adın", "adin", "ismin ne", "ismin", "kimsin sen", "kimsin", "sen nesin", "nesin sen")):
            return (
                "Ben Elyan'ım. Bilgisayarda dosya işlemleri, uygulama kontrolü, web araştırma, entegrasyon bağlama, takvim/e-posta yönetimi, "
                "gerçek zamanlı ekran kontrolü ve çok adımlı görev planlama yapabilirim."
            )

        if last_topic or last_task or last_app or last_url or last_file:
            return (
                "Bu konuya göre dosya işlemleri, uygulama kontrolü, web araştırma, entegrasyonlar ve çok adımlı görevlerde yardımcı olabilirim. "
                "İstersen örnekleri son konuya göre uyarlayayım."
            )

        return self.capability_overview

    def _is_calculation(self, question: str) -> bool:
        """Check if question is a calculation"""
        calc_patterns = [
            r'\d+\s*[\+\-\*\/]\s*\d+',
            r'\b(hesapla|calculate|toplam|sum|çarp|multiply)\b',
        ]

        for pattern in calc_patterns:
            if re.search(pattern, question):
                return True

        return False

    def _calculate(self, question: str) -> str:
        """Perform simple calculations"""
        try:
            # Extract mathematical expression
            expr_match = re.search(r'([\d\+\-\*\/\.\(\)\s]+)', question)
            if expr_match:
                expr = expr_match.group(1).strip()
                # Safe eval (only numbers and operators)
                if re.match(r'^[\d\+\-\*\/\.\(\)\s]+$', expr):
                    result = eval(expr)
                    return f"Sonuç: {result}"
        except Exception as e:
            logger.error(f"Calculation error: {e}")

        return "Üzgünüm, hesaplama yapamadım."

    def _get_current_time(self) -> str:
        """Get current time"""
        from datetime import datetime
        now = datetime.now()
        return f"Şu an saat {now.strftime('%H:%M:%S')}"

    def _get_current_date(self) -> str:
        """Get current date in Turkish"""
        from datetime import datetime
        now = datetime.now()
        aylar = {
            1: "Ocak", 2: "Subat", 3: "Mart", 4: "Nisan",
            5: "Mayis", 6: "Haziran", 7: "Temmuz", 8: "Agustos",
            9: "Eylul", 10: "Ekim", 11: "Kasim", 12: "Aralik"
        }
        gunler = {
            0: "Pazartesi", 1: "Sali", 2: "Carsamba", 3: "Persembe",
            4: "Cuma", 5: "Cumartesi", 6: "Pazar"
        }
        ay = aylar[now.month]
        gun = gunler[now.weekday()]
        return f"Bugun {now.day} {ay} {now.year}, {gun}"

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        hit_rate = (
            self.stats["fast_responses"] / self.stats["total_requests"] * 100
            if self.stats["total_requests"] > 0
            else 0
        )

        return {
            "total_requests": self.stats["total_requests"],
            "fast_responses": self.stats["fast_responses"],
            "hit_rate": f"{hit_rate:.1f}%",
            "avg_response_time": f"{self.stats['avg_response_time']*1000:.1f}ms",
            "by_type": self.stats["by_type"]
        }


# Global instance
_fast_response: Optional[FastResponseSystem] = None


def get_fast_response_system() -> FastResponseSystem:
    """Get or create global fast response system"""
    global _fast_response
    if _fast_response is None:
        _fast_response = FastResponseSystem()
    return _fast_response
