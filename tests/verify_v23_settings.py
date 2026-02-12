import asyncio
import os
import json
import shutil
from pathlib import Path
from config.settings_manager import SettingsPanel, DEFAULT_SETTINGS

def test_migration():
    print("--- Testing Settings Migration ---")
    old_dir = Path.home() / ".config" / "wiqo-bot"
    old_dir.mkdir(parents=True, exist_ok=True)
    old_file = old_dir / "settings.json"
    
    new_dir = Path.home() / ".wiqo"
    new_file = new_dir / "settings.json"
    
    # Backup existing new settings if any
    backup = None
    if new_file.exists():
        backup = new_file.with_suffix(".bak")
        shutil.move(new_file, backup)
    
    # Create old settings
    test_data = {"bot_name": "Migrated Bot", "telegram_token": "test_token"}
    with open(old_file, "w") as f:
        json.dump(test_data, f)
    
    try:
        manager = SettingsPanel()
        print(f"Loaded bot_name: {manager.get('bot_name')}")
        assert manager.get("bot_name") == "Migrated Bot"
        assert manager.get("telegram_token") == "test_token"
        assert new_file.exists()
        print("SUCCESS: Migration successful!")
    finally:
        # Cleanup
        if old_file.exists(): old_file.unlink()
        if backup and backup.exists():
            shutil.move(backup, new_file)

def test_defaults():
    print("\n--- Testing Default Settings ---")
    manager = SettingsPanel()
    assert manager.get("autonomy_level") == "Balanced"
    assert manager.get("vision_frequency") == 30
    print("SUCCESS: Default settings correct!")

if __name__ == "__main__":
    test_migration()
    test_defaults()
    print("\nVerification Complete.")
