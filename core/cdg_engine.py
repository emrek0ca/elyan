"""
Elyan CDG Engine — Contracted DAG with Gates

Default execution motoru. Her iş:
  Input → Contract → DAG Plan → Node Execution → QA Gates → Delivery

DAG düğümleri bağımsız, idempotent, paralel çalıştırılabilir.
Her düğüm: agent + tool permission + budget + acceptance test.
"""

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from utils.logger import get_logger

logger = get_logger("cdg_engine")


# ── DAG Node States ──────────────────────────────────────────

class NodeState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


@dataclass
class DAGNode:
    """Tek bir DAG düğümü (alt görev)."""
    id: str
    name: str
    action: str                        # tool/step adı
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)  # bağımlı düğüm id'leri
    allowed_tools: List[str] = field(default_factory=list)
    acceptance_test: Optional[str] = None  # QA check adı
    max_retries: int = 1
    budget_tokens: int = 4000
    idempotent: bool = True

    # Runtime state
    state: NodeState = NodeState.PENDING
    result: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: int = 0
    retry_count: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass
class QAGate:
    """Kalite kontrol kapısı."""
    name: str
    check_type: str  # file_exists, file_not_empty, html_valid, content_check, screenshot
    params: Dict[str, Any] = field(default_factory=dict)
    passed: Optional[bool] = None
    message: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CDGPlan:
    """Contracted DAG planı."""
    job_id: str
    job_type: str
    user_input: str
    nodes: List[DAGNode] = field(default_factory=list)
    node_qa_gates: Dict[str, List[QAGate]] = field(default_factory=dict)
    e2e_qa_gates: List[QAGate] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    status: str = "planned"  # planned, running, passed, failed


class CDGEngine:
    """
    Contracted DAG with Gates yürütme motoru.
    
    Akış:
    1. Contract → DAG plan oluştur
    2. DAG düğümlerini topolojik sırayla yürüt
    3. Her düğüm sonrası QA gate kontrolü
    4. Tüm düğümler bittikten sonra E2E QA
    5. Delivery = evidence manifest + artifact'lar
    """

    def __init__(self):
        self._plans: Dict[str, CDGPlan] = {}
        self._node_executors: Dict[str, Callable] = {}

    # ── Plan Oluşturma ────────────────────────────────────────

    def create_plan(self, job_id: str, job_type: str, user_input: str,
                    contract: Optional[Any] = None) -> CDGPlan:
        """Job template'den DAG planı oluştur."""
        from core.job_templates import get_template
        template = get_template(job_type)

        plan = CDGPlan(
            job_id=job_id,
            job_type=job_type,
            user_input=user_input,
        )

        # Template'e göre DAG düğümleri oluştur
        builder = _PLAN_BUILDERS.get(job_type, _build_generic_plan)
        builder(plan, user_input, template)

        self._plans[job_id] = plan
        logger.info(f"CDG plan created: {job_id} ({job_type}) — {len(plan.nodes)} nodes")
        return plan

    # ── DAG Yürütme ───────────────────────────────────────────

    async def execute(self, plan: CDGPlan, executor_fn: Callable) -> CDGPlan:
        """
        DAG'ı topolojik sırayla yürüt.
        
        executor_fn(node: DAGNode) -> Dict[str, Any]
        """
        plan.status = "running"

        # Topolojik sıra
        order = self._topological_sort(plan.nodes)

        for node_id in order:
            node = self._get_node(plan, node_id)
            if not node:
                continue

            # Bağımlılık kontrolü
            if not self._deps_satisfied(plan, node):
                node.state = NodeState.SKIPPED
                node.error = "Dependency failed"
                continue

            # Yürüt
            await self._execute_node(node, executor_fn)

            # Node-level QA gate
            if node.state == NodeState.PASSED:
                gates = plan.node_qa_gates.get(node_id, [])
                await self._run_qa_gates(gates, node)

                # QA fail → retry
                any_failed = any(g.passed is False for g in gates)
                if any_failed and node.retry_count < node.max_retries:
                    node.retry_count += 1
                    node.state = NodeState.RETRYING
                    logger.info(f"Node {node_id} QA failed, retrying ({node.retry_count}/{node.max_retries})")
                    await self._execute_node(node, executor_fn)

        # E2E QA
        if plan.e2e_qa_gates:
            await self._run_qa_gates(plan.e2e_qa_gates)

        # Final status
        all_passed = all(
            n.state in (NodeState.PASSED, NodeState.SKIPPED) for n in plan.nodes
        )
        e2e_ok = all(g.passed is not False for g in plan.e2e_qa_gates)

        plan.status = "passed" if (all_passed and e2e_ok) else "failed"
        logger.info(f"CDG plan {plan.job_id}: {plan.status}")
        return plan

    async def _execute_node(self, node: DAGNode, executor_fn: Callable):
        """Tek bir düğümü yürüt."""
        node.state = NodeState.RUNNING
        node.started_at = time.time()

        try:
            result = await asyncio.wait_for(
                executor_fn(node),
                timeout=300  # 5 min max per node
            )
            node.result = result if isinstance(result, dict) else {"output": str(result)}
            node.state = NodeState.PASSED

            # Evidence toplama
            node.evidence = self._collect_evidence(node.result)

        except asyncio.TimeoutError:
            node.state = NodeState.FAILED
            node.error = "Timeout (300s)"
        except Exception as e:
            node.state = NodeState.FAILED
            node.error = str(e)[:500]
            logger.error(f"Node {node.id} failed: {e}")

        node.finished_at = time.time()
        node.duration_ms = int((node.finished_at - node.started_at) * 1000)

    # ── QA Gates ──────────────────────────────────────────────

    async def _run_qa_gates(self, gates: List[QAGate], node: Optional[DAGNode] = None):
        """QA gate'leri çalıştır."""
        for gate in gates:
            try:
                if gate.check_type == "file_exists":
                    path = gate.params.get("path", "")
                    gate.passed = os.path.exists(path)
                    if gate.passed:
                        gate.evidence["path"] = path
                        gate.evidence["size"] = os.path.getsize(path)

                elif gate.check_type == "file_not_empty":
                    path = gate.params.get("path", "")
                    gate.passed = os.path.exists(path) and os.path.getsize(path) > 0
                    if gate.passed:
                        gate.evidence["size"] = os.path.getsize(path)

                elif gate.check_type == "html_valid":
                    path = gate.params.get("path", "")
                    if os.path.exists(path):
                        content = open(path, encoding="utf-8", errors="ignore").read()
                        gate.passed = "<html" in content.lower() or "<!doctype" in content.lower()
                    else:
                        gate.passed = False

                elif gate.check_type == "min_file_size":
                    path = gate.params.get("path", "")
                    min_bytes = gate.params.get("min_bytes", 100)
                    gate.passed = os.path.exists(path) and os.path.getsize(path) >= min_bytes

                elif gate.check_type == "sha256":
                    path = gate.params.get("path", "")
                    if os.path.exists(path):
                        h = hashlib.sha256(open(path, "rb").read()).hexdigest()
                        gate.evidence["sha256"] = h
                        gate.passed = True
                    else:
                        gate.passed = False

                elif gate.check_type == "content_check":
                    path = gate.params.get("path", "")
                    required = gate.params.get("contains", "")
                    if os.path.exists(path) and required:
                        content = open(path, encoding="utf-8", errors="ignore").read()
                        gate.passed = required.lower() in content.lower()
                    else:
                        gate.passed = bool(not required)

                else:
                    gate.passed = True  # Unknown check → pass

            except Exception as e:
                gate.passed = False
                gate.message = str(e)[:200]

    # ── Evidence Collection ───────────────────────────────────

    def _collect_evidence(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Tool sonucundan evidence topla."""
        evidence = {}
        for key in ("path", "file_path", "output_path", "screenshot", "image_path"):
            if key in result:
                evidence[key] = result[key]
                # SHA256 hash
                fpath = str(result[key])
                if os.path.isfile(fpath):
                    try:
                        evidence[f"{key}_sha256"] = hashlib.sha256(
                            open(fpath, "rb").read()
                        ).hexdigest()
                        evidence[f"{key}_size"] = os.path.getsize(fpath)
                    except Exception:
                        pass
        if result.get("success"):
            evidence["success"] = True
        return evidence

    # ── DAG Utilities ─────────────────────────────────────────

    def _topological_sort(self, nodes: List[DAGNode]) -> List[str]:
        """Topolojik sıralama (Kahn's algorithm)."""
        in_degree: Dict[str, int] = {n.id: 0 for n in nodes}
        adj: Dict[str, List[str]] = {n.id: [] for n in nodes}
        node_ids = {n.id for n in nodes}

        for n in nodes:
            for dep in n.depends_on:
                if dep in node_ids:
                    adj[dep].append(n.id)
                    in_degree[n.id] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order = []

        while queue:
            nid = queue.pop(0)
            order.append(nid)
            for child in adj.get(nid, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        return order

    def _get_node(self, plan: CDGPlan, node_id: str) -> Optional[DAGNode]:
        for n in plan.nodes:
            if n.id == node_id:
                return n
        return None

    def _deps_satisfied(self, plan: CDGPlan, node: DAGNode) -> bool:
        """Tüm bağımlılıklar PASSED mı?"""
        for dep_id in node.depends_on:
            dep = self._get_node(plan, dep_id)
            if dep and dep.state != NodeState.PASSED:
                return False
        return True

    # ── Manifest ──────────────────────────────────────────────

    def get_evidence_manifest(self, plan: CDGPlan) -> Dict[str, Any]:
        """Teslim için evidence manifest oluştur."""
        manifest = {
            "job_id": plan.job_id,
            "job_type": plan.job_type,
            "status": plan.status,
            "created_at": plan.created_at,
            "nodes": [],
            "artifacts": [],
            "qa_summary": {
                "node_gates": {},
                "e2e_gates": [],
            }
        }

        for node in plan.nodes:
            node_info = {
                "id": node.id,
                "name": node.name,
                "state": node.state.value,
                "duration_ms": node.duration_ms,
                "evidence": node.evidence,
            }
            manifest["nodes"].append(node_info)

            # Artifact'ları topla
            for key in ("path", "file_path", "output_path"):
                if key in node.evidence:
                    manifest["artifacts"].append({
                        "path": node.evidence[key],
                        "sha256": node.evidence.get(f"{key}_sha256"),
                        "size": node.evidence.get(f"{key}_size"),
                        "produced_by": node.id,
                    })

        # QA gates
        for node_id, gates in plan.node_qa_gates.items():
            manifest["qa_summary"]["node_gates"][node_id] = [
                {"name": g.name, "passed": g.passed, "evidence": g.evidence}
                for g in gates
            ]
        manifest["qa_summary"]["e2e_gates"] = [
            {"name": g.name, "passed": g.passed, "evidence": g.evidence}
            for g in plan.e2e_qa_gates
        ]

        return manifest

    def get_stats(self) -> Dict[str, Any]:
        total = len(self._plans)
        passed = sum(1 for p in self._plans.values() if p.status == "passed")
        return {
            "total_plans": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": f"{passed/max(1,total)*100:.0f}%",
        }


# ── Plan Builders (HTN Templates) ────────────────────────────

def _build_web_project_plan(plan: CDGPlan, user_input: str, template: dict):
    """Web projesi DAG planı."""
    plan.nodes = [
        DAGNode(id="spec", name="Spec oluştur", action="plan",
                allowed_tools=[], budget_tokens=2000),
        DAGNode(id="scaffold", name="Proje scaffold", action="create_web_project_scaffold",
                depends_on=["spec"],
                allowed_tools=["create_web_project_scaffold", "write_file", "create_directory"]),
        DAGNode(id="html", name="HTML yaz", action="write_file",
                depends_on=["scaffold"],
                allowed_tools=["write_file"]),
        DAGNode(id="css", name="CSS yaz", action="write_file",
                depends_on=["scaffold"],
                allowed_tools=["write_file"]),
        DAGNode(id="js", name="JS yaz", action="write_file",
                depends_on=["html"],
                allowed_tools=["write_file"]),
        DAGNode(id="qa", name="QA kontrol", action="verify",
                depends_on=["html", "css", "js"],
                allowed_tools=["take_screenshot", "read_file"]),
    ]
    # Node QA gates
    plan.node_qa_gates["html"] = [
        QAGate(name="HTML var", check_type="file_exists", params={}),
        QAGate(name="HTML geçerli", check_type="html_valid", params={}),
    ]
    plan.node_qa_gates["css"] = [
        QAGate(name="CSS var", check_type="file_exists", params={}),
    ]


def _build_research_plan(plan: CDGPlan, user_input: str, template: dict):
    """Araştırma raporu DAG planı."""
    plan.nodes = [
        DAGNode(id="scope", name="Kapsam belirleme", action="plan",
                allowed_tools=[], budget_tokens=1500),
        DAGNode(id="sources", name="Kaynak toplama", action="web_search",
                depends_on=["scope"],
                allowed_tools=["web_search", "deep_research"]),
        DAGNode(id="notes", name="Not çıkarma", action="analyze",
                depends_on=["sources"],
                allowed_tools=[]),
        DAGNode(id="outline", name="Taslak oluştur", action="plan",
                depends_on=["notes"],
                allowed_tools=[]),
        DAGNode(id="draft", name="Rapor yaz", action="write_file",
                depends_on=["outline"],
                allowed_tools=["write_file", "write_word"]),
        DAGNode(id="references", name="Kaynakça doğrula", action="verify",
                depends_on=["draft"],
                allowed_tools=["web_search"]),
        DAGNode(id="qa", name="Son QA", action="verify",
                depends_on=["draft", "references"],
                allowed_tools=["read_file"]),
    ]
    plan.node_qa_gates["draft"] = [
        QAGate(name="Rapor dosyası var", check_type="file_exists", params={}),
        QAGate(name="Rapor boş değil", check_type="file_not_empty", params={}),
    ]


def _build_code_project_plan(plan: CDGPlan, user_input: str, template: dict):
    """Yazılım projesi DAG planı."""
    plan.nodes = [
        DAGNode(id="spec", name="Spec + test criteria", action="plan",
                allowed_tools=[], budget_tokens=2000),
        DAGNode(id="implement", name="Kod yaz", action="write_file",
                depends_on=["spec"],
                allowed_tools=["write_file", "create_directory"]),
        DAGNode(id="test", name="Test çalıştır", action="execute_code",
                depends_on=["implement"],
                allowed_tools=["execute_python", "execute_code", "terminal_command"]),
        DAGNode(id="lint", name="Lint / type check", action="terminal_command",
                depends_on=["implement"],
                allowed_tools=["terminal_command"]),
        DAGNode(id="qa", name="Regression check", action="verify",
                depends_on=["test", "lint"],
                allowed_tools=["read_file"]),
    ]
    plan.node_qa_gates["implement"] = [
        QAGate(name="Kod dosyası var", check_type="file_exists", params={}),
    ]


def _build_editorial_plan(plan: CDGPlan, user_input: str, template: dict):
    """Makale yazma DAG planı."""
    plan.nodes = [
        DAGNode(id="brief", name="Audience + tone + format", action="plan",
                allowed_tools=[], budget_tokens=1000),
        DAGNode(id="outline", name="Outline (H1/H2)", action="plan",
                depends_on=["brief"],
                allowed_tools=[]),
        DAGNode(id="draft", name="Draft 1", action="write_file",
                depends_on=["outline"],
                allowed_tools=["write_file", "write_word"]),
        DAGNode(id="style_pass", name="Style pass", action="refine",
                depends_on=["draft"],
                allowed_tools=["write_file"]),
        DAGNode(id="fact_check", name="Fact check", action="verify",
                depends_on=["draft"],
                allowed_tools=["web_search"]),
        DAGNode(id="polish", name="Final polish", action="write_file",
                depends_on=["style_pass", "fact_check"],
                allowed_tools=["write_file"]),
    ]
    plan.node_qa_gates["draft"] = [
        QAGate(name="Draft dosyası var", check_type="file_exists", params={}),
        QAGate(name="Min 500 byte", check_type="min_file_size", params={"min_bytes": 500}),
    ]


def _build_file_ops_plan(plan: CDGPlan, user_input: str, template: dict):
    """Dosya işlemleri DAG planı."""
    plan.nodes = [
        DAGNode(id="analyze", name="İstek analizi", action="plan",
                allowed_tools=[], budget_tokens=1000),
        DAGNode(id="execute", name="İşlemi yürüt", action="file_op",
                depends_on=["analyze"],
                allowed_tools=template.get("allowed_tools", [])),
        DAGNode(id="verify", name="Doğrula", action="verify",
                depends_on=["execute"],
                allowed_tools=["list_directory", "read_file"]),
    ]


def _build_generic_plan(plan: CDGPlan, user_input: str, template: dict):
    """Genel (chat/system) DAG planı — tek düğüm."""
    plan.nodes = [
        DAGNode(id="respond", name="Yanıt üret", action="chat",
                allowed_tools=template.get("allowed_tools", []),
                budget_tokens=2000),
    ]


# Template → Builder eşlemesi
_PLAN_BUILDERS = {
    "web_project": _build_web_project_plan,
    "research_report": _build_research_plan,
    "code_project": _build_code_project_plan,
    "data_analysis": _build_code_project_plan,  # benzer yapı
    "file_operations": _build_file_ops_plan,
    "browser_task": _build_file_ops_plan,
    "system_ops": _build_file_ops_plan,
    "communication": _build_generic_plan,
}


# Global instance
cdg_engine = CDGEngine()
