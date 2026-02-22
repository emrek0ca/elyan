"""
core/resilience/global_handler.py
─────────────────────────────────────────────────────────────────────────────
Bulletproof Global Exception Handler (Phase 34).
Elyan must NEVER crash. This module wraps every async operation in a 
resilient try/catch with structured error reporting, retry logic, 
and graceful OS-specific fallbacks.
"""

import asyncio
import sys
import time
import functools
import traceback
from typing import Callable, Any, Optional, TypeVar, List
from utils.logger import get_logger

logger = get_logger("resilience")
T = TypeVar('T')

class RetryConfig:
    def __init__(self, max_attempts: int = 3, base_delay: float = 1.0, 
                 max_delay: float = 30.0, exponential: bool = True):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential = exponential

DEFAULT_RETRY = RetryConfig()

async def resilient_call(
    func: Callable, 
    *args, 
    retry_config: RetryConfig = DEFAULT_RETRY,
    fallback_value: Any = None,
    operation_name: str = "unknown",
    **kwargs
) -> Any:
    """Execute any async function with retry logic and graceful degradation."""
    last_error = None
    
    for attempt in range(1, retry_config.max_attempts + 1):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
                
        except KeyboardInterrupt:
            raise  # Never suppress user interrupts
        except Exception as e:
            last_error = e
            if attempt < retry_config.max_attempts:
                delay = min(
                    retry_config.base_delay * (2 ** (attempt - 1)) if retry_config.exponential 
                    else retry_config.base_delay,
                    retry_config.max_delay
                )
                logger.warning(
                    f"⚠️ [{operation_name}] Attempt {attempt}/{retry_config.max_attempts} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"❌ [{operation_name}] All {retry_config.max_attempts} attempts failed: {e}")
    
    if fallback_value is not None:
        logger.info(f"🔄 [{operation_name}] Using fallback value.")
        return fallback_value
    
    return None

class OSFallbackChain:
    """Tries platform-specific implementations in order, gracefully skipping unavailable ones."""
    
    def __init__(self):
        self.platform = sys.platform
        self._fallbacks: List[tuple] = []
    
    def register(self, platform: str, func: Callable, description: str = ""):
        """Register a platform-specific implementation."""
        self._fallbacks.append((platform, func, description))
        return self
    
    async def execute(self, *args, **kwargs) -> Any:
        """Try each registered implementation for the current platform."""
        # First try exact platform match
        for platform, func, desc in self._fallbacks:
            if platform == self.platform or platform == "any":
                try:
                    result = await resilient_call(
                        func, *args, 
                        operation_name=f"OSFallback({desc})",
                        fallback_value=None, 
                        **kwargs
                    )
                    if result is not None:
                        return result
                except Exception as e:
                    logger.debug(f"OS fallback '{desc}' failed on {self.platform}: {e}")
                    continue
        
        # Try any remaining fallbacks
        for platform, func, desc in self._fallbacks:
            if platform != self.platform and platform != "any":
                try:
                    result = await resilient_call(
                        func, *args,
                        operation_name=f"OSFallback({desc})-cross",
                        fallback_value=None,
                        **kwargs
                    )
                    if result is not None:
                        return result
                except:
                    continue
        
        logger.warning("🔄 All OS fallbacks exhausted. Returning None.")
        return None

def never_crash(operation_name: str = ""):
    """Decorator that ensures a function NEVER crashes the application."""
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.error(f"🛡️ [{operation_name or func.__name__}] Caught crash: {e}")
                logger.debug(traceback.format_exc())
                return None
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.error(f"🛡️ [{operation_name or func.__name__}] Caught crash: {e}")
                return None
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator

def install_global_handler():
    """Install a global unhandled exception hook so Elyan NEVER dies."""
    def _global_handler(exc_type, exc_value, exc_tb):
        if exc_type == KeyboardInterrupt:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical(f"🚨 GLOBAL UNHANDLED: {exc_type.__name__}: {exc_value}")
        logger.critical("".join(traceback.format_tb(exc_tb)))
    
    sys.excepthook = _global_handler
    
    def _async_handler(loop, context):
        msg = context.get("message", "Unknown async error")
        exc = context.get("exception")
        if exc:
            logger.critical(f"🚨 ASYNC UNHANDLED: {msg}: {exc}")
        else:
            logger.critical(f"🚨 ASYNC UNHANDLED: {msg}")
    
    try:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_async_handler)
    except RuntimeError:
        pass
    
    logger.info("🛡️ Global Crash Protection ACTIVE. Elyan will never die.")
