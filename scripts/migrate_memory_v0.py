import os
import json
import sqlite3
from pathlib import Path

def migrate_memory():
    home_elyan = Path.home() / ".elyan"
    memory_dir = home_elyan / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    
    # Audit and quality DBs migration (simulated or simplified for now)
    # We will mainly create the markdown structure as requested
    
    paths = {
        "preferences": memory_dir / "preferences.md",
        "patterns": memory_dir / "patterns.md",
        "history": memory_dir / "history.md"
    }
    
    for name, path in paths.items():
        if not path.exists():
            path.write_text(f"# Elyan {name.capitalize()}

", encoding="utf-8")

if __name__ == "__main__":
    migrate_memory()
