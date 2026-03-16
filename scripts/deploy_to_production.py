#!/usr/bin/env python3
"""
Production Deployment Pipeline for Wiqo Bot
============================================
Handles pre-deployment validation, database migrations, configuration,
health checks, and gradual rollout with rollback capability.
"""

import sys
import time
import json
import logging
import argparse
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
import sqlite3

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.health_checks import create_default_health_checks
import asyncio


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


@dataclass
class DeploymentConfig:
    """Configuration for a deployment."""
    version: str
    environment: str  # development, staging, production
    database_path: str
    log_dir: str
    llm_provider: str
    max_concurrent_tasks: int
    timeout_per_task: float
    timeout_total: float
    enable_learning: bool
    enable_analytics: bool
    enable_monitoring: bool
    rollout_stages: List[Tuple[float, int]]  # (percentage, duration_seconds)


class DeploymentStep:
    """Base class for deployment steps."""

    def __init__(self, name: str):
        self.name = name
        self.success = False
        self.duration = 0.0
        self.message = ""

    async def execute(self) -> bool:
        """Execute the deployment step."""
        raise NotImplementedError

    def __str__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"[{status}] {self.name}: {self.message} ({self.duration:.2f}s)"


class PreDeploymentValidation(DeploymentStep):
    """Validate system before deployment."""

    def __init__(self):
        super().__init__("Pre-Deployment Validation")

    async def execute(self) -> bool:
        """Run pre-deployment checks."""
        start = time.time()

        try:
            # Check Python version
            if sys.version_info < (3, 8):
                self.message = "Python 3.8+ required"
                return False

            # Check required directories
            required_dirs = ["./.claude", "./core", "./tests", "./scripts"]
            for dir_path in required_dirs:
                if not Path(dir_path).exists():
                    self.message = f"Missing required directory: {dir_path}"
                    return False

            # Check required files
            required_files = [
                "core/agent.py",
                "core/task_engine.py",
                "config/settings.py"
            ]
            for file_path in required_files:
                if not Path(file_path).exists():
                    self.message = f"Missing required file: {file_path}"
                    return False

            self.success = True
            self.message = "All pre-deployment checks passed"
            return True

        finally:
            self.duration = time.time() - start


class DatabaseMigration(DeploymentStep):
    """Initialize and migrate database."""

    def __init__(self, db_path: str):
        super().__init__("Database Migration")
        self.db_path = db_path

    async def execute(self) -> bool:
        """Run database migrations."""
        start = time.time()

        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create core tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_state (
                    state_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    state_data BLOB NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (execution_id) REFERENCES executions(execution_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    metric_name TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    resolved BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT NOT NULL,
                    value REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    tags TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indices
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_execution_status ON executions(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoint_execution ON checkpoints(execution_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_severity ON alerts(severity)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metric_name ON metrics(metric_name)")

            conn.commit()
            conn.close()

            self.success = True
            self.message = f"Database initialized: {self.db_path}"
            return True

        except Exception as e:
            self.message = f"Database migration failed: {e}"
            return False

        finally:
            self.duration = time.time() - start


class ConfigurationValidation(DeploymentStep):
    """Validate configuration."""

    def __init__(self, config: DeploymentConfig):
        super().__init__("Configuration Validation")
        self.config = config

    async def execute(self) -> bool:
        """Validate configuration."""
        start = time.time()

        try:
            # Validate required fields
            if not self.config.version:
                self.message = "Version not specified"
                return False

            if self.config.environment not in ["development", "staging", "production"]:
                self.message = f"Invalid environment: {self.config.environment}"
                return False

            if self.config.max_concurrent_tasks < 1:
                self.message = "max_concurrent_tasks must be >= 1"
                return False

            if not self.config.rollout_stages:
                self.message = "No rollout stages defined"
                return False

            # Validate rollout stages
            for percentage, duration in self.config.rollout_stages:
                if not (0 < percentage <= 100):
                    self.message = f"Invalid rollout percentage: {percentage}"
                    return False
                if duration < 60:
                    self.message = "Rollout stage duration must be >= 60 seconds"
                    return False

            self.success = True
            self.message = f"Configuration valid (v{self.config.version}, {self.config.environment})"
            return True

        finally:
            self.duration = time.time() - start


class HealthCheckStep(DeploymentStep):
    """Run system health checks."""

    def __init__(self, db_path: str):
        super().__init__("Health Checks")
        self.db_path = db_path

    async def execute(self) -> bool:
        """Run health checks."""
        start = time.time()

        try:
            suite = create_default_health_checks(self.db_path)
            results = await suite.run_all()

            unhealthy = sum(1 for r in results["details"] if r["status"] == "unhealthy")

            if unhealthy > 0:
                self.message = f"{unhealthy} health checks failed"
                return False

            self.success = True
            self.message = f"All {results['checks_run']} health checks passed"
            return True

        except Exception as e:
            self.message = f"Health check execution failed: {e}"
            return False

        finally:
            self.duration = time.time() - start


class RolloutStep(DeploymentStep):
    """Perform gradual rollout."""

    def __init__(self, stages: List[Tuple[float, int]]):
        super().__init__("Gradual Rollout")
        self.stages = stages

    async def execute(self) -> bool:
        """Execute gradual rollout."""
        start = time.time()

        try:
            logger.info("Starting gradual rollout...")

            for stage_num, (percentage, duration) in enumerate(self.stages, 1):
                logger.info(f"Stage {stage_num}: Rolling out to {percentage}% of traffic "
                           f"for {duration} seconds")

                # In a real deployment, this would:
                # - Update load balancer/router configuration
                # - Monitor error rates and metrics
                # - Automatically rollback if issues detected

                end_time = time.time() + duration
                while time.time() < end_time:
                    # Monitor during rollout stage
                    await asyncio.sleep(5)
                    # Check metrics/errors
                    # Rollback if needed

                logger.info(f"Stage {stage_num} complete")

            self.success = True
            self.message = f"Rolled out through {len(self.stages)} stages"
            return True

        except Exception as e:
            self.message = f"Rollout failed: {e}"
            return False

        finally:
            self.duration = time.time() - start


class DeploymentState:
    """Tracks deployment state for rollback capability."""

    def __init__(self, state_file: str = "~/.wiqo/deployment_state.json"):
        self.state_file = Path(state_file).expanduser()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, version: str, config: DeploymentConfig) -> None:
        """Save deployment snapshot for rollback."""
        snapshot = {
            "version": version,
            "timestamp": time.time(),
            "config": {
                "version": config.version,
                "environment": config.environment,
                "database_path": config.database_path,
                "log_dir": config.log_dir
            }
        }

        with open(self.state_file, "w") as f:
            json.dump(snapshot, f, indent=2)

        logger.info(f"Saved deployment snapshot: {version}")

    def get_previous_version(self) -> Optional[str]:
        """Get previously deployed version."""
        if not self.state_file.exists():
            return None

        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
                return data.get("version")
        except Exception:
            return None


class Deployer:
    """Orchestrates the entire deployment process."""

    def __init__(self, config: DeploymentConfig):
        self.config = config
        self.steps: List[DeploymentStep] = []
        self.state = DeploymentState()
        self.results: Dict[str, Any] = {}

    def add_step(self, step: DeploymentStep) -> None:
        """Add a deployment step."""
        self.steps.append(step)

    async def deploy(self) -> Tuple[bool, Dict[str, Any]]:
        """Execute deployment."""
        logger.info(f"Starting deployment of version {self.config.version} "
                   f"to {self.config.environment}")

        results = {
            "version": self.config.version,
            "environment": self.config.environment,
            "timestamp": time.time(),
            "steps": [],
            "success": False,
            "duration": 0.0
        }

        start = time.time()

        try:
            # Execute each step
            for step in self.steps:
                logger.info(f"Executing: {step.name}")
                success = await step.execute()
                logger.info(f"  {step}")

                results["steps"].append({
                    "name": step.name,
                    "success": success,
                    "duration": step.duration,
                    "message": step.message
                })

                if not success:
                    logger.error(f"Deployment failed at step: {step.name}")
                    results["success"] = False
                    return False, results

            # Save deployment snapshot
            self.state.save_snapshot(self.config.version, self.config)

            results["success"] = True
            logger.info("Deployment completed successfully")
            return True, results

        except Exception as e:
            logger.error(f"Deployment error: {e}")
            results["error"] = str(e)
            return False, results

        finally:
            results["duration"] = time.time() - start


async def deploy_production(
    version: str,
    environment: str = "production",
    db_path: str = "~/.wiqo/bot.db",
    log_dir: str = "~/.wiqo/logs"
) -> Tuple[bool, Dict[str, Any]]:
    """
    Deploy to production with full validation and rollout.
    """
    # Create deployment configuration
    config = DeploymentConfig(
        version=version,
        environment=environment,
        database_path=db_path,
        log_dir=log_dir,
        llm_provider="groq",
        max_concurrent_tasks=4,
        timeout_per_task=30.0,
        timeout_total=300.0,
        enable_learning=True,
        enable_analytics=True,
        enable_monitoring=True,
        rollout_stages=[
            (5, 300),    # 5% for 5 minutes
            (25, 300),   # 25% for 5 minutes
            (50, 600),   # 50% for 10 minutes
            (100, 0)     # 100% (completed)
        ]
    )

    # Create deployer and add steps
    deployer = Deployer(config)
    deployer.add_step(PreDeploymentValidation())
    deployer.add_step(DatabaseMigration(db_path))
    deployer.add_step(ConfigurationValidation(config))
    deployer.add_step(HealthCheckStep(db_path))
    if environment == "production":
        deployer.add_step(RolloutStep(config.rollout_stages))

    # Execute deployment
    success, results = await deployer.deploy()

    # Print results
    print("\n" + "=" * 70)
    print("DEPLOYMENT SUMMARY")
    print("=" * 70)
    print(f"Version: {results['version']}")
    print(f"Environment: {results['environment']}")
    print(f"Status: {'SUCCESS' if results['success'] else 'FAILED'}")
    print(f"Duration: {results['duration']:.2f}s")
    print("\nSteps:")
    for step in results["steps"]:
        status = "✓" if step["success"] else "✗"
        print(f"  [{status}] {step['name']}: {step['message']} ({step['duration']:.2f}s)")

    print("=" * 70)

    return success, results


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Deploy Wiqo Bot to production")
    parser.add_argument("--version", required=True, help="Version to deploy")
    parser.add_argument("--environment", default="production",
                       choices=["development", "staging", "production"])
    parser.add_argument("--db-path", default="~/.wiqo/bot.db")
    parser.add_argument("--log-dir", default="~/.wiqo/logs")

    args = parser.parse_args()

    success, results = asyncio.run(deploy_production(
        version=args.version,
        environment=args.environment,
        db_path=args.db_path,
        log_dir=args.log_dir
    ))

    # Write results to file
    results_file = Path("~/.wiqo/deployment_results.json").expanduser()
    results_file.parent.mkdir(parents=True, exist_ok=True)
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
