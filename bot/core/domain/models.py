from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

class Environment(str, Enum):
    PRODUCTION = "production"
    DEVELOPMENT = "development"
    TESTING = "testing"

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

class AppConfig(BaseModel):
    """Master configuration model with safe defaults."""
    version: str = "18.0.0"
    app_name: str = "Elyan"
    environment: Environment = Environment.PRODUCTION
    agent: AgentConfig = Field(default_factory=lambda: AgentConfig())
    models: Dict[str, Any] = Field(default_factory=dict)
    channels: List[ChannelConfig] = Field(default_factory=list)
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
    security: Dict[str, Any] = Field(default_factory=dict)
    gateway: Dict[str, Any] = Field(default_factory=dict)
    skills: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")
