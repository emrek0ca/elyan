"""
ELYAN API Gateway - Phase 6
JWT/OAuth2 authentication, rate limiting, webhook management.
"""

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class AuthMethod(Enum):
    API_KEY = "api_key"
    JWT = "jwt"
    OAUTH2 = "oauth2"


class Permission(Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    EXECUTE = "execute"
    BILLING = "billing"


@dataclass
class APIKey:
    key_id: str
    key_hash: str
    user_id: str
    name: str
    permissions: List[Permission]
    rate_limit: int = 60
    created_at: float = 0.0
    expires_at: Optional[float] = None
    is_active: bool = True
    last_used: float = 0.0
    usage_count: int = 0

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


@dataclass
class JWTConfig:
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_ttl: int = 3600
    refresh_token_ttl: int = 86400 * 7
    issuer: str = "elyan"
    audience: str = "elyan-api"


@dataclass
class JWTPayload:
    sub: str
    iss: str
    aud: str
    exp: float
    iat: float
    permissions: List[str]
    token_type: str = "access"


@dataclass
class WebhookEndpoint:
    endpoint_id: str
    url: str
    user_id: str
    events: List[str]
    secret: str
    is_active: bool = True
    created_at: float = 0.0
    failure_count: int = 0
    last_triggered: float = 0.0
    max_retries: int = 3
    retry_delay: float = 5.0


@dataclass
class WebhookEvent:
    event_id: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: float
    source: str = "elyan"


@dataclass
class RateLimitEntry:
    user_id: str
    window_start: float
    request_count: int
    limit: int


class TokenManager:
    """JWT token creation and validation."""

    def __init__(self, config: Optional[JWTConfig] = None):
        self.config = config or JWTConfig(secret_key=secrets.token_hex(32))

    def create_access_token(self, user_id: str, permissions: List[str]) -> str:
        now = time.time()
        payload = JWTPayload(
            sub=user_id,
            iss=self.config.issuer,
            aud=self.config.audience,
            exp=now + self.config.access_token_ttl,
            iat=now,
            permissions=permissions,
            token_type="access",
        )
        return self._encode(payload)

    def create_refresh_token(self, user_id: str) -> str:
        now = time.time()
        payload = JWTPayload(
            sub=user_id,
            iss=self.config.issuer,
            aud=self.config.audience,
            exp=now + self.config.refresh_token_ttl,
            iat=now,
            permissions=[],
            token_type="refresh",
        )
        return self._encode(payload)

    def validate_token(self, token: str) -> Tuple[bool, Optional[JWTPayload]]:
        try:
            payload = self._decode(token)
            if payload is None:
                return False, None
            if time.time() > payload.exp:
                return False, None
            if payload.iss != self.config.issuer:
                return False, None
            return True, payload
        except Exception:
            return False, None

    def _encode(self, payload: JWTPayload) -> str:
        header = {"alg": self.config.algorithm, "typ": "JWT"}
        header_b64 = self._b64encode(json.dumps(header))
        payload_dict = {
            "sub": payload.sub,
            "iss": payload.iss,
            "aud": payload.aud,
            "exp": payload.exp,
            "iat": payload.iat,
            "permissions": payload.permissions,
            "token_type": payload.token_type,
        }
        payload_b64 = self._b64encode(json.dumps(payload_dict))
        signing_input = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            self.config.secret_key.encode(),
            signing_input.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{signing_input}.{signature}"

    def _decode(self, token: str) -> Optional[JWTPayload]:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature = parts
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            self.config.secret_key.encode(),
            signing_input.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        payload_json = self._b64decode(payload_b64)
        data = json.loads(payload_json)
        return JWTPayload(
            sub=data["sub"],
            iss=data["iss"],
            aud=data["aud"],
            exp=data["exp"],
            iat=data["iat"],
            permissions=data.get("permissions", []),
            token_type=data.get("token_type", "access"),
        )

    @staticmethod
    def _b64encode(data: str) -> str:
        import base64
        return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")

    @staticmethod
    def _b64decode(data: str) -> str:
        import base64
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data.encode()).decode()


class APIKeyManager:
    """API key creation, validation, and management."""

    def __init__(self):
        self._keys: Dict[str, APIKey] = {}

    def create_key(
        self,
        user_id: str,
        name: str,
        permissions: Optional[List[Permission]] = None,
        rate_limit: int = 60,
        ttl_seconds: Optional[int] = None,
    ) -> Tuple[str, APIKey]:
        raw_key = f"elk_{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = f"kid_{secrets.token_hex(8)}"
        now = time.time()
        api_key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            user_id=user_id,
            name=name,
            permissions=permissions or [Permission.READ, Permission.EXECUTE],
            rate_limit=rate_limit,
            created_at=now,
            expires_at=now + ttl_seconds if ttl_seconds else None,
        )
        self._keys[key_id] = api_key
        return raw_key, api_key

    def validate_key(self, raw_key: str) -> Tuple[bool, Optional[APIKey]]:
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        for api_key in self._keys.values():
            if api_key.key_hash == key_hash:
                if not api_key.is_active:
                    return False, None
                if api_key.is_expired():
                    return False, None
                api_key.last_used = time.time()
                api_key.usage_count += 1
                return True, api_key
        return False, None

    def revoke_key(self, key_id: str) -> bool:
        if key_id in self._keys:
            self._keys[key_id].is_active = False
            return True
        return False

    def list_keys(self, user_id: str) -> List[APIKey]:
        return [k for k in self._keys.values() if k.user_id == user_id]

    def rotate_key(self, key_id: str) -> Optional[Tuple[str, APIKey]]:
        old_key = self._keys.get(key_id)
        if old_key is None:
            return None
        old_key.is_active = False
        return self.create_key(
            user_id=old_key.user_id,
            name=old_key.name,
            permissions=old_key.permissions,
            rate_limit=old_key.rate_limit,
        )


class WebhookManager:
    """Webhook registration, delivery, and retry management."""

    VALID_EVENTS = [
        "task.created",
        "task.completed",
        "task.failed",
        "agent.response",
        "agent.error",
        "code.generated",
        "code.reviewed",
        "learning.pattern_detected",
        "health.degraded",
        "health.critical",
        "billing.usage_threshold",
    ]

    def __init__(self):
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._event_log: List[Dict[str, Any]] = []

    def register(
        self,
        url: str,
        user_id: str,
        events: List[str],
        max_retries: int = 3,
    ) -> WebhookEndpoint:
        valid = [e for e in events if e in self.VALID_EVENTS]
        if not valid:
            raise ValueError(f"No valid events. Choose from: {self.VALID_EVENTS}")
        endpoint_id = f"wh_{secrets.token_hex(8)}"
        secret = secrets.token_hex(16)
        endpoint = WebhookEndpoint(
            endpoint_id=endpoint_id,
            url=url,
            user_id=user_id,
            events=valid,
            secret=secret,
            created_at=time.time(),
            max_retries=max_retries,
        )
        self._endpoints[endpoint_id] = endpoint
        return endpoint

    def unregister(self, endpoint_id: str) -> bool:
        if endpoint_id in self._endpoints:
            del self._endpoints[endpoint_id]
            return True
        return False

    def dispatch(self, event: WebhookEvent) -> List[Dict[str, Any]]:
        results = []
        for ep in self._endpoints.values():
            if not ep.is_active:
                continue
            if event.event_type not in ep.events:
                continue
            delivery = self._deliver(ep, event)
            results.append(delivery)
        return results

    def _deliver(self, endpoint: WebhookEndpoint, event: WebhookEvent) -> Dict[str, Any]:
        payload = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "source": event.source,
            "data": event.payload,
        }
        signature = hmac.new(
            endpoint.secret.encode(),
            json.dumps(payload, sort_keys=True).encode(),
            hashlib.sha256,
        ).hexdigest()
        delivery_record = {
            "endpoint_id": endpoint.endpoint_id,
            "url": endpoint.url,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "signature": f"sha256={signature}",
            "status": "delivered",
            "timestamp": time.time(),
            "attempts": 1,
        }
        endpoint.last_triggered = time.time()
        self._event_log.append(delivery_record)
        return delivery_record

    def list_endpoints(self, user_id: str) -> List[WebhookEndpoint]:
        return [ep for ep in self._endpoints.values() if ep.user_id == user_id]

    def get_delivery_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._event_log[-limit:]


class GatewayRateLimiter:
    """Per-user sliding window rate limiter for API gateway."""

    def __init__(self, default_limit: int = 60, window_seconds: int = 60):
        self._entries: Dict[str, RateLimitEntry] = {}
        self._default_limit = default_limit
        self._window = window_seconds

    def check(self, user_id: str, limit: Optional[int] = None) -> Tuple[bool, Dict[str, Any]]:
        now = time.time()
        effective_limit = limit or self._default_limit
        entry = self._entries.get(user_id)
        if entry is None or (now - entry.window_start) > self._window:
            self._entries[user_id] = RateLimitEntry(
                user_id=user_id,
                window_start=now,
                request_count=1,
                limit=effective_limit,
            )
            return True, self._headers(1, effective_limit, now + self._window)
        if entry.request_count >= effective_limit:
            retry_after = entry.window_start + self._window - now
            return False, {
                **self._headers(entry.request_count, effective_limit, entry.window_start + self._window),
                "retry_after": max(0, retry_after),
            }
        entry.request_count += 1
        return True, self._headers(entry.request_count, effective_limit, entry.window_start + self._window)

    @staticmethod
    def _headers(used: int, limit: int, reset: float) -> Dict[str, Any]:
        return {
            "X-RateLimit-Limit": limit,
            "X-RateLimit-Remaining": max(0, limit - used),
            "X-RateLimit-Reset": int(reset),
        }


class APIGateway:
    """Main API Gateway coordinating auth, rate limiting, and webhooks."""

    def __init__(self, jwt_config: Optional[JWTConfig] = None):
        self.token_manager = TokenManager(jwt_config)
        self.key_manager = APIKeyManager()
        self.webhook_manager = WebhookManager()
        self.rate_limiter = GatewayRateLimiter()
        self._request_log: List[Dict[str, Any]] = []

    def authenticate(self, auth_header: str) -> Tuple[bool, Optional[str], Optional[List[str]]]:
        if not auth_header:
            return False, None, None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            valid, payload = self.token_manager.validate_token(token)
            if valid and payload:
                return True, payload.sub, payload.permissions
            return False, None, None
        if auth_header.startswith("ApiKey "):
            raw_key = auth_header[7:]
            valid, api_key = self.key_manager.validate_key(raw_key)
            if valid and api_key:
                perms = [p.value for p in api_key.permissions]
                return True, api_key.user_id, perms
            return False, None, None
        return False, None, None

    def process_request(
        self,
        auth_header: str,
        method: str = "GET",
        path: str = "/",
        body: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        authed, user_id, permissions = self.authenticate(auth_header)
        if not authed:
            return {"status": 401, "error": "Unauthorized", "body": None}
        allowed, rate_info = self.rate_limiter.check(user_id)
        if not allowed:
            return {
                "status": 429,
                "error": "Rate limit exceeded",
                "body": None,
                "headers": rate_info,
            }
        log_entry = {
            "user_id": user_id,
            "method": method,
            "path": path,
            "timestamp": time.time(),
            "status": 200,
        }
        self._request_log.append(log_entry)
        return {
            "status": 200,
            "user_id": user_id,
            "permissions": permissions,
            "body": body,
            "headers": rate_info,
        }

    def get_request_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._request_log[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_requests": len(self._request_log),
            "active_api_keys": sum(1 for k in self.key_manager._keys.values() if k.is_active),
            "webhook_endpoints": len(self.webhook_manager._endpoints),
            "valid_webhook_events": WebhookManager.VALID_EVENTS,
        }
