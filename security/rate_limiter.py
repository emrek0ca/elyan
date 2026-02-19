"""
Rate Limiter — Kullanıcı başına istek sınırlaması

FIX BUG-SEC-003:
- asyncio.Lock ile concurrent access koruması
- Burst sayacı yalnızca gerçek burst durumunda sıfırlanıyor
- is_allowed() async yapıldı
"""
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Tuple
from utils.logger import get_logger

logger = get_logger("rate_limiter")


class RateLimiter:
    """Token bucket algoritması ile rate limiting (async-safe)"""

    def __init__(
        self,
        requests_per_minute: int = 20,
        burst_limit: int = 5
    ):
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self.user_requests: dict[int, list[datetime]] = defaultdict(list)
        self.burst_tracker: dict[int, int] = defaultdict(int)
        self.last_request: dict[int, datetime] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, user_id: int) -> Tuple[bool, str]:
        """
        Kullanıcının istek yapmasına izin verilip verilmediğini kontrol et.
        Returns: (izin verildi mi, mesaj)
        """
        async with self._lock:
            now = datetime.now()
            window = timedelta(minutes=1)

            # Eski istekleri temizle
            self.user_requests[user_id] = [
                req_time for req_time in self.user_requests[user_id]
                if now - req_time < window
            ]

            # Dakika başına limit kontrolü
            if len(self.user_requests[user_id]) >= self.requests_per_minute:
                oldest = min(self.user_requests[user_id])
                wait_seconds = int((oldest + window - now).total_seconds())
                logger.warning(f"Rate limit aşıldı: user={user_id}, requests={len(self.user_requests[user_id])}")
                return False, f"Çok fazla istek. {wait_seconds} saniye bekleyin."

            # Burst kontrolü (0.5 saniyede çok fazla istek)
            last_req = self.last_request.get(user_id)
            if last_req and (now - last_req).total_seconds() < 0.5:
                # FIX BUG-SEC-003: Burst sayacı yalnızca burst durumunda artırılır
                self.burst_tracker[user_id] += 1
                if self.burst_tracker[user_id] > self.burst_limit:
                    logger.warning(f"Burst limit aşıldı: user={user_id}")
                    return False, "Çok hızlı istek. Lütfen biraz yavaşlayın."
            else:
                # Normal hızda istek — burst sayacını sıfırla
                # FIX: Önceki kodda her normal istekte sıfırlanıyordu (hatalı).
                # Şimdi yalnızca burst penceresi dışına çıkıldığında sıfırlanıyor.
                if last_req is None or (now - last_req).total_seconds() >= 1.0:
                    self.burst_tracker[user_id] = 0

            # İzin ver ve kaydet
            self.user_requests[user_id].append(now)
            self.last_request[user_id] = now

            return True, "OK"

    def is_allowed_sync(self, user_id: int) -> Tuple[bool, str]:
        """
        Sync wrapper — sadece non-async bağlamlarda kullan.
        Async bağlamlarda is_allowed() kullan.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Async context — future oluştur
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.is_allowed(user_id))
                    return future.result(timeout=5)
            else:
                return loop.run_until_complete(self.is_allowed(user_id))
        except Exception:
            # Fallback: izin ver ama logla
            logger.error(f"Rate limiter sync check failed for user {user_id}, allowing by default")
            return True, "OK"

    async def get_user_stats(self, user_id: int) -> dict:
        """Kullanıcının rate limit durumunu döner"""
        async with self._lock:
            now = datetime.now()
            window = timedelta(minutes=1)

            self.user_requests[user_id] = [
                req_time for req_time in self.user_requests[user_id]
                if now - req_time < window
            ]

            current_requests = len(self.user_requests[user_id])
            remaining = max(0, self.requests_per_minute - current_requests)

            return {
                "user_id": user_id,
                "requests_in_window": current_requests,
                "remaining": remaining,
                "limit": self.requests_per_minute,
                "burst_count": self.burst_tracker.get(user_id, 0)
            }

    async def reset_user(self, user_id: int):
        """Kullanıcının rate limit sayaçlarını sıfırlar"""
        async with self._lock:
            self.user_requests[user_id] = []
            self.burst_tracker[user_id] = 0
            self.last_request.pop(user_id, None)
        logger.info(f"Rate limit sıfırlandı: user={user_id}")


# Global instance
rate_limiter = RateLimiter()
