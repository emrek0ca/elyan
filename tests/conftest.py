import sys
import os
from pathlib import Path

# Add project root to sys.path before any repo imports.
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.dependencies.autoinstall_hook import activate as _activate_autoinstall_hook

_activate_autoinstall_hook()

import pytest

from core.quota import quota_manager
from core.subscription import subscription_manager

# Ensure dummy .env for tests if needed
os.environ["FULL_DISK_ACCESS"] = "true"
os.environ["ELYAN_PORT"] = "18789"


@pytest.fixture(autouse=True)
def _isolate_usage_state(tmp_path):
    original_quota_path = quota_manager.db_path
    original_quota_usage = quota_manager._usage
    original_subscription_path = subscription_manager.db_path
    original_subscription_users = subscription_manager._users

    quota_manager.db_path = tmp_path / "user_usage.json"
    quota_manager._usage = {}
    subscription_manager.db_path = tmp_path / "subscriptions.json"
    subscription_manager._users = {}
    try:
        yield
    finally:
        quota_manager.db_path = original_quota_path
        quota_manager._usage = original_quota_usage
        subscription_manager.db_path = original_subscription_path
        subscription_manager._users = original_subscription_users
