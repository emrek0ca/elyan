"""
Streaming Handler
Provides real-time streaming feedback to user.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator


class StreamingHandler:
    """
    Handles real-time streaming of responses.
    Chunks response for progressive display.
    """

    def __init__(self, chunk_size: int = 50, chunk_delay: float = 0.01):
        """
        Args:
            chunk_size: Characters per chunk
            chunk_delay: Delay between chunks (seconds)
        """
        self.chunk_size = chunk_size
        self.chunk_delay = chunk_delay

    async def stream_response(self, response: str) -> AsyncIterator[str]:
        """
        Stream response text in chunks.

        Args:
            response: Full response text

        Yields:
            Response chunks
        """
        # Split into words to avoid breaking mid-word
        words = response.split()
        current_chunk = ""

        for word in words:
            current_chunk += word + " "

            if len(current_chunk) >= self.chunk_size:
                yield current_chunk
                current_chunk = ""
                await asyncio.sleep(self.chunk_delay)

        # Yield remaining
        if current_chunk:
            yield current_chunk

    async def stream_with_spinner(self, response: str) -> AsyncIterator[str]:
        """
        Stream response with progress indicator.

        Yields:
            Response chunks with progress marker
        """
        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        words = response.split()

        for i, word in enumerate(words):
            # Emit spinner every 10 words
            if i % 10 == 0:
                spinner = spinners[i % len(spinners)]
                yield f"{spinner} "

            yield word + " "
            await asyncio.sleep(self.chunk_delay)

    def stream_sync(self, response: str, callback=None) -> str:
        """
        Synchronous streaming (for CLI use).

        Args:
            response: Full response
            callback: Optional callable(chunk) for each chunk

        Returns:
            Full response
        """
        words = response.split()
        current_chunk = ""

        for word in words:
            current_chunk += word + " "

            if len(current_chunk) >= self.chunk_size:
                if callback:
                    callback(current_chunk)
                current_chunk = ""

        if current_chunk and callback:
            callback(current_chunk)

        return response


__all__ = ["StreamingHandler"]
