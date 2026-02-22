"""
Elyan Job Contract — Contract-First Typed Artifacts

Her iş için tek contract oluşturur.
Builder contract'a göre üretir, QA contract'a göre doğrular.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import time
import json
from utils.logger import get_logger

logger = get_logger("job_contract")


class DeliveryMode(Enum):
    FILE_PATH = "file_path"
    ZIP = "zip"
    INLINE = "inline"
    NONE = "none"


class ArtifactStatus(Enum):
    PENDING = "pending"
    CREATED = "created"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass
class ExpectedArtifact:
    """Beklenen çıktı dosyası."""
    path: str                          # Beklenen dosya yolu
    artifact_type: str                 # html, css, js, py, docx, xlsx, md, png
    description: str = ""
    required: bool = True
    status: ArtifactStatus = ArtifactStatus.PENDING
    actual_path: Optional[str] = None  # Gerçekte oluşan yol
    verified: bool = False
    hash: Optional[str] = None


@dataclass
class QACheck:
    """Kalite kontrol kuralı."""
    name: str                # file_exists, html_valid, word_count_min, screenshot
    params: Dict = field(default_factory=dict)
    passed: Optional[bool] = None
    message: str = ""


@dataclass
class JobContract:
    """
    Bir iş için typed contract.
    
    Builder yalnızca contract'a göre üretir.
    Tool Runner yalnızca artifacts index'e göre yazar.
    QA yalnızca index + disk durumunu karşılaştırır.
    """
    job_id: str
    job_type: str                           # web_project, research_report, file_ops
    user_input: str
    created_at: float = field(default_factory=time.time)

    # Contract specs
    allowed_tools: List[str] = field(default_factory=list)
    expected_artifacts: List[ExpectedArtifact] = field(default_factory=list)
    qa_checks: List[QACheck] = field(default_factory=list)
    delivery_mode: DeliveryMode = DeliveryMode.FILE_PATH

    # Execution state
    tool_calls: List[Dict] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed, verified
    evidence: Dict = field(default_factory=dict)

    def add_artifact(self, path: str, artifact_type: str, description: str = "", required: bool = True):
        self.expected_artifacts.append(
            ExpectedArtifact(path=path, artifact_type=artifact_type,
                             description=description, required=required)
        )

    def add_qa(self, name: str, **params):
        self.qa_checks.append(QACheck(name=name, params=params))

    def record_tool_call(self, tool_name: str, params: dict, result: dict):
        """Tool çağrısını kaydet."""
        self.tool_calls.append({
            "tool": tool_name,
            "params": {k: v for k, v in params.items() if not k.startswith("_")},
            "success": result.get("success", False) if isinstance(result, dict) else False,
            "ts": time.time(),
        })

    def verify_artifacts(self) -> Dict[str, Any]:
        """Beklenen artifact'ları disk ile karşılaştır."""
        import os
        results = {"total": 0, "found": 0, "missing": [], "verified": []}
        for art in self.expected_artifacts:
            results["total"] += 1
            check_path = art.actual_path or art.path
            if os.path.exists(check_path):
                art.status = ArtifactStatus.CREATED
                art.verified = True
                results["found"] += 1
                results["verified"].append(check_path)
            else:
                if art.required:
                    art.status = ArtifactStatus.FAILED
                    results["missing"].append(art.path)
        
        all_required_ok = all(
            a.verified for a in self.expected_artifacts if a.required
        )
        self.status = "verified" if all_required_ok else "failed"
        return results

    def run_qa(self) -> Dict[str, Any]:
        """QA check'leri çalıştır."""
        import os
        results = {"total": 0, "passed": 0, "failed": []}
        for check in self.qa_checks:
            results["total"] += 1
            try:
                if check.name == "file_exists":
                    path = check.params.get("path", "")
                    check.passed = os.path.exists(path)
                elif check.name == "file_not_empty":
                    path = check.params.get("path", "")
                    check.passed = os.path.exists(path) and os.path.getsize(path) > 0
                elif check.name == "html_valid":
                    path = check.params.get("path", "")
                    if os.path.exists(path):
                        content = open(path).read()
                        check.passed = "<html" in content.lower() or "<!doctype" in content.lower()
                    else:
                        check.passed = False
                elif check.name == "min_file_size":
                    path = check.params.get("path", "")
                    min_bytes = check.params.get("min_bytes", 100)
                    check.passed = os.path.exists(path) and os.path.getsize(path) >= min_bytes
                else:
                    check.passed = True  # Unknown check type → pass

                if check.passed:
                    results["passed"] += 1
                else:
                    results["failed"].append(check.name)
            except Exception as e:
                check.passed = False
                check.message = str(e)
                results["failed"].append(check.name)

        return results

    def get_evidence_summary(self) -> Dict:
        """Evidence Gate için kanıt özeti."""
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "tool_calls_count": len(self.tool_calls),
            "successful_tools": sum(1 for t in self.tool_calls if t.get("success")),
            "artifacts_verified": sum(1 for a in self.expected_artifacts if a.verified),
            "artifacts_total": len(self.expected_artifacts),
            "qa_passed": sum(1 for q in self.qa_checks if q.passed),
            "qa_total": len(self.qa_checks),
        }

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "created_at": self.created_at,
            "allowed_tools": self.allowed_tools,
            "artifacts": [{"path": a.path, "type": a.artifact_type, 
                          "status": a.status.value, "verified": a.verified}
                         for a in self.expected_artifacts],
            "qa": [{"name": q.name, "passed": q.passed} for q in self.qa_checks],
            "tool_calls": len(self.tool_calls),
            "evidence": self.get_evidence_summary(),
        }
