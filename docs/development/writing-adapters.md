# Kanal Adaptörü Yazma

Elyan'a yeni bir mesajlaşma platformu eklemek için `BaseChannelAdapter` soyut sınıfını uygulayın.

## Temel Sınıf

`core/gateway/adapters/base.py`:

```python
from abc import ABC, abstractmethod
from typing import Callable, Optional

class BaseChannelAdapter(ABC):

    @abstractmethod
    async def connect(self) -> bool:
        """Platforma bağlan. Başarı durumunda True döndür."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Bağlantıyı kapat."""

    @abstractmethod
    async def send_message(self, channel_id: str, text: str, **kwargs) -> bool:
        """Mesaj gönder."""

    @abstractmethod
    async def get_status(self) -> dict:
        """Bağlantı durumu: {"connected": bool, "latency_ms": int}"""

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        """Desteklenen özellikler: ["text", "markdown", "files", ...]"""
```

## Yeni Adapter Oluşturma

### 1. Dosya Oluşturun

`core/gateway/adapters/myplatform_adapter.py`:

```python
"""MyPlatform kanal adaptörü."""
import asyncio
import logging
from typing import Callable, Optional
from .base import BaseChannelAdapter, UnifiedMessage

logger = logging.getLogger(__name__)


class MyPlatformAdapter(BaseChannelAdapter):
    """MyPlatform için Elyan adaptörü."""

    def __init__(self, config: dict, message_callback: Optional[Callable] = None):
        self.config = config
        self.api_key = config.get("api_key", "")
        self.message_callback = message_callback
        self._connected = False

    async def connect(self) -> bool:
        if not self.api_key:
            logger.error("MyPlatform: api_key eksik")
            return False
        try:
            # Platform'a bağlan
            # self._client = MyPlatformClient(self.api_key)
            # await self._client.verify()
            self._connected = True
            logger.info("MyPlatform: bağlandı")
            return True
        except Exception as e:
            logger.error("MyPlatform bağlantı hatası: %s", e)
            return False

    async def disconnect(self) -> None:
        self._connected = False
        # await self._client.close()

    async def send_message(self, channel_id: str, text: str, **kwargs) -> bool:
        if not self._connected:
            return False
        try:
            # await self._client.send(channel_id, text)
            return True
        except Exception as e:
            logger.error("MyPlatform gönderme hatası: %s", e)
            return False

    async def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "latency_ms": 0,
            "platform": "myplatform"
        }

    def get_capabilities(self) -> list:
        return ["text", "markdown"]

    async def _poll_messages(self):
        """Mesaj alma döngüsü."""
        while self._connected:
            try:
                # messages = await self._client.poll()
                # for msg in messages:
                #     await self._handle_message(msg)
                await asyncio.sleep(1)
            except Exception as e:
                logger.error("Polling hatası: %s", e)
                await asyncio.sleep(5)

    async def _handle_message(self, raw_msg: dict):
        """Ham platform mesajını UnifiedMessage'a dönüştür."""
        if not self.message_callback:
            return

        unified = UnifiedMessage(
            channel="myplatform",
            channel_id=raw_msg.get("chat_id", ""),
            user_id=raw_msg.get("user_id", ""),
            username=raw_msg.get("username", ""),
            text=raw_msg.get("text", ""),
            message_id=str(raw_msg.get("id", "")),
            metadata={}
        )
        await self.message_callback(unified)
```

### 2. Registry'ye Ekleyin

`core/gateway/adapters/__init__.py`:

```python
from .myplatform_adapter import MyPlatformAdapter

ADAPTER_REGISTRY = {
    # ... mevcut adapterlar ...
    "myplatform": MyPlatformAdapter,
}
```

### 3. Yapılandırma Şeması

Adapter'ınızın beklediği config alanlarını belgeleyin:

```json5
{
  "channels": [
    {
      "type": "myplatform",
      "api_key": "YOUR_API_KEY",
      "webhook_path": "/myplatform/webhook",
      "enabled": true
    }
  ]
}
```

### 4. Test Yazın

`tests/unit/test_gateway_adapters.py`:

```python
class TestMyPlatformAdapter:

    def test_init_defaults(self):
        from core.gateway.adapters.myplatform_adapter import MyPlatformAdapter
        adapter = MyPlatformAdapter({"api_key": "test"})
        assert adapter.api_key == "test"
        assert adapter._connected is False

    @pytest.mark.asyncio
    async def test_connect_missing_key(self):
        from core.gateway.adapters.myplatform_adapter import MyPlatformAdapter
        adapter = MyPlatformAdapter({})
        result = await adapter.connect()
        assert result is False

    def test_get_capabilities(self):
        from core.gateway.adapters.myplatform_adapter import MyPlatformAdapter
        adapter = MyPlatformAdapter({"api_key": "test"})
        caps = adapter.get_capabilities()
        assert "text" in caps
```

### 5. Dokümantasyon

`docs/channels/myplatform.md` oluşturun. Şablon:

```markdown
# MyPlatform Entegrasyonu

## Gereksinimler
## Kurulum
## Yapılandırma
## Desteklenen Özellikler
## Sorun Giderme
```

## UnifiedMessage Yapısı

```python
@dataclass
class UnifiedMessage:
    channel: str        # "telegram", "discord", "myplatform"
    channel_id: str     # Platform mesaj ID'si
    user_id: str        # Kullanıcı kimliği
    username: str       # Görünen ad
    text: str           # Mesaj metni
    message_id: str     # Benzersiz mesaj ID
    metadata: dict      # Platform'a özgü ek veri
    attachments: list   # Dosya/resim ekleri
    is_reply: bool      # Yanıt mı?
    reply_to_id: str    # Hangi mesajın yanıtı
```

## Lazy Import (Büyük Bağımlılıklar)

Ağır bağımlılıklar için `connect()` içinde lazy import kullanın:

```python
async def connect(self) -> bool:
    try:
        from my_heavy_library import Client
    except ImportError:
        logger.error("my-heavy-library yüklü değil: pip install my-heavy-library")
        return False
    self._client = Client(self.api_key)
    ...
```

Bu sayede bağımlılık yüklü olmasa bile diğer adapterlar çalışmaya devam eder.
