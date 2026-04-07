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

    def __init__(self, chunk_size: int = 160, chunk_delay: float = 0.01):
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
        chunks = self._thought_units(response)
        for chunk in chunks:
            yield chunk
            await asyncio.sleep(self.chunk_delay)

    async def stream_with_spinner(self, response: str) -> AsyncIterator[str]:
        """
        Stream response with progress indicator.

        Yields:
            Response chunks with progress marker
        """
        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        chunks = self._thought_units(response)

        for i, chunk in enumerate(chunks):
            if i % 2 == 0:
                spinner = spinners[i % len(spinners)]
                yield f"{spinner} "
            yield chunk
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
        for chunk in self._thought_units(response):
            if callback:
                callback(chunk)

        return response

    def _thought_units(self, response: str) -> list[str]:
        text = str(response or "").strip()
        if not text:
            return []
        chunks: list[str] = []
        current = ""
        for part in text.replace("\r\n", "\n").split("\n"):
            line = part.strip()
            if not line:
                continue
            segments = [seg.strip() for seg in line.replace("?", "?\n").replace("!", "!\n").replace(". ", ".\n").split("\n") if seg.strip()]
            for segment in segments:
                candidate = f"{current} {segment}".strip() if current else segment
                if len(candidate) <= self.chunk_size:
                    current = candidate
                    continue
                if current:
                    chunks.append(current + (" " if not current.endswith(("?", "!", ".")) else ""))
                current = segment
        if current:
            chunks.append(current + (" " if not current.endswith(("?", "!", ".")) else ""))
        return chunks


__all__ = ["StreamingHandler"]
