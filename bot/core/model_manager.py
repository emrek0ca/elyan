"""
Centralized Model Manager for Elyan (v17.0)
Ensures expensive models are loaded once and shared across components.
"""
import asyncio
import contextlib
import io
import os
import warnings
from typing import Optional, Any
from utils.logger import get_logger

logger = get_logger("model_manager")

class ModelManager:
    _instance = None
    _model: Optional[Any] = None
    _loading_lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelManager, cls).__new__(cls)
        return cls._instance

    async def get_embedding_model(self) -> Optional[Any]:
        """Load or return the shared embedding model"""
        if self._model:
            return self._model

        async with self._loading_lock:
            if self._model: # Double check after lock
                return self._model

            try:
                os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
                os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
                warnings.filterwarnings(
                    "ignore",
                    message=".*unauthenticated requests to the HF Hub.*",
                )

                from sentence_transformers import SentenceTransformer
                try:
                    from transformers.utils import logging as hf_logging
                    hf_logging.set_verbosity_error()
                except Exception:
                    pass

                logger.info("Shared embedding model starting to load (sentence-transformers/all-MiniLM-L6-v2)")
                # Suppress noisy third-party stdout/stderr during model materialization.
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self._model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
                logger.info("Shared embedding model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load shared embedding model: {e}")
                self._model = None
            
            return self._model

# Global singleton accessor
_manager = ModelManager()

async def get_shared_embedder():
    return await _manager.get_embedding_model()
