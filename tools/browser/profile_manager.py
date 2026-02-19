import shutil
from pathlib import Path
from typing import List, Dict, Any

class BrowserProfileManager:
    """Manages isolated browser profiles."""
    
    def __init__(self):
        self.base_dir = Path.home() / ".elyan" / "browser" / "profiles"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_profile(self, name: str) -> str:
        profile_path = self.base_dir / name
        profile_path.mkdir(exist_ok=True)
        return str(profile_path)

    def delete_profile(self, name: str):
        profile_path = self.base_dir / name
        if profile_path.exists():
            shutil.rmtree(profile_path)

    def list_profiles(self) -> List[str]:
        return [d.name for d in self.base_dir.iterdir() if d.is_dir()]

    def get_profile_path(self, name: str) -> str:
        return str(self.base_dir / name)

# Global instance
browser_profiles = BrowserProfileManager()
