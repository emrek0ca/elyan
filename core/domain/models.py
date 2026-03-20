from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from core.version import APP_VERSION

class Environment(str, Enum):
    PRODUCTION = "production"
    DEVELOPMENT = "development"
    TESTING = "testing"

class SubscriptionTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"

class AgentConfig(BaseModel):
    autonomous: bool = True
    personality: str = "professional"
    language: str = "tr"
    model_config = ConfigDict(extra="allow")

class ChannelConfig(BaseModel):
    type: str
    enabled: bool = True
    token: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(extra="allow")

class VoiceConfig(BaseModel):
    feedback_enabled: bool = True
    volume: int = 100
    model_config = ConfigDict(extra="allow")

class CodingConfig(BaseModel):
    max_files_per_project: int = 10
    model_config = ConfigDict(extra="allow")

class SubscriptionConfig(BaseModel):
    enabled: bool = False
    default_tier: SubscriptionTier = SubscriptionTier.FREE
    tiers: Dict[SubscriptionTier, Dict[str, Any]] = Field(
        default_factory=lambda: {
            SubscriptionTier.FREE: {
                "max_messages_daily": 20,
                "max_tokens_monthly": 100000,
                "max_storage_gb": 1,
                "advanced_models": False,
                "research_allowed": False,
            },
            SubscriptionTier.PRO: {
                "max_messages_daily": 500,
                "max_tokens_monthly": 5000000,
                "max_storage_gb": 50,
                "advanced_models": True,
                "research_allowed": True,
            },
            SubscriptionTier.ENTERPRISE: {
                "max_messages_daily": 10000,
                "max_tokens_monthly": 100000000,
                "max_storage_gb": 500,
                "advanced_models": True,
                "research_allowed": True,
            },
        }
    )

class AppConfig(BaseModel):
    """Master configuration model with safe defaults."""
    version: str = APP_VERSION
    app_name: str = "Elyan"
    environment: Environment = Environment.PRODUCTION
    agent: AgentConfig = Field(default_factory=lambda: AgentConfig())
    models: Dict[str, Any] = Field(default_factory=dict)
    channels: List[ChannelConfig] = Field(default_factory=list)
    subscriptions: SubscriptionConfig = Field(default_factory=SubscriptionConfig)
    tools: Dict[str, Any] = Field(default_factory=dict)
    sandbox: Dict[str, Any] = Field(default_factory=dict)
    cron: List[Dict[str, Any]] = Field(default_factory=list)
    heartbeat: Dict[str, Any] = Field(default_factory=dict)
    memory: Dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "path": "~/.elyan/memory/",
            "maxSizeMB": 500,
            "maxUserStorageGB": 10,
            "localOnly": True,
        }
    )
    personalization: Dict[str, Any] = Field(default_factory=dict)
    ml: Dict[str, Any] = Field(default_factory=dict)
    evaluation: Dict[str, Any] = Field(default_factory=dict)
    adapter_training: Dict[str, Any] = Field(default_factory=dict)
    retrieval: Dict[str, Any] = Field(default_factory=dict)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    coding: CodingConfig = Field(default_factory=CodingConfig)
    security: Dict[str, Any] = Field(default_factory=dict)
    gateway: Dict[str, Any] = Field(default_factory=dict)
    skills: Dict[str, Any] = Field(default_factory=dict)
    monthly_budget_usd: float = 20.0
    cost_limit_usd: float = 50.0

    model_config = ConfigDict(extra="allow")
