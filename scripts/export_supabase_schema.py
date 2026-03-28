from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.persistence.supabase_schema import write_supabase_bootstrap_files


def main() -> int:
    output_root = ROOT / "db" / "supabase"
    schema_path, rls_path = write_supabase_bootstrap_files(output_root)
    print(schema_path)
    print(rls_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
