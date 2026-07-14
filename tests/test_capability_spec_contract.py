"""Tek Spec mimarisi sözleşmeleri: spec listesi tüm katmanlara eksiksiz türer."""

from __future__ import annotations

from importlib import import_module

from runtime import capability_registry as cr
from runtime import capability_spec
from runtime import safety_policy

_FULL_ACCESS_STATE = {"runtime": {"access": {"fullAccessSession": {"enabled": True}}}}


def test_every_spec_derives_into_all_layers() -> None:
    catalog_names = {str(item.get("name", "")) for item in cr.TOOL_DECLARATIONS}
    handlers = cr._handlers()
    for spec in capability_spec.SPECS:
        # 1) Adapter gerçek bir fonksiyona çözülür
        module = import_module(spec.module)
        handler_fn = getattr(module, spec.attribute, None)
        assert callable(handler_fn), f"{spec.name}: {spec.module}.{spec.attribute} yok"
        # 2) Planlayıcı kataloğunda decl var
        assert spec.name in catalog_names, f"{spec.name} katalogda yok"
        # 3) Çalıştırma handler'ı üretilmiş
        assert spec.name in handlers, f"{spec.name} handler yok"
        # 4) Metadata spec ile uyumlu (kategori/doğrulama/yan-etki)
        readiness = cr.capability_readiness(spec.name)
        assert readiness.get("category") == spec.category, spec.name
        assert readiness.get("verificationMode") == spec.verification_mode, spec.name
        assert readiness.get("sideEffect") == spec.side_effect, spec.name
        # 5) Görünen ad
        if spec.display_name:
            assert cr.capability_display_name(spec.name) == spec.display_name
        # 6) Politika kapısı spec'ten çalışır
        decision_no_perm = safety_policy.evaluate_tool(spec.name, {}, {})
        if spec.policy == "open":
            assert decision_no_perm.allowed, spec.name
        elif spec.policy == "confirm":
            assert not decision_no_perm.allowed, spec.name
            assert safety_policy.evaluate_tool(spec.name, {"_confirmed": True}, {}).allowed, spec.name
        elif spec.policy.startswith("permission:"):
            assert not decision_no_perm.allowed, spec.name
            assert safety_policy.evaluate_tool(spec.name, {}, _FULL_ACCESS_STATE).allowed, spec.name


def test_spec_handler_maps_aliases_and_types() -> None:
    calls: dict[str, object] = {}

    def _fake_loader(_name: str):
        def _adapter(**kwargs):
            calls.update(kwargs)
            return {"ok": True}
        return _adapter

    spec = capability_spec.spec_for("browser_agent.run")
    assert spec is not None
    handler = capability_spec.build_handler(spec, _fake_loader)
    handler({"goal": "linkleri topla", "maxTurns": "8"})
    assert calls == {"goal": "linkleri topla", "max_turns": 8}  # alias + sayı dönüşümü

    calls.clear()
    type_spec = capability_spec.spec_for("browser_session.type")
    assert type_spec is not None
    capability_spec.build_handler(type_spec, _fake_loader)(
        {"text_value": "merhaba", "submit": "true"}
    )
    assert calls["value"] == "merhaba" and calls["submit"] is True
