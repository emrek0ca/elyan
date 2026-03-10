from core.auto_patch import AutoPatchEngine
from core.cdg_engine import DAGNode, QAGate


def test_auto_patch_missing_file_ignores_none_paths():
    engine = AutoPatchEngine()
    node = DAGNode(id="n1", name="Draft", action="write_file", params={})
    gates = [
        QAGate(name="file_exists", check_type="file_exists", params={"path": None}),
        QAGate(name="file_exists", check_type="file_exists", params={"path": "/tmp/report.md"}),
    ]

    patched = engine._patch_missing_file(node, gates)
    assert patched is True
    assert "/tmp/report.md" in str(node.params.get("_auto_patch_instruction", ""))
