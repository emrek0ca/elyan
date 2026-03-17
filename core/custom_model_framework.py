"""
Custom Model Support Framework - Fine-tuning and deployment of custom models
Supports PEFT, QLoRA, and model serving infrastructure
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class ModelType(Enum):
    """Supported model types"""
    TRANSFORMER = "transformer"
    INSTRUCTION_TUNED = "instruction_tuned"
    CHAT = "chat"
    CODE = "code"
    MULTILINGUAL = "multilingual"


class TrainingMethod(Enum):
    """Training methods"""
    FULL_FINE_TUNE = "full_fine_tune"
    PEFT_LORA = "peft_lora"
    QLORA = "qlora"
    PREFIX_TUNING = "prefix_tuning"


@dataclass
class TrainingConfig:
    """Training configuration"""
    base_model: str
    method: TrainingMethod = TrainingMethod.PEFT_LORA
    learning_rate: float = 1e-4
    num_epochs: int = 3
    batch_size: int = 32
    max_steps: int = 1000
    warmup_steps: int = 100
    weight_decay: float = 0.01
    gradient_accumulation_steps: int = 4
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_model": self.base_model,
            "method": self.method.value if isinstance(self.method, TrainingMethod) else self.method,
            "learning_rate": self.learning_rate,
            "num_epochs": self.num_epochs,
            "batch_size": self.batch_size,
            "max_steps": self.max_steps,
            "warmup_steps": self.warmup_steps,
            "weight_decay": self.weight_decay,
            "gradient_accumulation_steps": self.gradient_accumulation_steps,
            "lora_r": self.lora_r,
            "lora_alpha": self.lora_alpha,
            "lora_dropout": self.lora_dropout
        }


@dataclass
class TrainingData:
    """Training dataset"""
    examples: List[Dict[str, str]]  # Each: {input, output, instruction}
    validation_split: float = 0.1
    test_split: float = 0.1

    def get_splits(self) -> Tuple[List, List, List]:
        """Get train/val/test splits"""
        import random
        random.shuffle(self.examples)
        n = len(self.examples)
        val_size = int(n * self.validation_split)
        test_size = int(n * self.test_split)

        test = self.examples[:test_size]
        val = self.examples[test_size:test_size + val_size]
        train = self.examples[test_size + val_size:]
        return train, val, test

    def to_dict(self) -> Dict[str, Any]:
        return {
            "num_examples": len(self.examples),
            "validation_split": self.validation_split,
            "test_split": self.test_split
        }


@dataclass
class ModelMetadata:
    """Custom model metadata"""
    model_id: str
    name: str
    description: str
    base_model: str
    model_type: ModelType
    training_method: TrainingMethod
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    version: str = "1.0.0"
    training_config: Optional[Dict] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    status: str = "created"  # created, training, ready, failed

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Convert Enums to their values
        data["model_type"] = self.model_type.value if isinstance(self.model_type, ModelType) else self.model_type
        data["training_method"] = self.training_method.value if isinstance(self.training_method, TrainingMethod) else self.training_method
        return data

    def save(self, path: Path):
        """Save metadata to file"""
        with open(path / "metadata.json", "w") as f:
            json.dump(self.to_dict(), f, indent=2)


@dataclass
class TrainingMetrics:
    """Training metrics"""
    step: int
    loss: float
    validation_loss: Optional[float] = None
    learning_rate: float = 0.0
    tokens_per_second: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ModelVersion:
    """Represents a specific model version"""

    def __init__(self, model_id: str, version: str, path: Path):
        self.model_id = model_id
        self.version = version
        self.path = path
        self.created_at = time.time()
        self.metadata: Optional[ModelMetadata] = None

    def load_metadata(self):
        """Load metadata from disk"""
        metadata_file = self.path / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file) as f:
                data = json.load(f)
                # Reconstruct metadata
                self.metadata = ModelMetadata(**data)

    def get_adapter_path(self) -> Optional[Path]:
        """Get path to LoRA adapters"""
        adapter_path = self.path / "adapters"
        return adapter_path if adapter_path.exists() else None

    def __repr__(self) -> str:
        return f"<ModelVersion {self.model_id}:{self.version}>"


class ModelTrainer:
    """Train custom models"""

    def __init__(self, storage_path: str = ".elyan/models"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.training_jobs: Dict[str, Dict] = {}
        self.lock = threading.RLock()

    def start_training(self, model_id: str, training_data: TrainingData,
                      config: TrainingConfig) -> str:
        """Start a training job"""
        job_id = f"{model_id}_{int(time.time())}"

        with self.lock:
            self.training_jobs[job_id] = {
                "model_id": model_id,
                "status": "queued",
                "start_time": time.time(),
                "config": config,
                "metrics": []
            }

        # Create model directory
        model_dir = self.storage_path / model_id
        model_dir.mkdir(exist_ok=True)

        logger.info(f"Training job {job_id} queued for {model_id}")
        return job_id

    def record_training_step(self, job_id: str, metrics: TrainingMetrics):
        """Record training metrics"""
        with self.lock:
            if job_id in self.training_jobs:
                self.training_jobs[job_id]["metrics"].append(metrics.to_dict())
                self.training_jobs[job_id]["status"] = "training"

    def complete_training(self, job_id: str, success: bool, error: Optional[str] = None):
        """Mark training as complete"""
        with self.lock:
            if job_id in self.training_jobs:
                self.training_jobs[job_id]["status"] = "success" if success else "failed"
                self.training_jobs[job_id]["end_time"] = time.time()
                if error:
                    self.training_jobs[job_id]["error"] = error

    def get_training_status(self, job_id: str) -> Dict[str, Any]:
        """Get training job status"""
        with self.lock:
            if job_id not in self.training_jobs:
                return {"error": "Job not found"}

            job = self.training_jobs[job_id]
            duration = job.get("end_time", time.time()) - job["start_time"]

            return {
                "job_id": job_id,
                "model_id": job["model_id"],
                "status": job["status"],
                "duration_seconds": duration,
                "num_steps": len(job["metrics"]),
                "latest_loss": job["metrics"][-1]["loss"] if job["metrics"] else None,
                "metrics": job["metrics"][-10:]  # Last 10 steps
            }


class ModelRegistry:
    """Registry of available custom models"""

    def __init__(self, storage_path: str = ".elyan/models"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.models: Dict[str, List[ModelVersion]] = {}
        self.lock = threading.RLock()
        self._load_registry()

    def register_model(self, metadata: ModelMetadata, version_path: Path):
        """Register a new model version"""
        with self.lock:
            model_version = ModelVersion(
                metadata.model_id,
                metadata.version,
                version_path
            )
            model_version.metadata = metadata

            if metadata.model_id not in self.models:
                self.models[metadata.model_id] = []

            self.models[metadata.model_id].append(model_version)
            metadata.save(version_path)

            logger.info(f"Registered {metadata.model_id}:{metadata.version}")

    def get_model_version(self, model_id: str,
                         version: Optional[str] = None) -> Optional[ModelVersion]:
        """Get a specific model version"""
        with self.lock:
            if model_id not in self.models:
                return None

            versions = self.models[model_id]
            if not version:
                return versions[-1] if versions else None

            for v in versions:
                if v.version == version:
                    return v
            return None

    def list_models(self) -> Dict[str, List[Dict]]:
        """List all registered models"""
        with self.lock:
            result = {}
            for model_id, versions in self.models.items():
                result[model_id] = [
                    {
                        "version": v.version,
                        "created_at": v.created_at,
                        "status": v.metadata.status if v.metadata else "unknown"
                    }
                    for v in versions
                ]
            return result

    def list_model_versions(self, model_id: str) -> List[Dict]:
        """List versions of a specific model"""
        with self.lock:
            if model_id not in self.models:
                return []

            return [
                {
                    "version": v.version,
                    "created_at": v.created_at,
                    "path": str(v.path),
                    "metadata": v.metadata.to_dict() if v.metadata else None
                }
                for v in self.models[model_id]
            ]

    def _load_registry(self):
        """Load existing models from disk"""
        if not self.storage_path.exists():
            return

        for model_dir in self.storage_path.iterdir():
            if not model_dir.is_dir():
                continue

            metadata_file = model_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        data = json.load(f)
                        metadata = ModelMetadata(**data)
                        version = ModelVersion(metadata.model_id, metadata.version, model_dir)
                        version.metadata = metadata

                        if metadata.model_id not in self.models:
                            self.models[metadata.model_id] = []
                        self.models[metadata.model_id].append(version)
                except Exception as e:
                    logger.error(f"Failed to load model {model_dir}: {e}")


class ModelDeployer:
    """Deploy custom models for inference"""

    def __init__(self, registry: ModelRegistry):
        self.registry = registry
        self.deployed_models: Dict[str, Any] = {}
        self.lock = threading.RLock()

    def deploy_model(self, model_id: str, version: Optional[str] = None) -> bool:
        """Deploy a model for inference"""
        model_version = self.registry.get_model_version(model_id, version)
        if not model_version:
            logger.error(f"Model {model_id}:{version} not found")
            return False

        with self.lock:
            self.deployed_models[model_id] = {
                "version": model_version.version,
                "path": str(model_version.path),
                "metadata": model_version.metadata.to_dict() if model_version.metadata else None,
                "deployed_at": time.time()
            }

        logger.info(f"Deployed {model_id}:{model_version.version}")
        return True

    def undeploy_model(self, model_id: str) -> bool:
        """Undeploy a model"""
        with self.lock:
            if model_id in self.deployed_models:
                del self.deployed_models[model_id]
                logger.info(f"Undeployed {model_id}")
                return True
        return False

    def get_deployed_models(self) -> Dict[str, Any]:
        """Get list of deployed models"""
        with self.lock:
            return dict(self.deployed_models)

    def invoke_model(self, model_id: str, input_text: str) -> Optional[str]:
        """Invoke a deployed model"""
        with self.lock:
            if model_id not in self.deployed_models:
                logger.error(f"Model {model_id} not deployed")
                return None

            # This would normally load the model and run inference
            # For now, return placeholder
            return f"<inference from {model_id}>"


class CustomModelFramework:
    """Main custom model framework"""

    def __init__(self, storage_path: str = ".elyan/models"):
        self.storage_path = Path(storage_path)
        self.registry = ModelRegistry(str(storage_path))
        self.trainer = ModelTrainer(str(storage_path))
        self.deployer = ModelDeployer(self.registry)

    def create_and_train_model(self, model_id: str, name: str,
                              base_model: str, training_data: TrainingData,
                              config: Optional[TrainingConfig] = None) -> str:
        """Create and start training a custom model"""
        if config is None:
            config = TrainingConfig(base_model=base_model)

        # Create metadata
        metadata = ModelMetadata(
            model_id=model_id,
            name=name,
            description=f"Custom fine-tuned model based on {base_model}",
            base_model=base_model,
            model_type=ModelType.INSTRUCTION_TUNED,
            training_method=config.method,
            training_config=config.to_dict(),
            status="training"
        )

        # Create version directory
        version_dir = self.storage_path / model_id / "v1.0.0"
        version_dir.mkdir(parents=True, exist_ok=True)

        # Register model
        self.registry.register_model(metadata, version_dir)

        # Start training
        job_id = self.trainer.start_training(model_id, training_data, config)
        return job_id

    def get_status(self) -> Dict[str, Any]:
        """Get framework status"""
        return {
            "timestamp": datetime.now().isoformat(),
            "registered_models": self.registry.list_models(),
            "deployed_models": list(self.deployer.get_deployed_models().keys()),
            "storage_path": str(self.storage_path)
        }

    def __repr__(self) -> str:
        return "<CustomModelFramework>"
