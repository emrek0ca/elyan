"""
Architecture boundary enforcement.
Bu testler katman kirlenmesini dakikalar içinde yakalar.
"""

import ast
import pathlib


def _imports_in_file(path: str) -> list[str]:
    src = pathlib.Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
    return modules


def test_agent_does_not_import_legacy_billing():
    imports = _imports_in_file("core/agent.py")
    legacy = [m for m in imports if "billing.subscription" in m]
    assert not legacy, (
        f"core/agent.py legacy billing import içermemeli: {legacy}\n"
        "workspace_billing kullan veya import'u kaldır."
    )


def test_gateway_server_does_not_import_agent_directly():
    imports = _imports_in_file("core/gateway/server.py")
    direct = [m for m in imports if m == "core.agent" or m.startswith("core.agent.")]
    assert not direct, (
        f"gateway/server.py agent'ı doğrudan import etmemeli: {direct}"
    )


def test_billing_module_does_not_import_gateway():
    billing_files = list(pathlib.Path("core/billing").glob("*.py"))
    for f in billing_files:
        imports = _imports_in_file(str(f))
        gw = [m for m in imports if "gateway" in m]
        assert not gw, (
            f"{f} gateway import içermemeli: {gw}\n"
            "Billing modülü gateway'e bağımlı olamaz."
        )
