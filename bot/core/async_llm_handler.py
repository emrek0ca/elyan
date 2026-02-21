"""
Async LLM Handler - Non-blocking LLM operations with streaming support
Donma ve takılma olmadan LLM işlemleri için optimize edilmiş sistem
"""

import asyncio
import time
import queue
import threading
from typing import Optional, List, Dict, Any, Callable, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
import json

from utils.logger import get_logger

logger = get_logger("async_llm_handler")


class LLMStatus(Enum):
    """LLM operation status"""
    IDLE = "idle"
    PROCESSING = "processing"
    STREAMING = "streaming"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class LLMRequest:
    """LLM request object"""
    id: str
    prompt: str
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2048
    stream: bool = True
    context: List[Dict[str, str]] = field(default_factory=list)
    timeout: float = 60.0
    callback: Optional[Callable] = None
    priority: int = 0  # Higher = more priority


@dataclass
class LLMResponse:
    """LLM response object"""
    request_id: str
    content: str
    complete: bool = False
    tokens_used: int = 0
    time_taken: float = 0.0
    error: Optional[str] = None
    status: LLMStatus = LLMStatus.IDLE


class AsyncLLMHandler:
    """
    Asynchronous LLM handler with:
    - Non-blocking operations
    - Streaming support
    - Request queuing with priorities
    - Timeout handling
    - Connection pooling
    - Automatic retry on failure
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2:3b",
        max_concurrent: int = 4,
        default_timeout: float = 60.0
    ):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.max_concurrent = max_concurrent
        self.default_timeout = default_timeout

        self._status = LLMStatus.IDLE
        self._request_queue: asyncio.PriorityQueue = None
        self._active_requests: Dict[str, LLMRequest] = {}
        self._response_handlers: Dict[str, Callable] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._semaphore: asyncio.Semaphore = None
        self._running = False
        self._stats = {
            "total_requests": 0,
            "successful": 0,
            "failed": 0,
            "timeouts": 0,
            "avg_response_time": 0.0
        }

    async def initialize(self):
        """Initialize async components"""
        self._request_queue = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._running = True
        logger.info(f"AsyncLLMHandler initialized with model: {self.model}")

    async def shutdown(self):
        """Gracefully shutdown"""
        self._running = False
        self._executor.shutdown(wait=True)
        logger.info("AsyncLLMHandler shutdown complete")

    @property
    def status(self) -> LLMStatus:
        return self._status

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        context: Optional[List[Dict[str, str]]] = None,
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: Optional[float] = None,
        on_token: Optional[Callable[[str], None]] = None
    ) -> LLMResponse:
        """
        Generate a response from the LLM.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            context: Previous conversation context
            stream: Enable streaming (recommended for responsiveness)
            temperature: Creativity level (0-1)
            max_tokens: Maximum response length
            timeout: Request timeout in seconds
            on_token: Callback for each streamed token

        Returns:
            LLMResponse with the generated content
        """
        request_id = f"req_{int(time.time() * 1000)}"
        start_time = time.time()

        request = LLMRequest(
            id=request_id,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            context=context or [],
            timeout=timeout or self.default_timeout,
            callback=on_token
        )

        self._stats["total_requests"] += 1
        self._active_requests[request_id] = request

        try:
            async with self._semaphore:
                self._status = LLMStatus.STREAMING if stream else LLMStatus.PROCESSING

                if stream:
                    response = await self._stream_generate(request)
                else:
                    response = await self._sync_generate(request)

                response.time_taken = time.time() - start_time
                self._stats["successful"] += 1
                self._update_avg_response_time(response.time_taken)

                return response

        except asyncio.TimeoutError:
            self._stats["timeouts"] += 1
            return LLMResponse(
                request_id=request_id,
                content="",
                complete=False,
                error="İstek zaman aşımına uğradı",
                status=LLMStatus.TIMEOUT
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.error(f"LLM generation error: {e}")
            return LLMResponse(
                request_id=request_id,
                content="",
                complete=False,
                error=str(e),
                status=LLMStatus.ERROR
            )

        finally:
            self._active_requests.pop(request_id, None)
            self._status = LLMStatus.IDLE

    async def _stream_generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response with streaming"""
        import httpx

        messages = self._build_messages(request)
        full_content = []
        tokens = 0

        async with httpx.AsyncClient(timeout=request.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "temperature": request.temperature,
                        "num_predict": request.max_tokens
                    }
                }
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        data = json.loads(line)

                        if "message" in data and "content" in data["message"]:
                            token = data["message"]["content"]
                            full_content.append(token)
                            tokens += 1

                            # Call token callback if provided
                            if request.callback:
                                try:
                                    request.callback(token)
                                except Exception as e:
                                    logger.warning(f"Token callback error: {e}")

                        if data.get("done", False):
                            break

                    except json.JSONDecodeError:
                        continue

        return LLMResponse(
            request_id=request.id,
            content="".join(full_content),
            complete=True,
            tokens_used=tokens,
            status=LLMStatus.IDLE
        )

    async def _sync_generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response without streaming"""
        import httpx

        messages = self._build_messages(request)

        async with httpx.AsyncClient(timeout=request.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": request.temperature,
                        "num_predict": request.max_tokens
                    }
                }
            )
            response.raise_for_status()
            data = response.json()

        content = data.get("message", {}).get("content", "")

        return LLMResponse(
            request_id=request.id,
            content=content,
            complete=True,
            tokens_used=data.get("eval_count", 0),
            status=LLMStatus.IDLE
        )

    def _build_messages(self, request: LLMRequest) -> List[Dict[str, str]]:
        """Build messages array for the API"""
        messages = []

        if request.system_prompt:
            messages.append({
                "role": "system",
                "content": request.system_prompt
            })

        # Add context
        for ctx in request.context:
            messages.append(ctx)

        # Add current prompt
        messages.append({
            "role": "user",
            "content": request.prompt
        })

        return messages

    def _update_avg_response_time(self, time_taken: float):
        """Update average response time"""
        total = self._stats["successful"]
        if total == 1:
            self._stats["avg_response_time"] = time_taken
        else:
            current_avg = self._stats["avg_response_time"]
            self._stats["avg_response_time"] = (current_avg * (total - 1) + time_taken) / total

    async def generate_with_retry(
        self,
        prompt: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        **kwargs
    ) -> LLMResponse:
        """Generate with automatic retry on failure"""
        last_error = None

        for attempt in range(max_retries):
            response = await self.generate(prompt, **kwargs)

            if response.error is None:
                return response

            last_error = response.error
            logger.warning(f"LLM attempt {attempt + 1} failed: {last_error}")

            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))

        return LLMResponse(
            request_id=f"retry_failed_{int(time.time())}",
            content="",
            complete=False,
            error=f"Tüm denemeler başarısız: {last_error}",
            status=LLMStatus.ERROR
        )

    async def check_connection(self) -> bool:
        """Check if LLM server is accessible"""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except:
            return False

    async def get_available_models(self) -> List[str]:
        """Get list of available models"""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    return [m["name"] for m in data.get("models", [])]
        except:
            pass

        return []

    def set_model(self, model: str):
        """Change the active model"""
        self.model = model
        logger.info(f"Model changed to: {model}")


class StreamingBuffer:
    """Buffer for managing streaming responses"""

    def __init__(self, max_size: int = 1000):
        self._buffer: List[str] = []
        self._max_size = max_size
        self._lock = threading.Lock()
        self._complete = False

    def add(self, token: str):
        """Add a token to the buffer"""
        with self._lock:
            self._buffer.append(token)
            if len(self._buffer) > self._max_size:
                self._buffer = self._buffer[-self._max_size:]

    def get_content(self) -> str:
        """Get current buffer content"""
        with self._lock:
            return "".join(self._buffer)

    def mark_complete(self):
        """Mark streaming as complete"""
        self._complete = True

    @property
    def is_complete(self) -> bool:
        return self._complete

    def clear(self):
        """Clear the buffer"""
        with self._lock:
            self._buffer.clear()
            self._complete = False


class LLMConnectionPool:
    """Connection pool for LLM requests"""

    def __init__(self, base_url: str, pool_size: int = 5):
        self.base_url = base_url
        self.pool_size = pool_size
        self._clients = []
        self._available = asyncio.Queue()

    async def initialize(self):
        """Initialize the connection pool"""
        import httpx

        for _ in range(self.pool_size):
            client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=60.0,
                limits=httpx.Limits(max_connections=1)
            )
            self._clients.append(client)
            await self._available.put(client)

        logger.info(f"Connection pool initialized with {self.pool_size} connections")

    async def acquire(self):
        """Acquire a client from the pool"""
        return await self._available.get()

    async def release(self, client):
        """Release a client back to the pool"""
        await self._available.put(client)

    async def close(self):
        """Close all connections"""
        for client in self._clients:
            await client.aclose()
        self._clients.clear()


# Global instance
_llm_handler: Optional[AsyncLLMHandler] = None


async def get_llm_handler() -> AsyncLLMHandler:
    """Get or create the global LLM handler"""
    global _llm_handler

    if _llm_handler is None:
        _llm_handler = AsyncLLMHandler()
        await _llm_handler.initialize()

    return _llm_handler


async def quick_generate(prompt: str, **kwargs) -> str:
    """Quick helper for simple generation"""
    handler = await get_llm_handler()
    response = await handler.generate(prompt, **kwargs)

    if response.error:
        raise Exception(response.error)

    return response.content


# Synchronous wrapper for non-async contexts
def generate_sync(prompt: str, **kwargs) -> str:
    """Synchronous wrapper for generate"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(quick_generate(prompt, **kwargs))
    finally:
        loop.close()
