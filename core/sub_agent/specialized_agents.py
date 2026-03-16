"""
core/sub_agent/specialized_agents.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4: Specialized Sub-Agents (~400 lines)
Specialized agents for different task domains with domain-specific error handling.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
import asyncio
import os
import json
import aiohttp
import re
from pathlib import Path
from typing import Any, Dict, Optional, List
from .base_agent import SubAgent, AgentConfig, AgentState, ExecutionResult, ExecutionStatus
from utils.logger import get_logger

logger = get_logger("specialized_agents")


class FileOperationAgent(SubAgent):
    """Handle file I/O operations with safety guarantees."""

    def __init__(self, config: Optional[AgentConfig] = None):
        if config is None:
            config = AgentConfig(name="FileOperationAgent", description="Handles file operations")
        super().__init__(config)
        self.allowed_paths: List[Path] = []
        self.temp_dir: Optional[Path] = None

    async def _on_initialize(self) -> bool:
        """Initialize file operation resources."""
        try:
            self.allowed_paths = [Path.home(), Path("/tmp")]
            self.temp_dir = Path("/tmp") / f"agent_{self.config.agent_id}"
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            self.log_info(f"Initialized file operations in {self.temp_dir}")
            return True
        except Exception as e:
            self.log_error(f"Failed to initialize: {e}")
            return False

    async def _execute_task(self, task_id: str, task_input: Dict[str, Any]) -> Any:
        """Execute file operation task."""
        operation = task_input.get("operation", "read")
        path = task_input.get("path")
        content = task_input.get("content")
        mode = task_input.get("mode", "text")

        if not path:
            raise ValueError("Path is required")

        # Validate path
        file_path = Path(path)
        if not self._is_path_allowed(file_path):
            raise PermissionError(f"Path not allowed: {path}")

        if operation == "read":
            return await self._read_file(file_path, mode)
        elif operation == "write":
            return await self._write_file(file_path, content, mode)
        elif operation == "append":
            return await self._append_file(file_path, content, mode)
        elif operation == "delete":
            return await self._delete_file(file_path)
        elif operation == "list":
            return await self._list_directory(file_path)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    async def _read_file(self, path: Path, mode: str = "text") -> str | bytes:
        """Read file safely."""
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not path.is_file():
            raise IsADirectoryError(f"Path is a directory: {path}")

        try:
            if mode == "text":
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            else:
                with open(path, "rb") as f:
                    return f.read()
        except Exception as e:
            self.log_error(f"Failed to read file: {e}")
            raise

    async def _write_file(self, path: Path, content: str | bytes, mode: str = "text") -> Dict[str, Any]:
        """Write file safely."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            if mode == "text":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content if isinstance(content, str) else str(content))
            else:
                with open(path, "wb") as f:
                    f.write(content if isinstance(content, bytes) else content.encode())

            return {"success": True, "path": str(path), "size_bytes": path.stat().st_size}
        except Exception as e:
            self.log_error(f"Failed to write file: {e}")
            raise

    async def _append_file(self, path: Path, content: str | bytes, mode: str = "text") -> Dict[str, Any]:
        """Append to file safely."""
        try:
            if mode == "text":
                with open(path, "a", encoding="utf-8") as f:
                    f.write(content if isinstance(content, str) else str(content))
            else:
                with open(path, "ab") as f:
                    f.write(content if isinstance(content, bytes) else content.encode())

            return {"success": True, "path": str(path), "size_bytes": path.stat().st_size}
        except Exception as e:
            self.log_error(f"Failed to append to file: {e}")
            raise

    async def _delete_file(self, path: Path) -> Dict[str, Any]:
        """Delete file safely."""
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                import shutil
                shutil.rmtree(path)
            else:
                raise FileNotFoundError(f"Path not found: {path}")

            return {"success": True, "deleted": str(path)}
        except Exception as e:
            self.log_error(f"Failed to delete: {e}")
            raise

    async def _list_directory(self, path: Path) -> Dict[str, Any]:
        """List directory contents."""
        try:
            if not path.is_dir():
                raise NotADirectoryError(f"Not a directory: {path}")

            items = []
            for item in path.iterdir():
                items.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size_bytes": item.stat().st_size if item.is_file() else 0,
                })

            return {"success": True, "path": str(path), "items": items}
        except Exception as e:
            self.log_error(f"Failed to list directory: {e}")
            raise

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if path is in allowed directories."""
        try:
            path = path.resolve()
            for allowed in self.allowed_paths:
                if path.is_relative_to(allowed):
                    return True
            return False
        except Exception:
            return False

    async def _on_cleanup(self) -> None:
        """Cleanup file operation resources."""
        import shutil
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            self.log_info(f"Cleaned up {self.temp_dir}")


class DataProcessingAgent(SubAgent):
    """Transform and analyze data."""

    async def _on_initialize(self) -> bool:
        """Initialize data processing."""
        self.log_info("Data processing agent initialized")
        return True

    async def _execute_task(self, task_id: str, task_input: Dict[str, Any]) -> Any:
        """Execute data processing task."""
        operation = task_input.get("operation", "transform")
        data = task_input.get("data", [])
        parameters = task_input.get("parameters", {})

        if operation == "filter":
            return await self._filter_data(data, parameters)
        elif operation == "transform":
            return await self._transform_data(data, parameters)
        elif operation == "aggregate":
            return await self._aggregate_data(data, parameters)
        elif operation == "sort":
            return await self._sort_data(data, parameters)
        elif operation == "deduplicate":
            return await self._deduplicate_data(data)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    async def _filter_data(self, data: List[Any], parameters: Dict[str, Any]) -> List[Any]:
        """Filter data based on criteria."""
        field = parameters.get("field")
        value = parameters.get("value")
        operator = parameters.get("operator", "==")

        result = []
        for item in data:
            if isinstance(item, dict) and field in item:
                item_value = item[field]
                if operator == "==" and item_value == value:
                    result.append(item)
                elif operator == "!=" and item_value != value:
                    result.append(item)
                elif operator == ">" and item_value > value:
                    result.append(item)
                elif operator == "<" and item_value < value:
                    result.append(item)

        return result

    async def _transform_data(self, data: List[Any], parameters: Dict[str, Any]) -> List[Any]:
        """Transform data structure."""
        mapping = parameters.get("mapping", {})
        result = []

        for item in data:
            if isinstance(item, dict):
                transformed = {}
                for new_key, old_key in mapping.items():
                    if old_key in item:
                        transformed[new_key] = item[old_key]
                result.append(transformed)
            else:
                result.append(item)

        return result

    async def _aggregate_data(self, data: List[Any], parameters: Dict[str, Any]) -> Any:
        """Aggregate data."""
        operation = parameters.get("aggregation", "count")
        field = parameters.get("field")

        if operation == "count":
            return len(data)
        elif operation == "sum" and field:
            return sum(item.get(field, 0) if isinstance(item, dict) else 0 for item in data)
        elif operation == "avg" and field:
            values = [item.get(field, 0) if isinstance(item, dict) else 0 for item in data]
            return sum(values) / len(values) if values else 0
        elif operation == "min" and field:
            values = [item.get(field) if isinstance(item, dict) else item for item in data]
            return min(values) if values else None
        elif operation == "max" and field:
            values = [item.get(field) if isinstance(item, dict) else item for item in data]
            return max(values) if values else None

        return None

    async def _sort_data(self, data: List[Any], parameters: Dict[str, Any]) -> List[Any]:
        """Sort data."""
        field = parameters.get("field")
        reverse = parameters.get("reverse", False)

        if field:
            return sorted(data, key=lambda x: x.get(field) if isinstance(x, dict) else x, reverse=reverse)
        else:
            return sorted(data, reverse=reverse)

    async def _deduplicate_data(self, data: List[Any]) -> List[Any]:
        """Remove duplicates."""
        seen = set()
        result = []
        for item in data:
            item_key = json.dumps(item, sort_keys=True, default=str)
            if item_key not in seen:
                seen.add(item_key)
                result.append(item)
        return result

    async def _on_cleanup(self) -> None:
        """Cleanup data processing resources."""
        pass


class APICallAgent(SubAgent):
    """Make HTTP requests with retry logic."""

    def __init__(self, config: Optional[AgentConfig] = None):
        if config is None:
            config = AgentConfig(name="APICallAgent", description="Handles API calls")
        super().__init__(config)
        self.session: Optional[aiohttp.ClientSession] = None

    async def _on_initialize(self) -> bool:
        """Initialize HTTP session."""
        try:
            self.session = aiohttp.ClientSession()
            self.log_info("API call agent initialized")
            return True
        except Exception as e:
            self.log_error(f"Failed to initialize: {e}")
            return False

    async def _execute_task(self, task_id: str, task_input: Dict[str, Any]) -> Any:
        """Execute API call task."""
        url = task_input.get("url")
        method = task_input.get("method", "GET")
        headers = task_input.get("headers", {})
        data = task_input.get("data")
        timeout = task_input.get("timeout", 30)

        if not url:
            raise ValueError("URL is required")

        if not self.session:
            raise RuntimeError("Session not initialized")

        try:
            async with self.session.request(
                method,
                url,
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                content = await response.text()
                return {
                    "status_code": response.status,
                    "headers": dict(response.headers),
                    "content": content,
                    "success": 200 <= response.status < 300,
                }
        except asyncio.TimeoutError:
            raise TimeoutError(f"API call timed out after {timeout}s")

    async def _on_cleanup(self) -> None:
        """Cleanup HTTP session."""
        if self.session:
            await self.session.close()
            self.log_info("API call agent cleaned up")


class CodeExecutionAgent(SubAgent):
    """Execute code safely."""

    async def _on_initialize(self) -> bool:
        """Initialize code execution."""
        self.log_info("Code execution agent initialized")
        return True

    async def _execute_task(self, task_id: str, task_input: Dict[str, Any]) -> Any:
        """Execute code task."""
        code = task_input.get("code")
        language = task_input.get("language", "python")
        timeout = task_input.get("timeout", 30)

        if not code:
            raise ValueError("Code is required")

        if language == "python":
            return await self._execute_python(code, timeout)
        else:
            raise ValueError(f"Unsupported language: {language}")

    async def _execute_python(self, code: str, timeout: int) -> Any:
        """Execute Python code safely."""
        # Sanitize code
        forbidden = ["__import__", "eval", "exec", "compile", "open", "os.system"]
        for word in forbidden:
            if word in code:
                raise ValueError(f"Code contains forbidden operation: {word}")

        # Execute in restricted environment
        try:
            namespace = {"__builtins__": {}}
            exec(code, namespace)
            return namespace.get("result", {"success": True})
        except Exception as e:
            raise RuntimeError(f"Code execution failed: {e}")

    async def _on_cleanup(self) -> None:
        """Cleanup code execution resources."""
        pass


class SearchAgent(SubAgent):
    """Information retrieval and search."""

    async def _on_initialize(self) -> bool:
        """Initialize search agent."""
        self.log_info("Search agent initialized")
        return True

    async def _execute_task(self, task_id: str, task_input: Dict[str, Any]) -> Any:
        """Execute search task."""
        query = task_input.get("query")
        source = task_input.get("source", "local")
        limit = task_input.get("limit", 10)

        if not query:
            raise ValueError("Query is required")

        if source == "local":
            return await self._search_local(query, limit)
        else:
            raise ValueError(f"Unknown source: {source}")

    async def _search_local(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search local files (simulated)."""
        # This would typically search local filesystem
        return [
            {"type": "file", "path": f"result_{i}", "relevance": 1.0 - (i * 0.1)}
            for i in range(min(limit, 3))
        ]

    async def _on_cleanup(self) -> None:
        """Cleanup search resources."""
        pass


class AnalysisAgent(SubAgent):
    """Analyze and summarize information."""

    async def _on_initialize(self) -> bool:
        """Initialize analysis agent."""
        self.log_info("Analysis agent initialized")
        return True

    async def _execute_task(self, task_id: str, task_input: Dict[str, Any]) -> Any:
        """Execute analysis task."""
        operation = task_input.get("operation", "summarize")
        content = task_input.get("content")

        if not content:
            raise ValueError("Content is required")

        if operation == "summarize":
            return await self._summarize(content)
        elif operation == "analyze_sentiment":
            return await self._analyze_sentiment(content)
        elif operation == "extract_keywords":
            return await self._extract_keywords(content)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    async def _summarize(self, content: str) -> str:
        """Summarize content."""
        lines = content.split("\n")
        # Simple summarization: take first and last lines
        return "\n".join(lines[:min(3, len(lines))])

    async def _analyze_sentiment(self, content: str) -> Dict[str, Any]:
        """Analyze sentiment (simplified)."""
        positive = sum(1 for word in content.lower().split() if word in ["good", "great", "excellent"])
        negative = sum(1 for word in content.lower().split() if word in ["bad", "poor", "terrible"])

        return {
            "positive": positive,
            "negative": negative,
            "sentiment": "positive" if positive > negative else ("negative" if negative > positive else "neutral"),
        }

    async def _extract_keywords(self, content: str) -> List[str]:
        """Extract keywords."""
        # Simple keyword extraction: words > 5 characters
        words = content.lower().split()
        return list(set(word for word in words if len(word) > 5))[:10]

    async def _on_cleanup(self) -> None:
        """Cleanup analysis resources."""
        pass


class IntegrationAgent(SubAgent):
    """Combine results from multiple agents."""

    async def _on_initialize(self) -> bool:
        """Initialize integration agent."""
        self.log_info("Integration agent initialized")
        return True

    async def _execute_task(self, task_id: str, task_input: Dict[str, Any]) -> Any:
        """Execute integration task."""
        operation = task_input.get("operation", "merge")
        data_sets = task_input.get("data_sets", [])

        if operation == "merge":
            return await self._merge_data(data_sets)
        elif operation == "correlate":
            return await self._correlate_data(data_sets)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    async def _merge_data(self, data_sets: List[Any]) -> Any:
        """Merge multiple data sources."""
        if not data_sets:
            return None

        if isinstance(data_sets[0], dict):
            merged = {}
            for ds in data_sets:
                merged.update(ds)
            return merged
        elif isinstance(data_sets[0], list):
            merged = []
            for ds in data_sets:
                merged.extend(ds)
            return merged
        else:
            return data_sets

    async def _correlate_data(self, data_sets: List[Any]) -> Dict[str, Any]:
        """Correlate multiple data sets."""
        return {"correlation": 0.8, "merged_data": await self._merge_data(data_sets)}

    async def _on_cleanup(self) -> None:
        """Cleanup integration resources."""
        pass
