from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import sys
from pathlib import Path
from typing import Callable, Iterable


def _iter_candidate_roots() -> Iterable[Path]:
    seen: set[str] = set()

    env_root = os.environ.get("ELYAN_PROJECT_DIR", "").strip()
    if env_root:
        p = Path(env_root).expanduser().resolve()
        key = str(p)
        if key not in seen:
            seen.add(key)
            yield p

    cwd = Path.cwd().resolve()
    key = str(cwd)
    if key not in seen:
        seen.add(key)
        yield cwd

    # Editable install mapping (setuptools __editable__ finder).
    for finder_name in list(sys.modules):
        if finder_name.startswith("__editable___elyan_") and finder_name.endswith("_finder"):
            try:
                finder_mod = importlib.import_module(finder_name)
                mapping = getattr(finder_mod, "MAPPING", {}) or {}
                cli_dir = mapping.get("cli")
                if cli_dir:
                    root = Path(str(cli_dir)).resolve().parent
                    root_key = str(root)
                    if root_key not in seen:
                        seen.add(root_key)
                        yield root
            except Exception:
                continue

    # Installed wheel location fallback.
    here = Path(__file__).resolve().parent
    here_key = str(here)
    if here_key not in seen:
        seen.add(here_key)
        yield here


def _load_main_from_file(cli_main_path: Path) -> Callable[[list[str] | None], int | None]:
    spec = importlib.util.spec_from_file_location("elyan_cli_runtime_main", str(cli_main_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"spec load failed: {cli_main_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    main_fn = getattr(module, "main", None)
    if not callable(main_fn):
        raise RuntimeError(f"main() not found in {cli_main_path}")
    return main_fn


def _invoke_main(main_fn: Callable, argv: list[str] | None):
    """
    Backward-compatible entrypoint invocation.
    Supports both `main()` and `main(argv)` signatures.
    """
    try:
        sig = inspect.signature(main_fn)
        params = list(sig.parameters.values())
        has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
        if has_varargs or len(params) >= 1:
            return main_fn(argv)
        return main_fn()
    except TypeError as exc:
        # Defensive fallback for dynamically wrapped main() functions.
        msg = str(exc)
        if "positional arguments but" in msg and "main()" in msg:
            return main_fn()
        raise


def main(argv: list[str] | None = None):
    errors: list[str] = []
    for root in _iter_candidate_roots():
        cli_candidates = (
            root / "elyan" / "cli" / "main.py",
            root / "cli" / "main.py",
        )
        cli_main = next((path for path in cli_candidates if path.exists()), None)
        if cli_main is None:
            continue
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        os.environ.setdefault("ELYAN_PROJECT_DIR", root_str)
        try:
            return _invoke_main(_load_main_from_file(cli_main), argv)
        except Exception as exc:
            errors.append(f"{cli_main}: {exc}")
            continue

    if errors:
        raise SystemExit("Elyan CLI bootstrap failed:\n- " + "\n- ".join(errors))
    raise SystemExit("Elyan CLI bootstrap failed: cli/main.py bulunamadı.")


if __name__ == "__main__":
    raise SystemExit(main())
