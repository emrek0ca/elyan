"""
Metin Dosyası Düzenleyici - Text Editor
Replace, insert, delete, append, prepend operasyonları
"""

import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any
from security.validator import validate_path
from utils.logger import get_logger

logger = get_logger("text_editor")


async def edit_text_file(
    path: str,
    operations: list[dict],
    create_backup: bool = True,
    encoding: str = "utf-8"
) -> dict[str, Any]:
    """
    Metin dosyasını düzenle

    Args:
        path: Dosya yolu
        operations: Düzenleme operasyonları listesi
            Her operasyon:
            - {"type": "replace", "find": str, "replace": str, "all": bool}
            - {"type": "insert", "line": int, "text": str}
            - {"type": "delete", "line": int} veya {"type": "delete", "start": int, "end": int}
            - {"type": "append", "text": str}
            - {"type": "prepend", "text": str}
            - {"type": "regex_replace", "pattern": str, "replace": str, "flags": str}
        create_backup: Yedek oluştur
        encoding: Dosya encoding'i

    Returns:
        dict: Düzenleme sonucu
    """
    try:
        # Convenience: LLM sıkça find/replace string olarak geçiyor → operations listine çevir
        if isinstance(operations, str):
            # edit_text_file(path, "find_text", "replace_text") şeklinde çağrıldıysa
            operations = [{"type": "replace", "find": operations, "replace": "", "all": True}]
        elif isinstance(operations, list) and operations and isinstance(operations[0], str):
            # ["find", "replace"] list of strings
            if len(operations) >= 2:
                operations = [{"type": "replace", "find": operations[0], "replace": operations[1], "all": True}]
            else:
                operations = [{"type": "replace", "find": operations[0], "replace": "", "all": True}]
        elif isinstance(operations, dict):
            # Single operation dict instead of list
            operations = [operations]

        valid, msg, resolved_path = validate_path(path)
        if not valid:
            return {"success": False, "error": msg}

        if not resolved_path.exists():
            return {"success": False, "error": f"Dosya bulunamadı: {path}"}

        if not resolved_path.is_file():
            return {"success": False, "error": f"Bu bir dosya değil: {path}"}

        # Check file size
        size = resolved_path.stat().st_size
        if size > 10 * 1024 * 1024:  # 10MB limit
            return {"success": False, "error": "Dosya çok büyük (max 10MB)"}

        # Read current content
        try:
            content = resolved_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            return {"success": False, "error": f"Dosya {encoding} formatında okunamadı"}

        original_content = content
        lines = content.split("\n")
        changes_made = []

        # Create backup
        if create_backup:
            backup_path = resolved_path.with_suffix(
                f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{resolved_path.suffix}"
            )
            shutil.copy2(resolved_path, backup_path)
            logger.info(f"Yedek oluşturuldu: {backup_path.name}")

        # Apply operations
        for i, op in enumerate(operations):
            op_type = op.get("type", "").lower()

            if op_type == "replace":
                find_text = op.get("find", "")
                replace_text = op.get("replace", "")
                replace_all = op.get("all", True)

                if not find_text:
                    changes_made.append({"op": i+1, "type": "replace", "error": "find parametresi gerekli"})
                    continue

                if replace_all:
                    count = content.count(find_text)
                    content = content.replace(find_text, replace_text)
                else:
                    count = 1 if find_text in content else 0
                    content = content.replace(find_text, replace_text, 1)

                changes_made.append({
                    "op": i+1,
                    "type": "replace",
                    "find": find_text[:50],
                    "count": count
                })

            elif op_type == "regex_replace":
                pattern = op.get("pattern", "")
                replace_text = op.get("replace", "")
                flags_str = op.get("flags", "")

                if not pattern:
                    changes_made.append({"op": i+1, "type": "regex_replace", "error": "pattern parametresi gerekli"})
                    continue

                # Parse flags
                flags = 0
                if "i" in flags_str:
                    flags |= re.IGNORECASE
                if "m" in flags_str:
                    flags |= re.MULTILINE
                if "s" in flags_str:
                    flags |= re.DOTALL

                try:
                    new_content, count = re.subn(pattern, replace_text, content, flags=flags)
                    content = new_content
                    changes_made.append({
                        "op": i+1,
                        "type": "regex_replace",
                        "pattern": pattern,
                        "count": count
                    })
                except re.error as e:
                    changes_made.append({"op": i+1, "type": "regex_replace", "error": f"Geçersiz regex: {e}"})

            elif op_type == "insert":
                line_num = op.get("line", 0)
                text = op.get("text", "")

                lines = content.split("\n")
                if 0 <= line_num <= len(lines):
                    lines.insert(line_num, text)
                    content = "\n".join(lines)
                    changes_made.append({
                        "op": i+1,
                        "type": "insert",
                        "line": line_num,
                        "text": text[:50]
                    })
                else:
                    changes_made.append({
                        "op": i+1,
                        "type": "insert",
                        "error": f"Geçersiz satır numarası: {line_num}"
                    })

            elif op_type == "delete":
                lines = content.split("\n")

                if "line" in op:
                    line_num = op["line"]
                    if 0 <= line_num < len(lines):
                        deleted_line = lines.pop(line_num)
                        content = "\n".join(lines)
                        changes_made.append({
                            "op": i+1,
                            "type": "delete",
                            "line": line_num,
                            "deleted": deleted_line[:50]
                        })
                    else:
                        changes_made.append({
                            "op": i+1,
                            "type": "delete",
                            "error": f"Geçersiz satır numarası: {line_num}"
                        })

                elif "start" in op and "end" in op:
                    start = op["start"]
                    end = op["end"]
                    if 0 <= start < end <= len(lines):
                        deleted_count = end - start
                        del lines[start:end]
                        content = "\n".join(lines)
                        changes_made.append({
                            "op": i+1,
                            "type": "delete",
                            "start": start,
                            "end": end,
                            "deleted_count": deleted_count
                        })
                    else:
                        changes_made.append({
                            "op": i+1,
                            "type": "delete",
                            "error": f"Geçersiz aralık: {start}-{end}"
                        })

            elif op_type == "append":
                text = op.get("text", "")
                content = content + "\n" + text if content else text
                changes_made.append({
                    "op": i+1,
                    "type": "append",
                    "text": text[:50]
                })

            elif op_type == "prepend":
                text = op.get("text", "")
                content = text + "\n" + content if content else text
                changes_made.append({
                    "op": i+1,
                    "type": "prepend",
                    "text": text[:50]
                })

            else:
                changes_made.append({
                    "op": i+1,
                    "type": op_type,
                    "error": f"Bilinmeyen operasyon tipi: {op_type}"
                })

        # Check if content changed
        if content == original_content:
            return {
                "success": True,
                "path": str(resolved_path),
                "filename": resolved_path.name,
                "changes": changes_made,
                "modified": False,
                "message": "Dosyada değişiklik yapılmadı"
            }

        # Write modified content
        resolved_path.write_text(content, encoding=encoding)

        logger.info(f"Dosya düzenlendi: {resolved_path.name} - {len(changes_made)} operasyon")

        return {
            "success": True,
            "path": str(resolved_path),
            "filename": resolved_path.name,
            "changes": changes_made,
            "modified": True,
            "backup_created": create_backup,
            "message": f"Dosya düzenlendi: {len(changes_made)} operasyon uygulandı"
        }

    except Exception as e:
        logger.error(f"Dosya düzenleme hatası: {e}")
        return {"success": False, "error": f"Dosya düzenlenemedi: {str(e)}"}


async def batch_edit_text(
    directory: str,
    pattern: str,
    operations: list[dict],
    create_backup: bool = True,
    recursive: bool = False
) -> dict[str, Any]:
    """
    Birden fazla metin dosyasını toplu düzenle

    Args:
        directory: Dizin yolu
        pattern: Dosya deseni (örn: "*.txt", "*.md")
        operations: Düzenleme operasyonları
        create_backup: Yedek oluştur
        recursive: Alt dizinleri de tara

    Returns:
        dict: Toplu düzenleme sonucu
    """
    try:
        valid, msg, resolved_path = validate_path(directory)
        if not valid:
            return {"success": False, "error": msg}

        if not resolved_path.is_dir():
            return {"success": False, "error": f"Dizin bulunamadı: {directory}"}

        # Find matching files
        if recursive:
            files = list(resolved_path.rglob(pattern))
        else:
            files = list(resolved_path.glob(pattern))

        # Limit number of files
        max_files = 50
        if len(files) > max_files:
            return {
                "success": False,
                "error": f"Çok fazla dosya bulundu ({len(files)}). Maksimum {max_files} dosya düzenlenebilir."
            }

        results = []
        modified_count = 0
        error_count = 0

        for file_path in files:
            result = await edit_text_file(
                str(file_path),
                operations,
                create_backup=create_backup
            )

            results.append({
                "file": file_path.name,
                "success": result.get("success", False),
                "modified": result.get("modified", False),
                "error": result.get("error")
            })

            if result.get("modified"):
                modified_count += 1
            if not result.get("success"):
                error_count += 1

        return {
            "success": True,
            "directory": str(resolved_path),
            "pattern": pattern,
            "total_files": len(files),
            "modified_count": modified_count,
            "error_count": error_count,
            "results": results,
            "message": f"{modified_count}/{len(files)} dosya düzenlendi"
        }

    except Exception as e:
        logger.error(f"Toplu düzenleme hatası: {e}")
        return {"success": False, "error": f"Toplu düzenleme yapılamadı: {str(e)}"}
