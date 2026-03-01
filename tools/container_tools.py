"""
Elyan Container Tools — Docker image and container management

Build, run, stop, logs, compose, Dockerfile generation.
"""

import asyncio
from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("container_tools")


async def _run_docker(args: List[str], cwd: str = None) -> Dict[str, Any]:
    """Run a docker command asynchronously."""
    cmd = ["docker"] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        return {
            "success": proc.returncode == 0,
            "stdout": stdout.decode(errors="replace").strip()[:20000],
            "stderr": stderr.decode(errors="replace").strip()[:5000],
        }
    except asyncio.TimeoutError:
        return {"success": False, "error": "Docker command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def docker_build(path: str, tag: str = "elyan-build:latest") -> Dict[str, Any]:
    """Build a Docker image from a Dockerfile."""
    return await _run_docker(["build", "-t", tag, path])


async def docker_run(image: str, command: str = None, ports: str = None, name: str = None, detach: bool = True) -> Dict[str, Any]:
    """Run a Docker container."""
    args = ["run"]
    if detach:
        args.append("-d")
    if name:
        args.extend(["--name", name])
    if ports:
        args.extend(["-p", ports])
    args.append(image)
    if command:
        args.extend(command.split())
    return await _run_docker(args)


async def docker_stop(container: str) -> Dict[str, Any]:
    """Stop a running container."""
    return await _run_docker(["stop", container])


async def docker_ps(all_containers: bool = False) -> Dict[str, Any]:
    """List running containers."""
    args = ["ps", "--format", "{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"]
    if all_containers:
        args.insert(1, "-a")
    result = await _run_docker(args)
    if result["success"]:
        containers = []
        for line in result["stdout"].split("\n"):
            if line.strip():
                parts = line.split("\t")
                if len(parts) >= 4:
                    containers.append({"id": parts[0], "image": parts[1], "status": parts[2], "name": parts[3]})
        result["containers"] = containers
    return result


async def docker_logs(container: str, tail: int = 50) -> Dict[str, Any]:
    """Get container logs."""
    return await _run_docker(["logs", "--tail", str(tail), container])


async def docker_images() -> Dict[str, Any]:
    """List Docker images."""
    result = await _run_docker(["images", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"])
    if result["success"]:
        images = []
        for line in result["stdout"].split("\n"):
            if line.strip():
                parts = line.split("\t")
                if len(parts) >= 3:
                    images.append({"name": parts[0], "size": parts[1], "created": parts[2]})
        result["images"] = images
    return result


async def docker_compose_up(path: str, detach: bool = True) -> Dict[str, Any]:
    """Run docker compose up."""
    args = ["compose", "up"]
    if detach:
        args.append("-d")
    return await _run_docker(args, cwd=path)


async def docker_compose_down(path: str) -> Dict[str, Any]:
    """Run docker compose down."""
    return await _run_docker(["compose", "down"], cwd=path)


async def generate_dockerfile(language: str, entrypoint: str = "main.py") -> Dict[str, Any]:
    """Generate a Dockerfile for a given language."""
    templates = {
        "python": f"FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nCMD [\"python\", \"{entrypoint}\"]",
        "node": f"FROM node:20-slim\nWORKDIR /app\nCOPY package*.json ./\nRUN npm ci --only=production\nCOPY . .\nCMD [\"node\", \"{entrypoint}\"]",
        "go": f"FROM golang:1.22-alpine AS builder\nWORKDIR /app\nCOPY . .\nRUN go build -o app\nFROM alpine:3.19\nCOPY --from=builder /app/app /app\nCMD [\"/app\"]",
    }
    content = templates.get(language)
    if not content:
        return {"success": False, "error": f"No template for: {language}"}
    return {"success": True, "dockerfile": content, "language": language}
