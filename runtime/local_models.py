from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _request_error_code(exc: requests.RequestException) -> str:
    if isinstance(exc, requests.Timeout):
        return "request_timeout"
    if isinstance(exc, requests.ConnectionError):
        return "provider_unreachable"
    return "provider_unreachable"


def _json_response(response: requests.Response) -> dict[str, Any] | None:
    try:
        payload = response.json() if response.text else {}
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else {}


def _base_runtime_status(*, provider_id: str, base_url: str, default_model: str) -> dict[str, Any]:
    configured = bool(str(default_model or "").strip())
    return {
        "providerId": provider_id,
        "available": False,
        "reachable": False,
        "configured": configured,
        "baseUrl": str(base_url or "").strip(),
        "defaultModel": str(default_model or "").strip(),
        "latencyMs": 0,
        "lastCheckedAt": "",
        "errorCode": "",
        "jobs": [],
    }


def _generate_id(prefix: str) -> str:
    import time
    from uuid import uuid4

    return f"{prefix}_{int(time.time() * 1000)}_{uuid4().hex[:8]}"


@dataclass
class ManagedJob:
    id: str
    kind: str
    command: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None
    process: subprocess.Popen[str] | None = None
    status: str = "queued"
    logs: list[str] = field(default_factory=list)
    exit_code: int | None = None
    error: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "command": self.command,
            "status": self.status,
            "logs": list(self.logs),
            "exitCode": self.exit_code,
            "error": self.error,
        }


class JobManager:
    def __init__(self):
        self._jobs: dict[str, ManagedJob] = {}
        self._lock = threading.RLock()

    def start_process(self, kind: str, command: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> ManagedJob:
        job = ManagedJob(id=_generate_id(kind), kind=kind, command=command, cwd=cwd, env=env)
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run_process, args=(job,), daemon=True)
        thread.start()
        return job

    def _run_process(self, job: ManagedJob) -> None:
        try:
            job.status = "running"
            job.process = subprocess.Popen(
                job.command,
                cwd=job.cwd,
                env=job.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert job.process.stdout is not None
            for line in job.process.stdout:
                stripped = line.rstrip()
                if stripped:
                    job.logs.append(stripped)
            job.exit_code = job.process.wait()
            job.status = "succeeded" if job.exit_code == 0 else "failed"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)

    def get(self, job_id: str) -> ManagedJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.snapshot() for job in self._jobs.values()]

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if not job:
            return {"ok": False, "error": "job_not_found"}
        if job.process and job.process.poll() is None:
            try:
                job.process.terminate()
                job.status = "canceled"
                return {"ok": True, "status": job.status}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "job_not_running"}


class OllamaClient:
    def __init__(self, base_url: str | None = None, default_model: str = ""):
        self.base_url = (base_url or os.environ.get("ELYAN_OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
        self.default_model = default_model.strip()
        self._jobs = JobManager()

    @property
    def binary(self) -> str | None:
        return shutil.which("ollama")

    def _tags_probe(self, timeout: float = 2.5) -> dict[str, Any]:
        started_at = time.perf_counter()
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=timeout)
        except requests.RequestException as exc:
            return {
                "ok": False,
                "reachable": False,
                "available": False,
                "latencyMs": _elapsed_ms(started_at),
                "lastCheckedAt": _utc_now_iso(),
                "errorCode": _request_error_code(exc),
                "models": [],
            }
        payload = _json_response(response)
        if payload is None:
            return {
                "ok": False,
                "reachable": bool(response.ok),
                "available": False,
                "latencyMs": _elapsed_ms(started_at),
                "lastCheckedAt": _utc_now_iso(),
                "errorCode": "invalid_response",
                "models": [],
            }
        models = payload.get("models", []) if isinstance(payload.get("models"), list) else []
        return {
            "ok": bool(response.ok),
            "reachable": bool(response.ok),
            "available": bool(response.ok),
            "latencyMs": _elapsed_ms(started_at),
            "lastCheckedAt": _utc_now_iso(),
            "errorCode": "" if response.ok else "provider_unreachable",
            "models": models,
        }

    def available(self) -> bool:
        return bool(self._tags_probe(timeout=2.5).get("available", False))

    def status(self) -> dict[str, Any]:
        probe = self._tags_probe(timeout=2.5)
        status = _base_runtime_status(provider_id="ollama", base_url=self.base_url, default_model=self.default_model)
        status.update(
            {
                "available": bool(probe.get("available", False)),
                "reachable": bool(probe.get("reachable", False)),
                "latencyMs": max(0, int(probe.get("latencyMs", 0) or 0)),
                "lastCheckedAt": str(probe.get("lastCheckedAt", "") or ""),
                "errorCode": str(probe.get("errorCode", "") or ""),
                "binary": self.binary,
                "jobs": self._jobs.list(),
            }
        )
        return status

    def list_models(self) -> dict[str, Any]:
        request_id = _generate_id("ollama_list")
        probe = self._tags_probe(timeout=5)
        if not probe.get("ok", False):
            return {
                "ok": False,
                "requestId": request_id,
                "error": str(probe.get("errorCode", "") or "provider_unreachable"),
                "models": [],
                "available": bool(probe.get("available", False)),
            }
        models = probe.get("models", [])
        normalised: list[dict[str, Any]] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            normalised.append(
                {
                    "name": str(item.get("name", "") or ""),
                    "size": int(item.get("size", 0) or 0),
                    "digest": str(item.get("digest", "") or ""),
                    "modifiedAt": str(item.get("modified_at", "") or ""),
                    "details": item.get("details") or {},
                }
            )
        normalised.sort(key=lambda row: row["name"].lower())
        return {
            "ok": True,
            "requestId": request_id,
            "available": True,
            "models": normalised,
        }

    def pull_model(self, model: str) -> dict[str, Any]:
        model = (model or self.default_model).strip()
        if not model:
            return {"ok": False, "error": "model_required"}
        if not self.binary:
            return {"ok": False, "error": "ollama_binary_missing"}
        job = self._jobs.start_process("ollama_pull", [self.binary, "pull", model])
        return {"ok": True, "job": job.snapshot()}

    def remove_model(self, model: str) -> dict[str, Any]:
        model = (model or self.default_model).strip()
        if not model:
            return {"ok": False, "error": "model_required"}
        if not self.binary:
            return {"ok": False, "error": "ollama_binary_missing"}
        job = self._jobs.start_process("ollama_rm", [self.binary, "rm", model])
        return {"ok": True, "job": job.snapshot()}

    def chat(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        model_name = (model or self.default_model).strip()
        if not model_name:
            return {"ok": False, "error": "model_required"}
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={"model": model_name, "messages": messages, "stream": False},
                timeout=60,
            )
        except requests.RequestException as exc:
            return {"ok": False, "error": _request_error_code(exc)}
        if not response.ok:
            return {"ok": False, "error": "provider_unreachable"}
        payload = _json_response(response)
        if payload is None:
            return {"ok": False, "error": "invalid_response"}
        message = payload.get("message", {}) if isinstance(payload, dict) else {}
        content = str(message.get("content", "") or "").strip()
        return {"ok": True, "content": content, "raw": payload}

    def jobs(self) -> list[dict[str, Any]]:
        return self._jobs.list()

    def job(self, job_id: str) -> dict[str, Any] | None:
        item = self._jobs.get(job_id)
        return item.snapshot() if item else None

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._jobs.cancel(job_id)

    def start_server(self) -> dict[str, Any]:
        if not self.binary:
            return {"ok": False, "error": "ollama_binary_missing"}
        job = self._jobs.start_process("ollama_serve", [self.binary, "serve"])
        return {"ok": True, "job": job.snapshot()}


class OpenAICompatibleLocalClient:
    def __init__(self, base_url: str, default_model: str = "", api_key: str = ""):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.default_model = default_model.strip()
        self.api_key = api_key.strip()

    def _models_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/models"
        return f"{self.base_url}/v1/models"

    def _chat_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _models_probe(self, timeout: float = 2.5) -> dict[str, Any]:
        started_at = time.perf_counter()
        try:
            response = requests.get(self._models_url(), headers=self._headers(), timeout=timeout)
        except requests.RequestException as exc:
            return {
                "ok": False,
                "available": False,
                "reachable": False,
                "latencyMs": _elapsed_ms(started_at),
                "lastCheckedAt": _utc_now_iso(),
                "errorCode": _request_error_code(exc),
                "models": [],
            }
        payload = _json_response(response)
        if payload is None:
            return {
                "ok": False,
                "available": False,
                "reachable": bool(response.ok),
                "latencyMs": _elapsed_ms(started_at),
                "lastCheckedAt": _utc_now_iso(),
                "errorCode": "invalid_response",
                "models": [],
            }
        models = payload.get("data", []) if isinstance(payload.get("data"), list) else []
        return {
            "ok": bool(response.ok),
            "available": bool(response.ok),
            "reachable": bool(response.ok),
            "latencyMs": _elapsed_ms(started_at),
            "lastCheckedAt": _utc_now_iso(),
            "errorCode": "" if response.ok else "provider_unreachable",
            "models": models,
        }

    def available(self) -> bool:
        return bool(self._models_probe(timeout=2.5).get("available", False))

    def status(self) -> dict[str, Any]:
        probe = self._models_probe(timeout=2.5)
        status = _base_runtime_status(provider_id="openai_compatible", base_url=self.base_url, default_model=self.default_model)
        status.update(
            {
                "available": bool(probe.get("available", False)),
                "reachable": bool(probe.get("reachable", False)),
                "latencyMs": max(0, int(probe.get("latencyMs", 0) or 0)),
                "lastCheckedAt": str(probe.get("lastCheckedAt", "") or ""),
                "errorCode": str(probe.get("errorCode", "") or ""),
            }
        )
        return status

    def list_models(self) -> dict[str, Any]:
        request_id = _generate_id("local_openai_list")
        probe = self._models_probe(timeout=5)
        if not probe.get("ok", False):
            return {
                "ok": False,
                "requestId": request_id,
                "error": str(probe.get("errorCode", "") or "provider_unreachable"),
                "models": [],
                "available": bool(probe.get("available", False)),
            }
        data = probe.get("models", [])
        models: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            models.append(
                {
                    "name": str(item.get("id", "") or item.get("name", "") or ""),
                    "ownedBy": str(item.get("owned_by", "") or ""),
                    "created": int(item.get("created", 0) or 0),
                    "raw": item,
                }
            )
        models.sort(key=lambda row: row["name"].lower())
        return {"ok": True, "requestId": request_id, "available": True, "models": models}

    def chat(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        model_name = (model or self.default_model).strip()
        if not model_name:
            return {"ok": False, "error": "model_required"}
        try:
            response = requests.post(
                self._chat_url(),
                headers=self._headers(),
                json={
                    "model": model_name,
                    "messages": messages,
                    "temperature": 0.2,
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            return {"ok": False, "error": _request_error_code(exc)}
        if not response.ok:
            return {"ok": False, "error": "provider_unreachable"}
        payload = _json_response(response)
        if payload is None:
            return {"ok": False, "error": "invalid_response"}
        choices = payload.get("choices", []) if isinstance(payload, dict) else []
        content = ""
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            if isinstance(message, dict):
                content = str(message.get("content", "") or "").strip()
        return {"ok": True, "content": content, "raw": payload}


class LMStudioClient(OpenAICompatibleLocalClient):
    def __init__(self, base_url: str | None = None, default_model: str = ""):
        super().__init__(
            base_url=(base_url or os.environ.get("ELYAN_LMSTUDIO_BASE_URL") or "http://127.0.0.1:1234/v1"),
            default_model=default_model,
        )

    def status(self) -> dict[str, Any]:
        payload = super().status()
        payload["providerId"] = "lmstudio"
        return payload


class LlamaCppClient(OpenAICompatibleLocalClient):
    def __init__(
        self,
        base_url: str | None = None,
        default_model: str = "",
        *,
        binary_path: str = "",
        model_path: str = "",
        auto_start: bool = False,
    ):
        super().__init__(
            base_url=(base_url or os.environ.get("ELYAN_LLAMACPP_BASE_URL") or "http://127.0.0.1:8080/v1"),
            default_model=default_model,
        )
        self.binary_path = binary_path.strip()
        self.model_path = model_path.strip()
        self.auto_start = bool(auto_start)
        self._jobs = JobManager()

    @property
    def binary(self) -> str | None:
        return self.binary_path or shutil.which("llama-server") or shutil.which("server")

    def status(self) -> dict[str, Any]:
        payload = super().status()
        payload.update(
            {
                "providerId": "llamacpp",
                "binary": self.binary,
                "modelPath": self.model_path,
                "autoStart": self.auto_start,
                "jobs": self._jobs.list(),
            }
        )
        return payload

    def start_server(self) -> dict[str, Any]:
        binary = self.binary
        if not binary:
            return {"ok": False, "error": "llamacpp_binary_missing"}
        if not self.model_path:
            return {"ok": False, "error": "llamacpp_model_missing"}
        parsed = urlparse(self.base_url if "://" in self.base_url else f"http://{self.base_url}")
        host = parsed.hostname or "127.0.0.1"
        port = str(parsed.port or 8080)
        command = [binary, "--model", self.model_path, "--host", host, "--port", port]
        job = self._jobs.start_process("llamacpp_start", command)
        return {"ok": True, "job": job.snapshot()}

    def jobs(self) -> list[dict[str, Any]]:
        return self._jobs.list()

    def job(self, job_id: str) -> dict[str, Any] | None:
        item = self._jobs.get(job_id)
        return item.snapshot() if item else None

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._jobs.cancel(job_id)
