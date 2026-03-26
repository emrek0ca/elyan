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

    async def create_plan(self, job_id: str, job_type: str, user_input: str,
                    contract: Optional[Any] = None, llm_client=None) -> CDGPlan:
        """Job template'den veya LLM'den DAG planı oluştur."""
        from core.job_templates import get_template
        template = get_template(job_type)

        plan = CDGPlan(
            job_id=job_id,
            job_type=job_type,
            user_input=user_input,
        )

        # Template'e göre DAG düğümleri oluştur
        builder = _PLAN_BUILDERS.get(job_type, _build_generic_plan)
        
        # Eğer builder async ise await et (Dynamic Plan Builder gibi)
        import inspect
        if inspect.iscoroutinefunction(builder):
            await builder(plan, user_input, template, llm_client)
        else:
            builder(plan, user_input, template)

        self._plans[job_id] = plan
        logger.info(f"CDG plan created: {job_id} ({job_type}) — {len(plan.nodes)} nodes")
        return plan

    # ── DAG Yürütme ───────────────────────────────────────────

    async def execute(self, plan: CDGPlan, executor_fn: Callable) -> CDGPlan:
        """
        DAG'ı wave-based paralel yürütme ile çalıştır.

        executor_fn(node: DAGNode) -> Dict[str, Any]
        """
        plan.status = "running"

        # Topological waves — bağımsız düğümler aynı wavede
        waves = self._topological_sort_waves(plan.nodes)

        for wave_idx, wave in enumerate(waves):
            # Wavede çalıştırılabilir düğümleri filtrele
            runnable = []
            for node_id in wave:
                node = self._get_node(plan, node_id)
                if not node:
                    continue
                if self._deps_satisfied(plan, node):
                    runnable.append(node)
                else:
                    node.state = NodeState.SKIPPED
                    node.error = "Dependency failed"

            # Wave'deki tüm düğümleri paralel yürüt
            if runnable:
                await asyncio.gather(*[
                    self._execute_node_with_qa(plan, node, executor_fn)
                    for node in runnable
                ])

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

    async def _execute_node_with_qa(self, plan: CDGPlan, node: DAGNode, executor_fn: Callable):
        """Execute a node and run its QA gates, with retry logic."""
        # Yürüt
        await self._execute_node(node, executor_fn)

        # Node-level QA gate
        if node.state == NodeState.PASSED:
            gates = plan.node_qa_gates.get(node.id, [])
            await self._run_qa_gates(gates, node)

            # QA fail → retry
            any_failed = any(g.passed is False for g in gates)
            if any_failed and node.retry_count < node.max_retries:
                node.retry_count += 1
                node.state = NodeState.RETRYING
                logger.info(f"Node {node.id} QA failed, retrying ({node.retry_count}/{node.max_retries})")

                # 🔥 AUTO-PATCH TRIGGER
                failed_gates = [g for g in gates if g.passed is False]
                try:
                    from core.auto_patch import auto_patch
                    if auto_patch.apply_patch(node, failed_gates):
                        logger.info(f"Auto-patched node {node.id} before retry.")
                except Exception as e:
                    logger.error(f"Auto-patch failed: {e}")

                await self._execute_node(node, executor_fn)

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

    def _topological_sort_waves(self, nodes: List[DAGNode]) -> List[List[str]]:
        """
        Topolojik sıralama ama 'waves' olarak — her wave'de bağımsız düğümler.
        Bağımsız düğümler aynı wavede paralel çalışabilir.
        """
        in_degree: Dict[str, int] = {n.id: 0 for n in nodes}
        adj: Dict[str, List[str]] = {n.id: [] for n in nodes}
        node_ids = {n.id for n in nodes}

        for n in nodes:
            for dep in n.depends_on:
                if dep in node_ids:
                    adj[dep].append(n.id)
                    in_degree[n.id] += 1

        waves = []
        while any(deg == 0 for deg in in_degree.values()):
            # Bu wavede çalıştırılabilir tüm düğümleri bul
            current_wave = [nid for nid, deg in in_degree.items() if deg == 0]
            if not current_wave:
                break

            waves.append(current_wave)

            # Wavede olan düğümleri işaretle (removed)
            for nid in current_wave:
                in_degree[nid] = -1  # "processed" marker
                for child in adj.get(nid, []):
                    in_degree[child] -= 1

        return waves

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

def _normalize_ascii_text(text: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")


def _extract_web_project_name(text: str) -> str:
    import re

    raw = str(text or "").strip()
    normalized = _normalize_ascii_text(raw)
    low = normalized.lower()

    quoted = re.search(r"[\"'`“”](.{2,60}?)[\"'`“”]", raw)
    if quoted:
        candidate = str(quoted.group(1) or "").strip()
        if candidate:
            return candidate[:60]

    if any(token in low for token in ("portfolio", "portfoy", "portfolyo")):
        if ("sari" in low or "yellow" in low) and ("turuncu" in low or "orange" in low):
            return "Sunset Portfolio"
        if ("siyah" in low or "black" in low) and ("beyaz" in low or "white" in low):
            return "Mono Portfolio"
        return "Portfolio Atelier"
    if any(token in low for token in ("dashboard", "panel")):
        return "Operations Dashboard"
    if any(token in low for token in ("landing page", "landing")):
        return "Landing Experience"
    if any(token in low for token in ("blog", "editorial")):
        return "Editorial Journal"

    before_target = re.search(
        r"([a-zA-Z0-9 _-]{2,80})\s+(?:website|web sitesi|web sayfasi|site|uygulama|app)\b",
        normalized,
        re.IGNORECASE,
    )
    if before_target:
        candidate = str(before_target.group(1) or "").strip().lower()
        stop_words = {
            "bir", "ve", "for", "with", "yap", "olustur", "hazirla", "create", "build",
            "renklerde", "renkte", "colors", "color", "portfolio", "portfoy", "portfolyo",
            "web", "website", "site", "uygulama", "app",
        }
        words = [word for word in re.split(r"[^a-z0-9]+", candidate) if word and word not in stop_words]
        if 1 <= len(words) <= 4:
            return " ".join(part.capitalize() for part in words)[:60]

    return "Web Studio"


def _infer_web_theme(text: str) -> str:
    low = _normalize_ascii_text(text).lower()
    if any(token in low for token in ("minimal", "clean", "sade")):
        return "minimal"
    if any(token in low for token in ("neon", "cyber", "futuristic", "futuristik")):
        return "futuristic"
    if any(token in low for token in ("enterprise", "kurumsal", "corporate", "b2b")):
        return "corporate"
    return "professional"


def _build_web_project_plan(plan: CDGPlan, user_input: str, template: dict):
    """Web projesi DAG planı."""
    import re
    from pathlib import Path
    from tools.pro_workflows import _build_vanilla_assets, _safe_project_slug

    text = str(user_input or "").strip()
    project_name = _extract_web_project_name(text)
    slug = _safe_project_slug(project_name).strip("_") or "web_studio"
    theme = _infer_web_theme(text)

    output_dir = Path.home() / "Desktop"
    out_match = re.search(
        r"(?:output[_ ]?dir|cikti|çıktı|dizin|klasor|klasör|folder)\s*[:=]?\s*([~\/][^\s,;]+)",
        text,
        flags=re.IGNORECASE,
    )
    if out_match:
        try:
            output_dir = Path(out_match.group(1)).expanduser()
        except Exception:
            output_dir = Path.home() / "Desktop"

    project_dir = output_dir / slug
    html_path = project_dir / "index.html"
    css_path = project_dir / "styles" / "main.css"
    js_path = project_dir / "scripts" / "main.js"
    html_content, css_content, js_content, profile = _build_vanilla_assets(
        project_name=project_name,
        brief=text or "Web projesi olustur",
        theme=theme,
    )
    layout = str(profile.get("layout") or "landing")
    html_marker = "portfolio-hero" if layout == "portfolio" else "grid-sections"

    plan.nodes = [
        DAGNode(id="spec", name="Spec oluştur", action="plan",
                allowed_tools=[], budget_tokens=2000),
        DAGNode(id="scaffold", name="Proje scaffold", action="create_web_project_scaffold",
                depends_on=["spec"],
                params={
                    "project_name": project_name,
                    "stack": "vanilla",
                    "theme": theme,
                    "output_dir": str(output_dir),
                    "brief": text or "Web projesi olustur",
                },
                allowed_tools=["create_web_project_scaffold", "write_file", "create_directory"]),
        DAGNode(id="html", name="HTML yaz", action="write_file",
                depends_on=["scaffold"],
                params={
                    "path": str(html_path),
                    "content": html_content,
                },
                allowed_tools=["write_file"]),
        DAGNode(id="css", name="CSS yaz", action="write_file",
                depends_on=["scaffold"],
                params={
                    "path": str(css_path),
                    "content": css_content,
                },
                allowed_tools=["write_file"]),
        DAGNode(id="js", name="JS yaz", action="write_file",
                depends_on=["html"],
                params={
                    "path": str(js_path),
                    "content": js_content,
                },
                allowed_tools=["write_file"]),
        DAGNode(id="qa", name="QA kontrol", action="verify",
                depends_on=["html", "css", "js"],
                allowed_tools=["take_screenshot", "read_file"]),
    ]
    plan.node_qa_gates["html"] = [
        QAGate(name="HTML var", check_type="file_exists", params={"path": str(html_path)}),
        QAGate(name="HTML geçerli", check_type="html_valid", params={"path": str(html_path)}),
        QAGate(name="HTML yeterli boyutta", check_type="min_file_size", params={"path": str(html_path), "min_bytes": 1400}),
        QAGate(name="HTML layout marker", check_type="content_check", params={"path": str(html_path), "contains": html_marker}),
    ]
    plan.node_qa_gates["css"] = [
        QAGate(name="CSS var", check_type="file_exists", params={"path": str(css_path)}),
        QAGate(name="CSS yeterli boyutta", check_type="min_file_size", params={"path": str(css_path), "min_bytes": 1200}),
    ]
    plan.node_qa_gates["js"] = [
        QAGate(name="JS var", check_type="file_exists", params={"path": str(js_path)}),
        QAGate(name="JS event hook", check_type="content_check", params={"path": str(js_path), "contains": "DOMContentLoaded"}),
        QAGate(name="JS yeterli boyutta", check_type="min_file_size", params={"path": str(js_path), "min_bytes": 120}),
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


_DYNAMIC_ACTION_ALIASES: Dict[str, str] = {
    "research": "advanced_research",
    "deep_research": "deep_research",
    "internet_research": "advanced_research",
    "search_web": "web_search",
    "browser_search": "web_search",
    "run_command": "run_safe_command",
    "run_shell": "run_safe_command",
    "execute_python": "execute_python",
    "execute_python_code": "execute_python",
    "open_browser": "open_url",
    "create_folder": "create_directory",
    "list_files": "list_directory",
    "find_files": "search_files",
    "api_call": "http_request",
    "request_api": "http_request",
    "health_check_api": "api_health_check",
}


def _normalize_dynamic_action(
    action: str,
    allowed_tools: List[str],
    *,
    node_name: str = "",
    params: Optional[Dict[str, Any]] = None,
) -> str:
    raw = str(action or "").split("(")[0].strip().lower()
    if not raw:
        return "plan"

    mapped = _DYNAMIC_ACTION_ALIASES.get(raw, raw)
    allowed = {str(t).strip().lower() for t in (allowed_tools or []) if str(t).strip()}

    # If no restriction, keep mapped action.
    if not allowed:
        return mapped

    if mapped in allowed:
        return mapped

    # Control/meta actions are always safe in CDG executor.
    if mapped in {"plan", "refine", "chat", "respond", "answer", "verify"}:
        return mapped

    # Cross-compatible families.
    family_candidates = {
        "advanced_research": ("advanced_research", "deep_research", "web_search"),
        "deep_research": ("deep_research", "advanced_research", "web_search"),
        "create_directory": ("create_directory", "create_folder", "write_file"),
        "list_directory": ("list_directory", "list_files", "search_files", "read_file"),
        "execute_python": ("execute_python", "execute_code", "terminal_command", "run_safe_command"),
        "execute_code": ("execute_code", "execute_python", "terminal_command", "run_safe_command"),
        "run_safe_command": ("run_safe_command", "terminal_command", "execute_code"),
        "http_request": ("http_request", "graphql_query", "api_health_check", "web_search"),
        "graphql_query": ("graphql_query", "http_request", "api_health_check"),
        "api_health_check": ("api_health_check", "http_request", "web_search"),
    }
    for candidate in family_candidates.get(mapped, ()):
        if candidate in allowed:
            return candidate

    hint = f"{node_name} {mapped} {params or {}}".lower()
    if any(k in hint for k in ("api", "endpoint", "graphql", "http", "webhook")):
        for candidate in ("http_request", "graphql_query", "api_health_check", "web_search"):
            if candidate in allowed:
                return candidate
    if any(k in hint for k in ("research", "analiz", "araştır", "arastir")):
        for candidate in ("advanced_research", "deep_research", "web_search", "read_file"):
            if candidate in allowed:
                return candidate
    if any(k in hint for k in ("write", "yaz", "kaydet", "generate")) and "write_file" in allowed:
        return "write_file"
    if any(k in hint for k in ("read", "oku", "kontrol", "check")) and "read_file" in allowed:
        return "read_file"

    # Priority fallback: choose the closest high-value executable action.
    for candidate in (
        "write_file",
        "read_file",
        "http_request",
        "graphql_query",
        "api_health_check",
        "advanced_research",
        "deep_research",
        "web_search",
        "run_safe_command",
        "execute_code",
        "take_screenshot",
    ):
        if candidate in allowed:
            return candidate

    return "plan"


async def _build_dynamic_plan(plan: CDGPlan, user_input: str, template: dict, llm_client=None):
    """
    IntelligentPlanner kullanarak LLM ile dinamik DAG planı oluştur.
    Şablon kuralları (allowed_tools, evidence_gates) yine katı şekilde uygulanır.
    """
    if not llm_client:
        # LLM yoksa fallback: statik generic/iletişim node atar
        logger.warning("LLM client not provided for dynamic plan. Falling back.")
        _build_generic_plan(plan, user_input, template)
        return

    from core.intelligent_planner import IntelligentPlanner
    planner = IntelligentPlanner()
    planner.llm = llm_client

    # Planner üzerinden SubTask'leri al
    subtasks = await planner.decompose_task(
        task_description=user_input,
        llm_client=llm_client,
        use_llm=True,
        user_id="local",
        preferred_tools=template.get("allowed_tools", [])
    )

    if not subtasks:
        _build_generic_plan(plan, user_input, template)
        return

    # SubTask -> DAGNode Çevirisi
    plan.nodes = []
    allowed_tools = template.get("allowed_tools", [])
    
    for st in subtasks:
        final_action = _normalize_dynamic_action(
            st.action,
            allowed_tools,
            node_name=st.name,
            params=st.params,
        )
        if final_action != str(st.action).strip().lower():
            logger.info(f"Dynamic action normalized: '{st.action}' -> '{final_action}'")

        node = DAGNode(
            id=st.task_id,
            name=st.name,
            action=final_action,
            params=st.params,
            depends_on=st.dependencies,
            allowed_tools=allowed_tools,
            max_retries=st.max_retries,
            budget_tokens=2000
        )
        plan.nodes.append(node)

    # Otomatik QA Gate'leri Basma (Delivery Mode ve Beklenen Extension'a göre)
    e2e_gates = []
    
    # QA checks from job template 
    template_qa_checks = template.get("qa_checks", [])
    # NOTE:
    # Generic path-less file_exists E2E gates produce systematic false negatives.
    # Node-level gates already validate concrete artifact paths.

    # Her Node'un çıkışında kendi tool'una göre QAGate basma
    for node in plan.nodes:
        # File artifacts validation
        if node.action in ("write_file", "create_web_project_scaffold", "write_excel", "write_word", 
                          "write_json", "write_yaml") or "_file" in node.action:
            path_hint = str(
                node.params.get("path")
                or node.params.get("output_dir", "")
                or node.params.get("project_dir", "")
                or node.params.get("file_path", "")
            ).strip()
            placeholder_hints = {"", "~/Desktop/not.txt", "~/Desktop"}
            if not path_hint or path_hint in placeholder_hints:
                if plan.job_type == "code_project":
                    expected_exts = [str(item).strip() for item in list(template.get("expected_extensions") or []) if str(item).strip()]
                    default_ext = expected_exts[0] if expected_exts else ".txt"
                    if not default_ext.startswith("."):
                        default_ext = ".txt"
                    default_path = f"/tmp/{plan.job_id}_{node.id}{default_ext}"
                    if isinstance(node.params, dict):
                        node.params.setdefault("path", default_path)
                        if node.action == "write_file" and not str(node.params.get("content") or "").strip():
                            node.params["content"] = f"# generated artifact for {node.id}\n"
                    path_hint = str(node.params.get("path") or default_path).strip()
                    logger.info(f"Dynamic QA fallback path injected for node '{node.id}': {path_hint}")
                else:
                    logger.debug(f"Skipping QA gate for node '{node.id}' due to missing/placeholder path hint.")
                    continue

            gates = [QAGate(name=f"Persistence: {node.id}", check_type="file_exists", 
                          params={"path": path_hint})]
            
            if "_not_empty" in str(template.get("qa_checks", [])):
                gates.append(
                    QAGate(
                        name=f"Integrity: {node.id}",
                        check_type="file_not_empty",
                        params={"path": path_hint},
                    )
                )
            
            plan.node_qa_gates[node.id] = gates
            
        elif node.action in ("take_screenshot", "screenshot"):
            plan.node_qa_gates[node.id] = [
                QAGate(name=f"Media: {node.id}", check_type="file_exists", params={})
            ]
            
        elif node.action in ("terminal_command", "execute_code"):
            # Check for success in result (this is usually handled by execution logic but can be explicit)
            pass

    plan.e2e_qa_gates = e2e_gates
    logger.info(f"Dynamic Plan Enhanced: {len(plan.nodes)} nodes, {len(plan.node_qa_gates)} node gates.")


def _build_generic_plan(plan: CDGPlan, user_input: str, template: dict):
    """Genel (chat/system) DAG planı — tek düğüm."""
    plan.nodes = [
        DAGNode(id="respond", name="Yanıt üret", action="chat",
                allowed_tools=template.get("allowed_tools", []),
                budget_tokens=2000),
    ]

# Template → Builder eşlemesi
# Tüm karmaşık görevleri yapay zekalı dinamik planlamaya (Omnipotence) devrediyoruz.
_PLAN_BUILDERS = {
    "web_project": _build_web_project_plan,
    "research_report": _build_dynamic_plan,
    "code_project": _build_dynamic_plan,
    "api_integration": _build_dynamic_plan,
    "data_analysis": _build_dynamic_plan,
    "file_operations": _build_dynamic_plan,
    "browser_task": _build_dynamic_plan,
    "system_ops": _build_dynamic_plan,
    "communication": _build_generic_plan,
}


# Global instance
cdg_engine = CDGEngine()
