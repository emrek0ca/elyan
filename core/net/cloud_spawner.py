"""
core/net/cloud_spawner.py
─────────────────────────────────────────────────────────────────────────────
Omni-Presence Cloud Spawner (IaC Swarm Deployment).
Provides Elyan with the ability to dynamically rent and destroy remote 
cloud servers (e.g., DigitalOcean Droplets) completely autonomously.
This is strictly to be used for ultra-high compute tasks (massive scraping,
model training) that the local user machine cannot handle.

Follows OpenClaw-like architecture: User brings their own API key.
"""

import os
import json
import asyncio
import aiohttp
from typing import Dict, Any, List
from utils.logger import get_logger

logger = get_logger("cloud_spawner")

class CloudSpawner:
    def __init__(self, agent_instance):
        self.agent = agent_instance
        # In a real user-installed app, this comes from a central Config class or .env
        self.api_key = os.getenv("DO_API_TOKEN", "mock_token")
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        self.base_url = "https://api.digitalocean.com/v2"
        self.active_droplets = []
        
        # Security: Hard-limit budget allowed for autonomous renting
        self.MAX_DAILY_BUDGET = 5.0 # $5.00 limit

    async def _check_budget(self) -> bool:
        """Security: Elyan cannot rent servers if the daily limit is breached."""
        # Querying an internal ledger (mocked here)
        spent_today = 0.0 # load from self.agent.wallet_tracker in FinOps
        if spent_today >= self.MAX_DAILY_BUDGET:
            logger.error("🛑 CloudSpawner Budget Limit Reached! Cannot authorize new clusters.")
            return False
        return True

    async def spawn_ephemeral_cluster(self, instance_count: int = 1, size: str = "s-1vcpu-1gb") -> List[Dict[str, Any]]:
        """Spawns an Ubuntu VPS, runs Dockerized Elyan SwarmNode, and returns the IPs."""
        if not await self._check_budget():
            return []

        logger.info(f"🌩️ Autonomous IaC: Spawning {instance_count} '{size}' cloud droplet(s) for extreme compute task...")
        
        # User Data script that runs on Server Boot
        # This installs Docker and runs the SwarmNode we built in Phase 15.
        cloud_init_script = """#!/bin/bash
        apt-get update
        apt-get install -y docker.io
        # Run Elyan Headless Worker
        docker run -d --name elyan_node -p 8765:8765 emrekoca/elyan-swarm-node:latest
        """

        payload = {
            "names": [f"elyan-ephemeral-worker-{i}" for i in range(instance_count)],
            "region": "fra1",
            "size": size,
            "image": "ubuntu-22-04-x64",
            "user_data": cloud_init_script,
            "tags": ["elyan-swarm"]
        }

        try:
            # We wrap this in a mock for now, but the API logic remains universally robust.
            if self.api_key == "mock_token":
                logger.warning("No DO_API_TOKEN found. Simulating cloud spin-up.")
                mock_ips = [{"id": 100+i, "ip": f"192.168.100.{10+i}"} for i in range(instance_count)]
                self.active_droplets.extend([d["id"] for d in mock_ips])
                # Simulate provisioning delay
                await asyncio.sleep(2)
                return mock_ips

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/droplets", json=payload, headers=self.headers) as resp:
                    if resp.status == 202:
                        data = await resp.json()
                        logger.info("✅ Droplets provisioning started via Cloud API.")
                        # We would track the ID and wait for network attachment
                        return data.get("droplets", [])
                    else:
                        logger.error(f"Cloud API failed: {resp.status} - {await resp.text()}")
                        return []
        except Exception as e:
            logger.error(f"CloudSpawner exception: {e}")
            return []

    async def destroy_all_ephemeral_clusters(self):
        """CRITICAL: Kills all active droplets to stop billing immediately after task finishes."""
        logger.info("🗑️ Autonomously destroying all ephemeral droplets to preserve budget...")
        
        if self.api_key == "mock_token":
            self.active_droplets.clear()
            logger.info("✅ Simulated instance destruction complete.")
            return

        try:
            async with aiohttp.ClientSession() as session:
                # Destroy by tag to ensure no stranded instances
                async with session.delete(f"{self.base_url}/droplets?tag_name=elyan-swarm", headers=self.headers) as resp:
                    if resp.status == 204:
                        logger.info("✅ All Swarm Nodes have been terminated on the Cloud.")
                        self.active_droplets.clear()
                    else:
                        logger.error(f"Failed to destroy cluster: {resp.status} - {await resp.text()}")
        except Exception as e:
            logger.error(f"CloudSpawner destruction exception: {e}")
