import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Ensure dummy .env for tests if needed
os.environ["FULL_DISK_ACCESS"] = "true"
os.environ["ELYAN_PORT"] = "18789"
