from __future__ import annotations

from typing import Any


def _read_nested(dct: dict[str, Any], *keys: str) -> Any:
    cur: Any = dct
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def flag_enabled(ctx: Any, name: str, default: bool = False) -> bool:
    """Resolve upgrade feature flags from runtime policy and config.

    Priority:
    1) ctx.runtime_policy.feature_flags[name]
    2) ctx.runtime_policy.flags[name]
    3) config key: agent.flags.<name>
    """
    try:
        policy = getattr(ctx, "runtime_policy", None)
        if isinstance(policy, dict):
            val = _read_nested(policy, "feature_flags", name)
            if isinstance(val, bool):
                return val
            val = _read_nested(policy, "flags", name)
            if isinstance(val, bool):
                return val
    except Exception:
        pass

    try:
        from config.elyan_config import elyan_config

        conf = elyan_config.get(f"agent.flags.{name}", default)
        if isinstance(conf, bool):
            return conf
    except Exception:
        pass

    return bool(default)
