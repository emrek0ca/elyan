"""Background Research - Long-running research tasks"""

import asyncio
from typing import Any, Dict
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("web.research")

# Active research tasks
_research_tasks: Dict[str, dict] = {}

# Maximum concurrent research tasks
MAX_CONCURRENT_TASKS = 3


async def start_research(
    topic: str,
    depth: str = "basic",
    task_id: str = None
) -> dict[str, Any]:
    """Start a background research task

    Args:
        topic: Research topic/question
        depth: Research depth - "basic" (1-2 sources), "moderate" (3-5), "deep" (5-10)
        task_id: Optional custom task ID

    Returns:
        Task status with task_id to check progress
    """
    try:
        # Check concurrent task limit
        active_count = sum(1 for t in _research_tasks.values() if t.get("status") == "running")
        if active_count >= MAX_CONCURRENT_TASKS:
            return {
                "success": False,
                "error": f"Maksimum eşzamanlı araştırma sayısına ({MAX_CONCURRENT_TASKS}) ulaşıldı"
            }

        # Generate task ID
        if not task_id:
            task_id = f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Determine source count based on depth
        depth_config = {
            "basic": {"sources": 2, "fetch_content": False},
            "moderate": {"sources": 5, "fetch_content": True},
            "deep": {"sources": 10, "fetch_content": True}
        }
        config = depth_config.get(depth, depth_config["basic"])

        # Create task record
        _research_tasks[task_id] = {
            "task_id": task_id,
            "topic": topic,
            "depth": depth,
            "status": "running",
            "progress": 0,
            "started_at": datetime.now().isoformat(),
            "results": None,
            "error": None
        }

        # Start background task
        asyncio.create_task(_run_research(task_id, topic, config))

        logger.info(f"Started research task: {task_id} - {topic}")

        return {
            "success": True,
            "task_id": task_id,
            "status": "running",
            "message": f"Araştırma başlatıldı: {topic}"
        }

    except Exception as e:
        logger.error(f"Start research error: {e}")
        return {"success": False, "error": str(e)}


async def _run_research(task_id: str, topic: str, config: dict):
    """Run the actual research task"""
    try:
        from .search_engine import web_search
        from .web_scraper import fetch_page

        task = _research_tasks[task_id]

        # Step 1: Search for sources
        task["progress"] = 10
        search_result = await web_search(topic, num_results=config["sources"])

        if not search_result.get("success"):
            task["status"] = "failed"
            task["error"] = search_result.get("error", "Arama başarısız")
            return

        results = search_result.get("results", [])
        task["progress"] = 30

        # Step 2: Optionally fetch content from sources
        sources = []
        if config["fetch_content"] and results:
            for i, result in enumerate(results[:config["sources"]]):
                try:
                    fetch_result = await fetch_page(result["url"])
                    if fetch_result.get("success"):
                        sources.append({
                            "title": result.get("title", ""),
                            "url": result.get("url", ""),
                            "snippet": result.get("snippet", ""),
                            "content": fetch_result.get("content", "")[:2000]
                        })
                    else:
                        sources.append({
                            "title": result.get("title", ""),
                            "url": result.get("url", ""),
                            "snippet": result.get("snippet", ""),
                            "content": result.get("snippet", "")
                        })
                except Exception as e:
                    logger.warning(f"Failed to fetch {result.get('url')}: {e}")
                    sources.append({
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "snippet": result.get("snippet", ""),
                        "content": result.get("snippet", "")
                    })

                task["progress"] = 30 + int(50 * (i + 1) / len(results))
                await asyncio.sleep(0.5)  # Rate limiting
        else:
            sources = results

        task["progress"] = 80

        # Step 3: Compile summary
        summary = _compile_summary(topic, sources)

        task["progress"] = 100
        task["status"] = "completed"
        task["results"] = {
            "topic": topic,
            "summary": summary,
            "sources": sources,
            "source_count": len(sources)
        }
        task["completed_at"] = datetime.now().isoformat()

        logger.info(f"Research completed: {task_id}")

    except Exception as e:
        logger.error(f"Research error: {e}")
        task = _research_tasks.get(task_id)
        if task:
            task["status"] = "failed"
            task["error"] = str(e)


def _compile_summary(topic: str, sources: list) -> str:
    """Compile a summary from research sources"""
    if not sources:
        return f"{topic} hakkında bilgi bulunamadı."

    summary_parts = [f"📚 {topic} Araştırma Sonuçları\n{'─'*40}\n"]

    for i, source in enumerate(sources[:5], 1):
        title = source.get("title", "Başlıksız")
        snippet = source.get("snippet", source.get("content", ""))[:200]
        url = source.get("url", "")

        summary_parts.append(f"\n{i}. {title}")
        if snippet:
            summary_parts.append(f"   {snippet}...")
        if url:
            summary_parts.append(f"   🔗 {url}")

    summary_parts.append(f"\n{'─'*40}")
    summary_parts.append(f"Toplam {len(sources)} kaynak incelendi.")

    return "\n".join(summary_parts)


async def get_research_status(task_id: str) -> dict[str, Any]:
    """Get the status of a research task

    Args:
        task_id: The task ID returned by start_research
    """
    try:
        if task_id not in _research_tasks:
            return {
                "success": False,
                "error": f"Araştırma bulunamadı: {task_id}"
            }

        task = _research_tasks[task_id]

        result = {
            "success": True,
            "task_id": task_id,
            "topic": task.get("topic"),
            "status": task.get("status"),
            "progress": task.get("progress", 0),
            "started_at": task.get("started_at")
        }

        if task["status"] == "completed":
            result["results"] = task.get("results")
            result["completed_at"] = task.get("completed_at")
        elif task["status"] == "failed":
            result["error"] = task.get("error")

        return result

    except Exception as e:
        logger.error(f"Get status error: {e}")
        return {"success": False, "error": str(e)}


def list_research_tasks() -> list:
    """List all research tasks"""
    return [
        {
            "task_id": task_id,
            "topic": task.get("topic"),
            "status": task.get("status"),
            "progress": task.get("progress")
        }
        for task_id, task in _research_tasks.items()
    ]


def cleanup_completed_tasks(max_age_hours: int = 24):
    """Remove old completed tasks"""
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    to_remove = []

    for task_id, task in _research_tasks.items():
        if task["status"] in ("completed", "failed"):
            completed_at = task.get("completed_at") or task.get("started_at")
            if completed_at:
                task_time = datetime.fromisoformat(completed_at)
                if task_time < cutoff:
                    to_remove.append(task_id)

    for task_id in to_remove:
        del _research_tasks[task_id]

    return len(to_remove)
