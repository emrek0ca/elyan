import os
from pathlib import Path
from typing import Any
import fnmatch
from security.validator import validate_path

async def list_files(path: str = ".") -> dict[str, Any]:
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return {"success": False, "error": msg}

    try:
        if not resolved_path.exists():
            return {"success": False, "error": f"Path does not exist: {path}"}

        if not resolved_path.is_dir():
            return {"success": False, "error": f"Not a directory: {path}"}

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

        return {
            "success": True,
            "path": str(resolved_path),
            "items": items,
            "count": len(items)
        }

    except PermissionError:
        return {"success": False, "error": "Permission denied"}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def read_file(path: str) -> dict[str, Any]:
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return {"success": False, "error": msg}

    try:
        if not resolved_path.exists():
            return {"success": False, "error": f"File does not exist: {path}"}

        if not resolved_path.is_file():
            return {"success": False, "error": f"Not a file: {path}"}

        size = resolved_path.stat().st_size
        if size > 100000:
            return {"success": False, "error": "File too large (max 100KB)"}

        content = resolved_path.read_text(encoding="utf-8", errors="replace")

        return {
            "success": True,
            "path": str(resolved_path),
            "content": content,
            "size": size
        }

    except PermissionError:
        return {"success": False, "error": "Permission denied"}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def write_file(path: str, content: str) -> dict[str, Any]:
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return {"success": False, "error": msg}

    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "path": str(resolved_path),
            "size": len(content.encode("utf-8"))
        }

    except PermissionError:
        return {"success": False, "error": "Permission denied"}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def search_files(pattern: str, directory: str = ".") -> dict[str, Any]:
    valid, msg, resolved_path = validate_path(directory)
    if not valid:
        return {"success": False, "error": msg}

    try:
        if not resolved_path.exists():
            return {"success": False, "error": f"Directory does not exist: {directory}"}

        matches = []
        for root, dirs, files in os.walk(resolved_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for filename in files:
                if fnmatch.fnmatch(filename, pattern):
                    full_path = Path(root) / filename
                    matches.append(str(full_path))

            if len(matches) >= 50:
                break

        return {
            "success": True,
            "pattern": pattern,
            "directory": str(resolved_path),
            "matches": matches,
            "count": len(matches)
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

async def move_file(source: str, destination: str) -> dict[str, Any]:
    """Dosya veya klasoru tasinir"""
    import shutil

    valid_src, msg_src, src_path = validate_path(source)
    if not valid_src:
        return {"success": False, "error": f"Kaynak hata: {msg_src}"}

    valid_dst, msg_dst, dst_path = validate_path(destination)
    if not valid_dst:
        return {"success": False, "error": f"Hedef hata: {msg_dst}"}

    try:
        if not src_path.exists():
            return {"success": False, "error": f"Kaynak bulunamadi: {source}"}

        # Hedef bir dizinse, dosya adini koru
        if dst_path.is_dir():
            dst_path = dst_path / src_path.name

        # Hedef dizini olustur
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        # Tasi
        shutil.move(str(src_path), str(dst_path))

        return {
            "success": True,
            "source": str(src_path),
            "destination": str(dst_path),
            "filename": dst_path.name,
            "message": f"{src_path.name} tasindi: {dst_path}"
        }

    except PermissionError:
        return {"success": False, "error": "Erisim izni yok"}
    except Exception as e:
        return {"success": False, "error": f"Tasima hatasi: {str(e)}"}


async def copy_file(source: str, destination: str) -> dict[str, Any]:
    """Dosya veya klasoru kopyalar"""
    import shutil

    valid_src, msg_src, src_path = validate_path(source)
    if not valid_src:
        return {"success": False, "error": f"Kaynak hata: {msg_src}"}

    valid_dst, msg_dst, dst_path = validate_path(destination)
    if not valid_dst:
        return {"success": False, "error": f"Hedef hata: {msg_dst}"}

    try:
        if not src_path.exists():
            return {"success": False, "error": f"Kaynak bulunamadi: {source}"}

        # Hedef bir dizinse, dosya adini koru
        if dst_path.is_dir():
            dst_path = dst_path / src_path.name

        # Hedef dizini olustur
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        # Kopyala
        if src_path.is_file():
            shutil.copy2(str(src_path), str(dst_path))
        else:
            shutil.copytree(str(src_path), str(dst_path))

        return {
            "success": True,
            "source": str(src_path),
            "destination": str(dst_path),
            "filename": dst_path.name,
            "message": f"{src_path.name} kopyalandi: {dst_path}"
        }

    except PermissionError:
        return {"success": False, "error": "Erisim izni yok"}
    except Exception as e:
        return {"success": False, "error": f"Kopyalama hatasi: {str(e)}"}


async def rename_file(path: str, new_name: str) -> dict[str, Any]:
    """Dosya veya klasoru yeniden adlandirir"""
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return {"success": False, "error": msg}

    try:
        if not resolved_path.exists():
            return {"success": False, "error": f"Dosya bulunamadi: {path}"}

        new_path = resolved_path.parent / new_name

        if new_path.exists():
            return {"success": False, "error": f"Bu isimde dosya zaten var: {new_name}"}

        resolved_path.rename(new_path)

        return {
            "success": True,
            "old_name": resolved_path.name,
            "new_name": new_name,
            "path": str(new_path),
            "message": f"{resolved_path.name} -> {new_name} olarak yeniden adlandirildi"
        }

    except PermissionError:
        return {"success": False, "error": "Erisim izni yok"}
    except Exception as e:
        return {"success": False, "error": f"Yeniden adlandirma hatasi: {str(e)}"}


async def create_folder(path: str) -> dict[str, Any]:
    """Yeni klasor olusturur"""
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return {"success": False, "error": msg}

    try:
        if resolved_path.exists():
            return {"success": False, "error": f"Bu isimde dosya/klasor zaten var: {path}"}

        resolved_path.mkdir(parents=True, exist_ok=True)

        return {
            "success": True,
            "path": str(resolved_path),
            "name": resolved_path.name,
            "message": f"Klasor olusturuldu: {resolved_path.name}"
        }

    except PermissionError:
        return {"success": False, "error": "Erisim izni yok"}
    except Exception as e:
        return {"success": False, "error": f"Klasor olusturma hatasi: {str(e)}"}


async def delete_file(path: str, force: bool = False) -> dict[str, Any]:
    """Dosya veya klasoru siler (guvenli silme)"""
    valid, msg, resolved_path = validate_path(path)
    if not valid:
        return {"success": False, "error": msg}

    try:
        if not resolved_path.exists():
            return {"success": False, "error": f"Path does not exist: {path}"}

        # Sistem dosyaları engelle
        forbidden_paths = [".ssh", ".gnupg", ".aws", "Keychain", ".credentials", ".git"]
        if any(forbidden in str(resolved_path) for forbidden in forbidden_paths):
            return {"success": False, "error": "Sistem dosyası silinemez (güvenlik)"}

        # Dosya veya klasörü sil
        if resolved_path.is_file():
            resolved_path.unlink()
            return {
                "success": True,
                "path": str(resolved_path),
                "type": "file",
                "message": f"Dosya silindi: {resolved_path.name}"
            }
        elif resolved_path.is_dir():
            # Boş klasörler sadece silinebilir
            if not force and list(resolved_path.iterdir()):
                return {"success": False, "error": "Klasör boş değil. force=true ile silebilirsiniz"}
            
            import shutil
            shutil.rmtree(resolved_path)
            return {
                "success": True,
                "path": str(resolved_path),
                "type": "directory",
                "message": f"Klasör silindi: {resolved_path.name}"
            }

        return {"success": False, "error": "Geçersiz path"}

    except PermissionError:
        return {"success": False, "error": "Permission denied"}
    except Exception as e:
        return {"success": False, "error": f"Silme hatası: {str(e)}"}
