import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger("canvas_engine")

class CanvasEngine:
    """Manages visual workspace data for Kanban, Charts, etc."""
    
    def __init__(self):
        self.data_dir = Path.home() / ".elyan" / "canvas"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.active_views: Dict[str, Dict] = {}

    def _get_view_path(self, view_id: str) -> Path:
        return self.data_dir / f"{view_id}.json"

    def create_view(self, view_type: str, title: str, data: Any) -> str:
        """Create a new visual view and return its ID."""
        view_id = f"{view_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        view_data = {
            "id": view_id,
            "type": view_type,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "data": data
        }
        
        path = self._get_view_path(view_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(view_data, f, indent=2, ensure_ascii=False)
            
        self.active_views[view_id] = view_data
        logger.info(f"Canvas view created: {view_id} ({view_type})")
        return view_id

    def get_view(self, view_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_view_path(view_id)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return self.active_views.get(view_id)

    def list_views(self) -> List[Dict[str, Any]]:
        views = []
        for p in self.data_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    views.append(json.load(f))
            except: pass
        return views

# Global instance
canvas_engine = CanvasEngine()
