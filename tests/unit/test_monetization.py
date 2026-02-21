
import pytest
from core.subscription import SubscriptionManager
from core.quota import QuotaManager
from core.domain.models import SubscriptionTier
from config.elyan_config import elyan_config
from unittest.mock import MagicMock, patch

@pytest.fixture
def sub_manager():
    """Isolated subscription manager."""
    with patch("core.subscription.SUBSCRIPTION_FILE") as mock_path:
        mock_path.exists.return_value = False
        manager = SubscriptionManager()
        return manager

@pytest.fixture
def quota_manager_obj():
    """Isolated quota manager."""
    with patch("core.quota.QUOTA_FILE") as mock_path:
        mock_path.exists.return_value = False
        manager = QuotaManager()
        return manager

def test_default_tier(sub_manager):
    assert sub_manager.get_user_tier("new_user") == SubscriptionTier.FREE

def test_set_user_tier(sub_manager):
    sub_manager.set_user_tier("pro_user", SubscriptionTier.PRO)
    assert sub_manager.get_user_tier("pro_user") == SubscriptionTier.PRO

def test_check_feature_allowed(sub_manager):
    sub_manager.set_user_tier("free_user", SubscriptionTier.FREE)
    sub_manager.set_user_tier("pro_user", SubscriptionTier.PRO)
    
    # Advanced models should be False for free, True for Pro (based on our default config)
    assert sub_manager.check_feature_allowed("free_user", "advanced_models") is False
    assert sub_manager.check_feature_allowed("pro_user", "advanced_models") is True

def test_quota_check_within_limits(quota_manager_obj):
    # Ensure subscriptions enabled for testing
    with patch.object(elyan_config.config.subscriptions, "enabled", True):
        # Record 5 messages for a free user (limit is 20)
        for _ in range(5):
            quota_manager_obj.record_message("user1", tokens=100)
        
        result = quota_manager_obj.check_quota("user1")
        assert result["allowed"] is True
        assert result["reason"] == "within_limits"

def test_quota_check_exceeded_messages(quota_manager_obj):
    with patch.object(elyan_config.config.subscriptions, "enabled", True):
        # Record 21 messages for a free user (limit is 20)
        for _ in range(21):
            quota_manager_obj.record_message("user2", tokens=10)
        
        result = quota_manager_obj.check_quota("user2")
        assert result["allowed"] is False
        assert result["reason"] == "daily_message_limit_reached"
        assert result["limit"] == 20

def test_quota_check_exceeded_tokens(quota_manager_obj):
    with patch.object(elyan_config.config.subscriptions, "enabled", True):
        # Record a message with 150,000 tokens (limit is 100,000)
        quota_manager_obj.record_message("user3", tokens=150000)
        
        result = quota_manager_obj.check_quota("user3")
        assert result["allowed"] is False
        assert result["reason"] == "monthly_token_limit_reached"

def test_pro_user_higher_limits(quota_manager_obj, sub_manager):
    with patch.object(elyan_config.config.subscriptions, "enabled", True):
        with patch("core.quota.subscription_manager", sub_manager):
            sub_manager.set_user_tier("pro_user", SubscriptionTier.PRO)
            
            # Record 50 messages (Free limit 20, Pro limit 500)
            for _ in range(50):
                quota_manager_obj.record_message("pro_user", tokens=100)
            
            result = quota_manager_obj.check_quota("pro_user")
            assert result["allowed"] is True
