import os
import hashlib
from pathlib import Path
from typing import Any
import fnmatch
from security.validator import validate_path


def _artifact_payload(path: str, *, kind: str = "file") -> dict[str, Any]:
    clean = str(path or "").strip()
    if not clean:
        return {}
    return {"path": clean, "type": str(kind or "file").strip().lower() or "file"}


def _success_payload(*, message: str = "", path: str = "", kind: str = "file", data: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": True,
        "status": "success",
        "message": str(message or "").strip(),
        "retryable": False,
        "data": dict(data or {}),
    }
    clean_path = str(path or "").strip()
    if clean_path:
        payload["path"] = clean_path
        payload["output_path"] = clean_path
        payload["artifacts"] = [_artifact_payload(clean_path, kind=kind)]
    payload.update(extra)
    return payload


def _error_payload(error: str, *, retryable: bool = False, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "status": "failed",
        "error": str(error or "").strip(),
        "errors": [str(error or "").strip()] if str(error or "").strip() else [],
        "retryable": bool(retryable),
        "data": {},
    }
    payload.update(extra)
    return payload

async def apply_patch(path: str, search_text: str, replacement_text: str) -> dict[str, Any]:
    """Surgical file modification. Replaces specific blocks without full overwrite."""
    try:
        valid, msg, p = validate_path(path)
        if not valid: return {"success": False, "error": msg}
        
        if not p.exists():
            return {"success": False, "error": "File not found"}
        
        content = p.read_text(encoding="utf-8")
        if search_text not in content:
            return {"success": False, "error": "Search text not found in file. Patch failed."}
        
        new_content = content.replace(search_text, replacement_text)
        p.write_text(new_content, encoding="utf-8")
        
        return {
            "success": True, 
            "path": str(p), 
            "patch_applied": True,
            "message": "Cerrahi onarım başarıyla uygulandı."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

async def list_files(path: str = ".") -> dict[str, Any]:
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return _error_payload(msg)

    try:
        if not resolved_path.exists():
            return _error_payload(f"Path does not exist: {path}")

        if not resolved_path.is_dir():
            return _error_payload(f"Not a directory: {path}")

        items = []
        for item in resolved_path.iterdir():
            item_type = "dir" if item.is_dir() else "file"
            size = item.stat().st_size if item.is_file() else 0
            items.append({
                "name": item.name,
                "type": item_type,
                "size": size
            })

        items.sort(key=lambda x: (x["type"] == "file", x["name"]))

        return _success_payload(
            path=str(resolved_path),
            kind="directory",
            message=f"{len(items)} oge listelendi.",
            data={"items": items, "count": len(items)},
            items=items,
            count=len(items),
        )

    except PermissionError:
        return _error_payload("Permission denied", retryable=False)
    except Exception as e:
        return _error_payload(str(e), retryable=True)

async def read_file(path: str) -> dict[str, Any]:
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return _error_payload(msg)

    try:
        if not resolved_path.exists():
            return _error_payload(f"File does not exist: {path}")

        if not resolved_path.is_file():
            return _error_payload(f"Not a file: {path}")

        size = resolved_path.stat().st_size
        if size > 100000:
            return _error_payload("File too large (max 100KB)", retryable=False)

        content = resolved_path.read_text(encoding="utf-8", errors="replace")

        return _success_payload(
            path=str(resolved_path),
            kind="text",
            message=f"Dosya okundu: {resolved_path.name}",
            data={"content": content, "size": size, "bytes_read": size},
            content=content,
            size=size,
            bytes_read=size,
        )

    except PermissionError:
        return _error_payload("Permission denied", retryable=False)
    except Exception as e:
        return _error_payload(str(e), retryable=True)

async def write_file(path: str, content: str, allow_short_content: bool = False) -> dict[str, Any]:
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return _error_payload(msg)

    # Rule-2: No wrong format fallback (.docx should use write_word)
    if resolved_path.suffix.lower() == ".docx":
        return _error_payload(
            "DOCX_UNAVAILABLE: .docx dosyaları için 'write_word' aracını kullanmalısınız.",
            retryable=False,
            error_code="DOCX_UNAVAILABLE",
        )

    # Rule-1: No empty or skeleton files
    content_text = str(content or "").strip()
    if len(content_text) < 50 and not bool(allow_short_content):
        return _error_payload(
            f"CONTENT_TOO_SHORT: Dosya içeriği çok kısa ({len(content_text)} karakter). En az 50 karakter olmalı.",
            retryable=False,
            error_code="CONTENT_TOO_SHORT",
        )

    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content_text, encoding="utf-8")

        # Post-check validation
        if not resolved_path.exists():
            return _error_payload("WRITE_FAILED: Dosya diskte bulunamadı.", retryable=True, error_code="FILE_NOT_FOUND")
        
        file_size = resolved_path.stat().st_size
        if file_size < 50 and not bool(allow_short_content):
            return _error_payload(
                f"WRITE_POSTCHECK_FAILED: Dosya boyutu çok küçük ({file_size} bytes).",
                retryable=True,
                error_code="WRITE_POSTCHECK_FAILED",
            )

        sha256 = hashlib.sha256(content_text.encode("utf-8")).hexdigest()

        return _success_payload(
            path=str(resolved_path),
            kind="text",
            message=f"Dosya yazildi: {resolved_path.name}",
            data={
                "size": file_size,
                "bytes_written": file_size,
                "sha256": sha256,
                "preview_200_chars": content_text[:200],
            },
            ok=True,
            size=file_size,
            bytes_written=file_size,
            sha256=sha256,
            preview_200_chars=content_text[:200],
            created_files=[str(resolved_path)],
        )

    except PermissionError:
        return _error_payload("Permission denied", retryable=False)
    except Exception as e:
        return _error_payload(str(e), retryable=True)

async def search_files(pattern: str, directory: str = ".") -> dict[str, Any]:
    valid, msg, resolved_path = validate_path(directory)
    if not valid:
        return _error_payload(msg)

    try:
        if not resolved_path.exists():
            return _error_payload(f"Directory does not exist: {directory}")
        if not resolved_path.is_dir():
            return _error_payload(f"Not a directory: {directory}")

        matches = []
        for root, dirs, files in os.walk(resolved_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for filename in files:
                if fnmatch.fnmatch(filename, pattern):
                    full_path = Path(root) / filename
                    matches.append(str(full_path))

            if len(matches) >= 50:
                break

        matches.sort()
        return _success_payload(
            path=str(resolved_path),
            kind="directory",
            message=f"{len(matches)} eslesen dosya bulundu.",
            data={"pattern": pattern, "directory": str(resolved_path), "matches": matches, "count": len(matches)},
            pattern=pattern,
            directory=str(resolved_path),
            matches=matches,
            count=len(matches),
        )

    except PermissionError:
        return _error_payload("Permission denied", retryable=False)
    except Exception as e:
        return _error_payload(str(e), retryable=True)

async def move_file(source: str, destination: str) -> dict[str, Any]:
    """Dosya veya klasoru tasinir"""
    import shutil

    valid_src, msg_src, src_path = validate_path(source)
    if not valid_src:
        return _error_payload(f"Kaynak hata: {msg_src}")

    valid_dst, msg_dst, dst_path = validate_path(destination)
    if not valid_dst:
        return _error_payload(f"Hedef hata: {msg_dst}")

    try:
        if not src_path.exists():
            return _error_payload(f"Kaynak bulunamadi: {source}")

        # Hedef bir dizinse, dosya adini koru
        if dst_path.is_dir():
            dst_path = dst_path / src_path.name

        if dst_path.exists() and src_path.resolve() != dst_path.resolve():
            return _error_payload(f"Hedef zaten mevcut: {dst_path}", retryable=False)

        # Hedef dizini olustur
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        # Tasi
        shutil.move(str(src_path), str(dst_path))

        if not dst_path.exists():
            return _error_payload("Tasima dogrulamasi basarisiz: hedef bulunamadi.", retryable=True)
        if src_path.exists() and src_path.resolve() != dst_path.resolve():
            return _error_payload("Tasima dogrulamasi basarisiz: kaynak hala mevcut.", retryable=True)

        return _success_payload(
            path=str(dst_path),
            kind="directory" if dst_path.is_dir() else "file",
            message=f"{src_path.name} tasindi: {dst_path}",
            data={"source": str(src_path), "destination": str(dst_path), "filename": dst_path.name, "moved": True},
            source=str(src_path),
            destination=str(dst_path),
            filename=dst_path.name,
            moved=True,
            created_files=[str(dst_path)],
        )

    except PermissionError:
        return _error_payload("Erisim izni yok", retryable=False)
    except Exception as e:
        return _error_payload(f"Tasima hatasi: {str(e)}", retryable=True)


async def copy_file(source: str, destination: str) -> dict[str, Any]:
    """Dosya veya klasoru kopyalar"""
    import shutil

    valid_src, msg_src, src_path = validate_path(source)
    if not valid_src:
        return _error_payload(f"Kaynak hata: {msg_src}")

    valid_dst, msg_dst, dst_path = validate_path(destination)
    if not valid_dst:
        return _error_payload(f"Hedef hata: {msg_dst}")

    try:
        if not src_path.exists():
            return _error_payload(f"Kaynak bulunamadi: {source}")

        # Hedef bir dizinse, dosya adini koru
        if dst_path.is_dir():
            dst_path = dst_path / src_path.name

        if dst_path.exists():
            return _error_payload(f"Hedef zaten mevcut: {dst_path}", retryable=False)

        # Hedef dizini olustur
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        # Kopyala
        if src_path.is_file():
            shutil.copy2(str(src_path), str(dst_path))
        else:
            shutil.copytree(str(src_path), str(dst_path))

        if not dst_path.exists():
            return _error_payload("Kopyalama dogrulamasi basarisiz: hedef bulunamadi.", retryable=True)
        if not src_path.exists():
            return _error_payload("Kopyalama dogrulamasi basarisiz: kaynak kayboldu.", retryable=True)

        return _success_payload(
            path=str(dst_path),
            kind="directory" if dst_path.is_dir() else "file",
            message=f"{src_path.name} kopyalandi: {dst_path}",
            data={"source": str(src_path), "destination": str(dst_path), "filename": dst_path.name, "copied": True},
            source=str(src_path),
            destination=str(dst_path),
            filename=dst_path.name,
            copied=True,
            created_files=[str(dst_path)],
        )

    except PermissionError:
        return _error_payload("Erisim izni yok", retryable=False)
    except Exception as e:
        return _error_payload(f"Kopyalama hatasi: {str(e)}", retryable=True)


async def rename_file(path: str, new_name: str) -> dict[str, Any]:
    """Dosya veya klasoru yeniden adlandirir"""
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return _error_payload(msg)

    try:
        if not resolved_path.exists():
            return _error_payload(f"Dosya bulunamadi: {path}")

        new_path = resolved_path.parent / new_name

        if new_path.exists():
            return _error_payload(f"Bu isimde dosya zaten var: {new_name}", retryable=False)

        resolved_path.rename(new_path)

        if not new_path.exists():
            return _error_payload("Yeniden adlandirma dogrulamasi basarisiz: yeni yol bulunamadi.", retryable=True)
        if resolved_path.exists():
            return _error_payload("Yeniden adlandirma dogrulamasi basarisiz: eski yol hala mevcut.", retryable=True)

        return _success_payload(
            path=str(new_path),
            kind="directory" if new_path.is_dir() else "file",
            message=f"{resolved_path.name} -> {new_name} olarak yeniden adlandirildi",
            data={"old_name": resolved_path.name, "new_name": new_name, "renamed": True},
            old_name=resolved_path.name,
            new_name=new_name,
            renamed=True,
            created_files=[str(new_path)],
        )

    except PermissionError:
        return _error_payload("Erisim izni yok", retryable=False)
    except Exception as e:
        return _error_payload(f"Yeniden adlandirma hatasi: {str(e)}", retryable=True)


async def create_folder(path: str) -> dict[str, Any]:
    """Yeni klasor olusturur"""
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return _error_payload(msg)

    try:
        if resolved_path.exists():
            if resolved_path.is_dir():
                return _success_payload(
                    path=str(resolved_path),
                    kind="directory",
                    message=f"Klasor zaten mevcut: {resolved_path.name}",
                    data={"name": resolved_path.name, "created": False},
                    name=resolved_path.name,
                )
            return _error_payload(f"Bu isimde dosya/klasor zaten var: {path}")

        resolved_path.mkdir(parents=True, exist_ok=True)

        return _success_payload(
            path=str(resolved_path),
            kind="directory",
            message=f"Klasor olusturuldu: {resolved_path.name}",
            data={"name": resolved_path.name, "created": True},
            name=resolved_path.name,
        )

    except PermissionError:
        return _error_payload("Erisim izni yok", retryable=False)
    except Exception as e:
        return _error_payload(f"Klasor olusturma hatasi: {str(e)}", retryable=True)


async def delete_file(
    path: str = "",
    force: bool = False,
    pattern: str = "",
    directory: str = ".",
    recursive: bool = False,
    max_files: int = 200,
    dry_run: bool = False,
    patterns: list[str] | None = None,
) -> dict[str, Any]:
    """Dosya veya klasoru siler (guvenli silme)"""
    resolved_path = None
    raw_path = str(path or "").strip()
    raw_pattern = str(pattern or "").strip()
    pattern_list = [str(p or "").strip() for p in (patterns or []) if str(p or "").strip()]
    if not pattern_list and raw_pattern:
        pattern_list = [raw_pattern]

    try:
        # Bulk delete by glob patterns (safe path + bounded file count).
        if not raw_path and pattern_list:
            valid_dir, msg_dir, resolved_dir = validate_path(directory)
            if not valid_dir:
                return _error_payload(msg_dir)
            if not resolved_dir.exists() or not resolved_dir.is_dir():
                return _error_payload(f"Directory does not exist: {directory}")

            try:
                limit = int(max_files or 200)
            except Exception:
                limit = 200
            limit = max(1, min(2000, limit))

            lowered_patterns = [p.lower() for p in pattern_list]
            candidates: list[Path] = []
            walker = resolved_dir.rglob("*") if bool(recursive) else resolved_dir.glob("*")
            for item in walker:
                if not item.is_file():
                    continue
                name = item.name.lower()
                if any(fnmatch.fnmatch(name, pat) for pat in lowered_patterns):
                    candidates.append(item)
                if len(candidates) >= limit:
                    break

            if bool(dry_run):
                return _success_payload(
                    message=f"{len(candidates)} dosya eşleşti (dry-run).",
                    data={
                        "mode": "dry_run",
                        "directory": str(resolved_dir),
                        "patterns": pattern_list,
                        "matched_count": len(candidates),
                        "matches": [str(p) for p in candidates[:200]],
                    },
                    mode="dry_run",
                    directory=str(resolved_dir),
                    patterns=pattern_list,
                    matched_count=len(candidates),
                    matches=[str(p) for p in candidates[:200]],
                )

            deleted: list[str] = []
            failed: list[dict[str, str]] = []
            for file_path in candidates:
                try:
                    file_path.unlink()
                    deleted.append(str(file_path))
                except Exception as exc:
                    failed.append({"path": str(file_path), "error": str(exc)})

            if not deleted and not failed:
                return _success_payload(
                    message="Eşleşen dosya bulunamadı.",
                    data={
                        "directory": str(resolved_dir),
                        "patterns": pattern_list,
                        "deleted_files": [],
                        "deleted_count": 0,
                    },
                    directory=str(resolved_dir),
                    patterns=pattern_list,
                    deleted_count=0,
                    deleted=[],
                    created_files=[],
                )
            return {
                **_success_payload(
                    message=f"{len(deleted)} dosya silindi.",
                    data={
                        "directory": str(resolved_dir),
                        "patterns": pattern_list,
                        "deleted_files": deleted[:200],
                        "deleted_count": len(deleted),
                        "failed": failed[:50],
                    },
                    directory=str(resolved_dir),
                    patterns=pattern_list,
                    deleted_count=len(deleted),
                    failed_count=len(failed),
                    deleted=deleted[:200],
                    failed=failed[:50],
                    created_files=[],
                ),
                "success": len(deleted) > 0 and len(failed) == 0,
                "status": "success" if len(deleted) > 0 and len(failed) == 0 else "partial",
            }

        valid, msg, resolved_path = validate_path(raw_path)
        if not valid:
            return _error_payload(msg)

        if not resolved_path.exists():
            return _error_payload(f"Path does not exist: {raw_path}")

        # Sistem dosyaları engelle
        forbidden_paths = [".ssh", ".gnupg", ".aws", "Keychain", ".credentials", ".git"]
        if any(forbidden in str(resolved_path) for forbidden in forbidden_paths):
            return _error_payload("Sistem dosyası silinemez (güvenlik)", retryable=False)

        # Dosya veya klasörü sil
        if resolved_path.is_file():
            resolved_path.unlink()
            return _success_payload(
                path=str(resolved_path),
                kind="file",
                message=f"Dosya silindi: {resolved_path.name}",
                data={"deleted": True, "deleted_files": [str(resolved_path)]},
                type="file",
                created_files=[],
                deleted_files=[str(resolved_path)],
            )
        elif resolved_path.is_dir():
            # Boş klasörler sadece silinebilir
            if not force and list(resolved_path.iterdir()):
                return _error_payload("Klasör boş değil. force=true ile silebilirsiniz", retryable=False)
            
            import shutil
            shutil.rmtree(resolved_path)
            return _success_payload(
                path=str(resolved_path),
                kind="directory",
                message=f"Klasör silindi: {resolved_path.name}",
                data={"deleted": True, "deleted_files": [str(resolved_path)]},
                type="directory",
                created_files=[],
                deleted_files=[str(resolved_path)],
            )

        return _error_payload("Geçersiz path")

    except PermissionError:
        return _error_payload("Permission denied", retryable=False)
    except Exception as e:
        return _error_payload(f"Silme hatası: {str(e)}", retryable=True)
