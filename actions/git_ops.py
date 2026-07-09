"""Masaüstü kod-ajanı için READ-ONLY git introspection: git_status, git_diff.

Yalnız okuma alt-komutları çalıştırır (status/diff). Mutasyon (commit/push/
checkout) bu modülde YOKTUR; onlar git_guard + WRITE/external izin kapısından
geçmelidir.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from runtime.capability_registry import SafeCapabilityError

_MAX_DIFF_CHARS = 12_000
_GIT_TIMEOUT = 15


def _git_binary() -> str:
    binary = shutil.which("git")
    if not binary:
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "git bu sistemde bulunamadı.")
    return binary


def _resolve_repo_root(path: str) -> Path:
    candidate = str(path or ".").strip() or "."
    start = Path(candidate).expanduser()
    if not start.is_absolute():
        start = Path.cwd() / start
    start = start.resolve()
    if start.is_file():
        start = start.parent
    if not start.exists():
        raise SafeCapabilityError("FILE_NOT_FOUND", "Belirtilen yol bulunamadı.")
    try:
        completed = subprocess.run(
            [_git_binary(), "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise SafeCapabilityError("TOOL_EXECUTION_FAILED", "git çalıştırılamadı.") from exc
    root = completed.stdout.strip()
    if completed.returncode != 0 or not root:
        raise SafeCapabilityError("NOT_A_REPO", "Bu klasör bir git deposu değil.")
    return Path(root)


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [_git_binary(), "-C", str(root), *args],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise SafeCapabilityError("TOOL_EXECUTION_FAILED", "git komutu çalıştırılamadı.") from exc


def _current_branch(root: Path) -> str:
    """Aktif branch adını sağlam biçimde okur (doğmamış/detached HEAD dahil)."""
    name = _run_git(root, ["branch", "--show-current"]).stdout.strip()
    if name:
        return name
    ref = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    return ref if ref and ref != "HEAD" else "(detached)"


def git_status(path: str = ".") -> dict[str, Any]:
    """Çalışma ağacının durumunu (branch + değişiklikler) yapılandırılmış döndürür."""
    root = _resolve_repo_root(path)
    branch = _current_branch(root)
    porcelain = _run_git(root, ["status", "--porcelain=v1"])
    if porcelain.returncode != 0:
        raise SafeCapabilityError("TOOL_EXECUTION_FAILED", porcelain.stderr.strip()[:200] or "git status başarısız.")

    staged: list[dict[str, str]] = []
    unstaged: list[dict[str, str]] = []
    untracked: list[str] = []
    for line in porcelain.stdout.splitlines():
        if not line:
            continue
        index_state, worktree_state, file_name = line[0], line[1], line[3:]
        if index_state == "?" and worktree_state == "?":
            untracked.append(file_name)
            continue
        if index_state not in (" ", "?"):
            staged.append({"status": index_state, "file": file_name})
        if worktree_state not in (" ", "?"):
            unstaged.append({"status": worktree_state, "file": file_name})

    total = len(staged) + len(unstaged) + len(untracked)
    if total == 0:
        text = f"[{branch}] çalışma ağacı temiz."
    else:
        parts = [f"[{branch}] {total} değişiklik:"]
        if staged:
            parts.append("Staged:\n" + "\n".join(f"  {e['status']} {e['file']}" for e in staged))
        if unstaged:
            parts.append("Unstaged:\n" + "\n".join(f"  {e['status']} {e['file']}" for e in unstaged))
        if untracked:
            parts.append("Untracked:\n" + "\n".join(f"  {f}" for f in untracked))
        text = "\n".join(parts)

    return {
        "text": text,
        "result": {
            "kind": "git_status",
            "root": str(root),
            "branch": branch,
            "clean": total == 0,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "changeCount": total,
        },
        "artifacts": [],
    }


def git_diff(path: str = ".", staged: bool = False, target_file: str = "") -> dict[str, Any]:
    """Çalışma ağacındaki (veya --staged) diff'i döndürür; büyük çıktı kısaltılır."""
    root = _resolve_repo_root(path)
    args = ["diff", "--no-color"]
    if staged:
        args.append("--staged")
    target = str(target_file or "").strip()
    if target:
        args += ["--", target]
    completed = _run_git(root, args)
    if completed.returncode != 0:
        raise SafeCapabilityError("TOOL_EXECUTION_FAILED", completed.stderr.strip()[:200] or "git diff başarısız.")

    diff_text = completed.stdout
    truncated = len(diff_text) > _MAX_DIFF_CHARS
    shown = diff_text[:_MAX_DIFF_CHARS]
    files_changed = sum(1 for line in diff_text.splitlines() if line.startswith("diff --git "))

    if not diff_text.strip():
        scope = "staged" if staged else "çalışma ağacı"
        text = f"[{root.name}] {scope}: fark yok."
    else:
        text = shown + ("\n… (diff kısaltıldı)" if truncated else "")

    return {
        "text": text,
        "result": {
            "kind": "git_diff",
            "root": str(root),
            "staged": bool(staged),
            "targetFile": target,
            "filesChanged": files_changed,
            "truncated": truncated,
            "byteSize": len(diff_text),
        },
        "artifacts": [],
    }


# ── Mutasyon (git_guard) — YEREL değişiklikler. PUSH/REMOTE burada YOK. ─────────
def git_commit(path: str = ".", message: str = "", add_all: bool = True, _confirmed: bool = False) -> dict[str, Any]:
    """Değişiklikleri commit'ler (opsiyonel `git add -A`). Uzağa PUSH YAPMAZ."""
    commit_message = " ".join(str(message or "").split()).strip()
    if not commit_message:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Commit mesajı gerekli.")
    root = _resolve_repo_root(path)

    if add_all:
        staged = _run_git(root, ["add", "-A"])
        if staged.returncode != 0:
            raise SafeCapabilityError("TOOL_EXECUTION_FAILED", staged.stderr.strip()[:200] or "git add başarısız.")

    # Commit edilecek bir şey var mı?
    pending = _run_git(root, ["status", "--porcelain=v1"]).stdout.strip()
    staged_diff = _run_git(root, ["diff", "--cached", "--name-only"]).stdout.strip()
    if not staged_diff:
        detail = "Çalışma ağacı temiz." if not pending else "Staged değişiklik yok (önce ekle)."
        raise SafeCapabilityError("NOTHING_TO_COMMIT", detail)

    completed = _run_git(root, ["commit", "-m", commit_message])
    if completed.returncode != 0:
        raise SafeCapabilityError("TOOL_EXECUTION_FAILED", completed.stderr.strip()[:200] or "git commit başarısız.")

    commit_hash = _run_git(root, ["rev-parse", "HEAD"]).stdout.strip()[:12]
    branch = _current_branch(root)
    files = [f for f in staged_diff.splitlines() if f]

    return {
        "text": f"[{branch} {commit_hash}] {commit_message}\n{len(files)} dosya commit'lendi. (push YAPILMADI)",
        "result": {
            "kind": "git_commit",
            "root": str(root),
            "branch": branch,
            "commit": commit_hash,
            "message": commit_message,
            "filesCommitted": files,
            "pushed": False,
        },
        "artifacts": [],
    }


def git_branch(path: str = ".", name: str = "", checkout: bool = True, _confirmed: bool = False) -> dict[str, Any]:
    """Yeni bir branch oluşturur (varsayılan: oluşturup ona geçer)."""
    branch_name = str(name or "").strip()
    if not branch_name or any(ch.isspace() for ch in branch_name):
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçerli bir branch adı gerekli (boşluksuz).")
    root = _resolve_repo_root(path)

    args = ["checkout", "-b", branch_name] if checkout else ["branch", branch_name]
    completed = _run_git(root, args)
    if completed.returncode != 0:
        raise SafeCapabilityError("TOOL_EXECUTION_FAILED", completed.stderr.strip()[:200] or "git branch başarısız.")

    current = _current_branch(root)
    verb = "oluşturuldu ve geçildi" if checkout else "oluşturuldu"
    return {
        "text": f"'{branch_name}' branch'i {verb}. (aktif: {current})",
        "result": {
            "kind": "git_branch",
            "root": str(root),
            "branch": branch_name,
            "checkedOut": bool(checkout),
            "currentBranch": current,
        },
        "artifacts": [],
    }
