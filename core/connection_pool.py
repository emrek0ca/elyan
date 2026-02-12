"""
Connection Pooling System
Manages reusable connections for HTTP and database operations
"""

import asyncio
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
import httpx
from utils.logger import get_logger

logger = get_logger("connection_pool")


class HTTPConnectionPool:
    """Manages HTTP client connections with pooling"""

    def __init__(self, max_connections: int = 20, timeout: float = 30.0):
        self.max_connections = max_connections
        self.timeout = timeout
        self.client: Optional[httpx.AsyncClient] = None
        self.lock = asyncio.Lock()

    async def initialize(self):
        """Initialize HTTP client"""
        limits = httpx.Limits(max_connections=self.max_connections)
        self.client = httpx.AsyncClient(
            limits=limits,
            timeout=self.timeout,
            verify=True
        )
        logger.info(f"HTTP connection pool initialized ({self.max_connections} max connections)")

    async def close(self):
        """Close HTTP client"""
        if self.client:
            await self.client.aclose()
            self.client = None
            logger.info("HTTP connection pool closed")

    @asynccontextmanager
    async def acquire(self):
        """Acquire HTTP client from pool"""
        async with self.lock:
            if self.client is None:
                await self.initialize()

        try:
            yield self.client
        except Exception as e:
            logger.error(f"Error using HTTP connection: {e}")
            raise

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Make GET request with pooled connection"""
        async with self.acquire() as client:
            return await client.get(url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        """Make POST request with pooled connection"""
        async with self.acquire() as client:
            return await client.post(url, **kwargs)

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make HTTP request with pooled connection"""
        async with self.acquire() as client:
            return await client.request(method, url, **kwargs)

    def get_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics"""
        if not self.client:
            return {"status": "uninitialized"}

        return {
            "status": "active",
            "max_connections": self.max_connections,
            "timeout": self.timeout,
            "is_closed": self.client.is_closed if self.client else True
        }


class DatabaseConnectionPool:
    """Manages database connections with pooling"""

    def __init__(self, min_connections: int = 2, max_connections: int = 10):
        self.min_connections = min_connections
        self.max_connections = max_connections
        self.available_connections: asyncio.Queue = asyncio.Queue(maxsize=max_connections)
        self.active_connections = 0
        self.lock = asyncio.Lock()

    async def initialize(self, connection_func, *args, **kwargs):
        """Initialize connection pool"""
        for _ in range(self.min_connections):
            try:
                conn = await connection_func(*args, **kwargs)
                await self.available_connections.put(conn)
            except Exception as e:
                logger.error(f"Failed to initialize connection: {e}")

        logger.info(f"Database connection pool initialized ({self.min_connections} initial, {self.max_connections} max)")

    @asynccontextmanager
    async def acquire(self, connection_func, *args, **kwargs):
        """Acquire connection from pool"""
        connection = None

        try:
            # Try to get available connection
            try:
                connection = self.available_connections.get_nowait()
            except asyncio.QueueEmpty:
                # Create new connection if under limit
                async with self.lock:
                    if self.active_connections < self.max_connections:
                        self.active_connections += 1
                        connection = await connection_func(*args, **kwargs)
                    else:
                        # Wait for available connection
                        connection = await asyncio.wait_for(
                            self.available_connections.get(),
                            timeout=5.0
                        )

            yield connection

        finally:
            # Return connection to pool
            if connection:
                try:
                    await self.available_connections.put(connection)
                except asyncio.QueueFull:
                    logger.warning("Connection pool full, closing connection")

    async def close_all(self):
        """Close all connections"""
        while not self.available_connections.empty():
            try:
                conn = self.available_connections.get_nowait()
                if hasattr(conn, 'close'):
                    await conn.close()
            except asyncio.QueueEmpty:
                break

        self.active_connections = 0
        logger.info("All database connections closed")

    def get_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics"""
        return {
            "available": self.available_connections.qsize(),
            "active": self.active_connections,
            "min_size": self.min_connections,
            "max_size": self.max_connections,
            "utilization": f"{(self.active_connections / self.max_connections * 100):.1f}%"
        }


# Global instances
_http_pool: Optional[HTTPConnectionPool] = None
_db_pool: Optional[DatabaseConnectionPool] = None


def get_http_pool() -> HTTPConnectionPool:
    """Get or create HTTP connection pool"""
    global _http_pool
    if _http_pool is None:
        _http_pool = HTTPConnectionPool(max_connections=20, timeout=30.0)
    return _http_pool


def get_db_pool() -> DatabaseConnectionPool:
    """Get or create database connection pool"""
    global _db_pool
    if _db_pool is None:
        _db_pool = DatabaseConnectionPool(min_connections=2, max_connections=10)
    return _db_pool


async def initialize_pools():
    """Initialize all connection pools"""
    http_pool = get_http_pool()
    await http_pool.initialize()
    logger.info("Connection pools initialized")


async def close_pools():
    """Close all connection pools"""
    if _http_pool:
        await _http_pool.close()
    if _db_pool:
        await _db_pool.close_all()
    logger.info("Connection pools closed")
