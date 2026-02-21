"""
core/multi_agent/audit_bundle.py
─────────────────────────────────────────────────────────────────────────────
Generates "Proof of Delivery" Audit Bundles.
Zips Job Contracts, Execution Reports, QA outcomes, and Metrics.
Calculates 5 Core Quality Metrics.
"""

import os
import zipfile
import json
import time
from pathlib import Path
from typing import Dict, Any, List
from .contract import DeliverableContract, JobMetrics
from config.settings import ELYAN_DIR
from utils.logger import get_logger

logger = get_logger("audit_bundle")

class AuditManager:
    def __init__(self):
        self.bundle_dir = ELYAN_DIR / "audits"
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        
    def calculate_metrics(self, contract: DeliverableContract, execution_results: Dict[str, Any], qa_issues: List[Dict[str, str]], duration: float) -> JobMetrics:
        """
        Calculates the 5 Core Metrics for the Autonomous Operator Job.
        1. Task Success Rate
        2. Tool Correctness (Success vs Fail execution count)
        3. Output Completeness (Artifact matching % against contract)
        4. Token Usage (Approximated or passed from LLM)
        5. Duration_s
        """
        metrics = JobMetrics(duration_s=duration)
        
        # 1. Output Completeness
        expected_artifacts = len(contract.artifacts)
        if expected_artifacts == 0:
            metrics.output_completeness = 1.0
        else:
            actual_artifacts = len([a for a in contract.artifacts.values() if os.path.exists(Path(a.path).expanduser())])
            metrics.output_completeness = float(actual_artifacts / expected_artifacts)
            
        # 2. Tool Correctness
        total_steps = len(execution_results)
        if total_steps == 0:
            metrics.tool_correctness = 1.0
        else:
            success_steps = len([res for res in execution_results.values() if res.get("success")])
            metrics.tool_correctness = float(success_steps / total_steps)
            
        # 3. Overall Task Success
        # Passed QA (no issues) + High Tool Correctness + High Completeness
        metrics.task_success_rate = 1.0 if not qa_issues and metrics.output_completeness == 1.0 else 0.0
        
        # Attach metrics back to contract
        contract.metrics = metrics
        return metrics

    def generate_bundle(self, contract: DeliverableContract, execution_results: Dict[str, Any], qa_issues: List[Dict[str, str]], workspace: str) -> str:
        """
        Creates a ZIP archive containing the full proof of work for sales/debugging.
        """
        timestamp = int(time.time())
        bundle_name = f"audit_{contract.job_id}_{timestamp}.zip"
        bundle_path = self.bundle_dir / bundle_name
        
        report_data = {
            "job_id": contract.job_id,
            "goal": contract.goal,
            "metrics": contract.metrics.__dict__,
            "qa_issues": qa_issues,
            "execution_steps": execution_results
        }
        
        with zipfile.ZipFile(bundle_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add JSON manifest
            zf.writestr('manifest.json', json.dumps(report_data, indent=2, ensure_ascii=False))
            # Add expected contract
            zf.writestr('contract.json', contract.to_json())
            
            # Add all resulting artifacts inside the bundle
            for art_path in contract.artifacts:
                full_path = Path(workspace) / art_path.lstrip("/")
                if full_path.exists():
                    zf.write(full_path, arcname=f"artifacts/{art_path.lstrip('/')}")
                    
        logger.info(f"Generated Audit Bundle: {bundle_path}")
        contract.audit_bundle_path = str(bundle_path)
        return str(bundle_path)
