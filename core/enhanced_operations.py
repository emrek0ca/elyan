"""
Enhanced Operations - Advanced file, research, and document operations
Gelişmiş dosya, araştırma ve belge işlemleri için merkezi sistem
"""

import os
import sys
import shutil
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
import json
import re

from utils.logger import get_logger

logger = get_logger("enhanced_operations")


# ============================================================================
# ENHANCED FILE OPERATIONS
# ============================================================================

class FileOperationType(Enum):
    """Types of file operations"""
    COPY = "copy"
    MOVE = "move"
    RENAME = "rename"
    DELETE = "delete"
    CREATE = "create"
    READ = "read"
    WRITE = "write"
    COMPRESS = "compress"
    EXTRACT = "extract"
    SEARCH = "search"
    ORGANIZE = "organize"
    BACKUP = "backup"


@dataclass
class FileOperationResult:
    """Result of a file operation"""
    success: bool
    operation: FileOperationType
    source: str
    destination: Optional[str] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class EnhancedFileOperations:
    """Advanced file operations with safety checks and batch support"""

    SAFE_EXTENSIONS = {'.txt', '.md', '.json', '.xml', '.csv', '.html', '.css', '.js',
                       '.py', '.java', '.cpp', '.h', '.swift', '.rb', '.go', '.rs',
                       '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                       '.jpg', '.jpeg', '.png', '.gif', '.svg', '.bmp', '.webp',
                       '.mp3', '.wav', '.mp4', '.mov', '.avi', '.mkv',
                       '.zip', '.tar', '.gz', '.7z', '.rar'}

    PROTECTED_DIRS = {'/System', '/Library', '/bin', '/sbin', '/usr', '/etc', '/var'}

    def __init__(self):
        self.operation_history: List[FileOperationResult] = []

    def is_safe_path(self, path: str) -> bool:
        """Check if path is safe to operate on"""
        path_obj = Path(path).resolve()

        # Check against protected directories
        for protected in self.PROTECTED_DIRS:
            if str(path_obj).startswith(protected):
                return False

        return True

    def is_safe_extension(self, path: str) -> bool:
        """Check if file extension is safe"""
        return Path(path).suffix.lower() in self.SAFE_EXTENSIONS

    async def copy_file(self, source: str, destination: str, overwrite: bool = False) -> FileOperationResult:
        """Copy a file with safety checks"""
        try:
            source_path = Path(source).expanduser().resolve()
            dest_path = Path(destination).expanduser().resolve()

            if not source_path.exists():
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.COPY,
                    source=source,
                    destination=destination,
                    error=f"Kaynak dosya bulunamadı: {source}"
                )

            if not self.is_safe_path(str(dest_path)):
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.COPY,
                    source=source,
                    destination=destination,
                    error="Hedef konum güvenli değil"
                )

            if dest_path.exists() and not overwrite:
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.COPY,
                    source=source,
                    destination=destination,
                    error="Hedef dosya zaten var. Üzerine yazmak için overwrite=True kullanın"
                )

            # Create parent directories if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Perform copy
            if source_path.is_dir():
                shutil.copytree(source_path, dest_path, dirs_exist_ok=overwrite)
            else:
                shutil.copy2(source_path, dest_path)

            result = FileOperationResult(
                success=True,
                operation=FileOperationType.COPY,
                source=source,
                destination=destination,
                message=f"Dosya kopyalandı: {source} -> {destination}",
                details={"size": dest_path.stat().st_size if dest_path.exists() else 0}
            )
            self.operation_history.append(result)
            return result

        except Exception as e:
            return FileOperationResult(
                success=False,
                operation=FileOperationType.COPY,
                source=source,
                destination=destination,
                error=str(e)
            )

    async def move_file(self, source: str, destination: str) -> FileOperationResult:
        """Move a file with safety checks"""
        try:
            source_path = Path(source).expanduser().resolve()
            dest_path = Path(destination).expanduser().resolve()

            if not source_path.exists():
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.MOVE,
                    source=source,
                    destination=destination,
                    error=f"Kaynak dosya bulunamadı: {source}"
                )

            if not self.is_safe_path(str(source_path)) or not self.is_safe_path(str(dest_path)):
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.MOVE,
                    source=source,
                    destination=destination,
                    error="İşlem güvenli değil"
                )

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(dest_path))

            result = FileOperationResult(
                success=True,
                operation=FileOperationType.MOVE,
                source=source,
                destination=destination,
                message=f"Dosya taşındı: {source} -> {destination}"
            )
            self.operation_history.append(result)
            return result

        except Exception as e:
            return FileOperationResult(
                success=False,
                operation=FileOperationType.MOVE,
                source=source,
                destination=destination,
                error=str(e)
            )

    async def rename_file(self, source: str, new_name: str) -> FileOperationResult:
        """Rename a file"""
        source_path = Path(source).expanduser().resolve()
        dest_path = source_path.parent / new_name

        return await self.move_file(str(source_path), str(dest_path))

    async def delete_file(self, path: str, to_trash: bool = True) -> FileOperationResult:
        """Delete a file (move to trash by default)"""
        try:
            file_path = Path(path).expanduser().resolve()

            if not file_path.exists():
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.DELETE,
                    source=path,
                    error=f"Dosya bulunamadı: {path}"
                )

            if not self.is_safe_path(str(file_path)):
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.DELETE,
                    source=path,
                    error="Bu dosya silinemez (korumalı alan)"
                )

            if to_trash:
                # Move to trash on macOS
                if sys.platform == "darwin":
                    subprocess.run(["osascript", "-e",
                                    f'tell app "Finder" to delete POSIX file "{file_path}"'],
                                   capture_output=True)
                else:
                    # Fallback: move to ~/.Trash
                    trash_dir = Path.home() / ".Trash"
                    trash_dir.mkdir(exist_ok=True)
                    shutil.move(str(file_path), str(trash_dir / file_path.name))
            else:
                if file_path.is_dir():
                    shutil.rmtree(file_path)
                else:
                    file_path.unlink()

            result = FileOperationResult(
                success=True,
                operation=FileOperationType.DELETE,
                source=path,
                message=f"Dosya {'çöp kutusuna taşındı' if to_trash else 'silindi'}: {path}"
            )
            self.operation_history.append(result)
            return result

        except Exception as e:
            return FileOperationResult(
                success=False,
                operation=FileOperationType.DELETE,
                source=path,
                error=str(e)
            )

    async def create_folder(self, path: str) -> FileOperationResult:
        """Create a new folder"""
        try:
            folder_path = Path(path).expanduser().resolve()

            if folder_path.exists():
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.CREATE,
                    source=path,
                    error="Klasör zaten var"
                )

            folder_path.mkdir(parents=True, exist_ok=True)

            result = FileOperationResult(
                success=True,
                operation=FileOperationType.CREATE,
                source=path,
                message=f"Klasör oluşturuldu: {path}"
            )
            self.operation_history.append(result)
            return result

        except Exception as e:
            return FileOperationResult(
                success=False,
                operation=FileOperationType.CREATE,
                source=path,
                error=str(e)
            )

    async def search_files(self, directory: str, pattern: str, recursive: bool = True,
                          file_type: Optional[str] = None) -> FileOperationResult:
        """Search for files matching pattern"""
        try:
            dir_path = Path(directory).expanduser().resolve()

            if not dir_path.exists():
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.SEARCH,
                    source=directory,
                    error=f"Dizin bulunamadı: {directory}"
                )

            results = []
            search_pattern = f"**/{pattern}" if recursive else pattern

            for match in dir_path.glob(search_pattern):
                if file_type and match.suffix.lower() != f".{file_type.lower()}":
                    continue

                results.append({
                    "path": str(match),
                    "name": match.name,
                    "size": match.stat().st_size if match.is_file() else 0,
                    "modified": datetime.fromtimestamp(match.stat().st_mtime).isoformat(),
                    "is_dir": match.is_dir()
                })

            return FileOperationResult(
                success=True,
                operation=FileOperationType.SEARCH,
                source=directory,
                message=f"{len(results)} dosya bulundu",
                details={"results": results, "count": len(results)}
            )

        except Exception as e:
            return FileOperationResult(
                success=False,
                operation=FileOperationType.SEARCH,
                source=directory,
                error=str(e)
            )

    async def organize_files(self, directory: str, organize_by: str = "type") -> FileOperationResult:
        """Organize files in a directory by type or date"""
        try:
            dir_path = Path(directory).expanduser().resolve()

            if not dir_path.exists():
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.ORGANIZE,
                    source=directory,
                    error=f"Dizin bulunamadı: {directory}"
                )

            organized = {"moved": 0, "skipped": 0, "errors": 0}

            type_folders = {
                ".jpg": "Resimler", ".jpeg": "Resimler", ".png": "Resimler",
                ".gif": "Resimler", ".svg": "Resimler", ".bmp": "Resimler",
                ".mp3": "Müzik", ".wav": "Müzik", ".flac": "Müzik",
                ".mp4": "Videolar", ".mov": "Videolar", ".avi": "Videolar", ".mkv": "Videolar",
                ".pdf": "Belgeler", ".doc": "Belgeler", ".docx": "Belgeler",
                ".xls": "Tablolar", ".xlsx": "Tablolar", ".csv": "Tablolar",
                ".zip": "Arşivler", ".rar": "Arşivler", ".7z": "Arşivler", ".tar": "Arşivler",
                ".py": "Kod", ".js": "Kod", ".html": "Kod", ".css": "Kod", ".java": "Kod",
            }

            for item in dir_path.iterdir():
                if item.is_file():
                    if organize_by == "type":
                        ext = item.suffix.lower()
                        folder_name = type_folders.get(ext, "Diğer")
                    else:  # organize by date
                        mod_time = datetime.fromtimestamp(item.stat().st_mtime)
                        folder_name = mod_time.strftime("%Y-%m")

                    target_folder = dir_path / folder_name
                    target_folder.mkdir(exist_ok=True)

                    try:
                        shutil.move(str(item), str(target_folder / item.name))
                        organized["moved"] += 1
                    except Exception:
                        organized["errors"] += 1

            return FileOperationResult(
                success=True,
                operation=FileOperationType.ORGANIZE,
                source=directory,
                message=f"Dosyalar düzenlendi: {organized['moved']} taşındı, {organized['errors']} hata",
                details=organized
            )

        except Exception as e:
            return FileOperationResult(
                success=False,
                operation=FileOperationType.ORGANIZE,
                source=directory,
                error=str(e)
            )

    async def compress_files(self, source: Union[str, List[str]], destination: str,
                           format: str = "zip") -> FileOperationResult:
        """Compress files or folders"""
        try:
            dest_path = Path(destination).expanduser().resolve()

            sources = [source] if isinstance(source, str) else source
            source_paths = [Path(s).expanduser().resolve() for s in sources]

            # Verify all sources exist
            for sp in source_paths:
                if not sp.exists():
                    return FileOperationResult(
                        success=False,
                        operation=FileOperationType.COMPRESS,
                        source=str(source),
                        error=f"Kaynak bulunamadı: {sp}"
                    )

            if format == "zip":
                import zipfile
                with zipfile.ZipFile(dest_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for sp in source_paths:
                        if sp.is_file():
                            zf.write(sp, sp.name)
                        else:
                            for file in sp.rglob('*'):
                                zf.write(file, file.relative_to(sp.parent))

            elif format == "tar.gz":
                import tarfile
                with tarfile.open(dest_path, "w:gz") as tar:
                    for sp in source_paths:
                        tar.add(sp, arcname=sp.name)

            return FileOperationResult(
                success=True,
                operation=FileOperationType.COMPRESS,
                source=str(source),
                destination=destination,
                message=f"Dosyalar sıkıştırıldı: {destination}",
                details={"format": format, "size": dest_path.stat().st_size}
            )

        except Exception as e:
            return FileOperationResult(
                success=False,
                operation=FileOperationType.COMPRESS,
                source=str(source),
                error=str(e)
            )

    async def extract_archive(self, source: str, destination: Optional[str] = None) -> FileOperationResult:
        """Extract an archive"""
        try:
            source_path = Path(source).expanduser().resolve()
            dest_path = Path(destination).expanduser().resolve() if destination else source_path.parent

            if not source_path.exists():
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.EXTRACT,
                    source=source,
                    error=f"Arşiv bulunamadı: {source}"
                )

            dest_path.mkdir(parents=True, exist_ok=True)

            if source_path.suffix == '.zip':
                import zipfile
                with zipfile.ZipFile(source_path, 'r') as zf:
                    # Zip-Slip Patch
                    for member in zf.namelist():
                        member_path = (dest_path / member).resolve()
                        if not str(member_path).startswith(str(dest_path)):
                            raise Exception("BANNED: Zip-Slip Path Traversal detected.")
                    zf.extractall(dest_path)

            elif source_path.suffix in ['.tar', '.gz', '.tgz']:
                import tarfile
                with tarfile.open(source_path, 'r:*') as tar:
                    # Tar Zip-Slip Patch
                    def is_within_directory(directory, target):
                        abs_directory = os.path.abspath(directory)
                        abs_target = os.path.abspath(target)
                        prefix = os.path.commonprefix([abs_directory, abs_target])
                        return prefix == abs_directory

                    def safe_tar_extract(tar, path=".", members=None, *, numeric_owner=False):
                        for member in tar.getmembers():
                            member_path = os.path.join(path, member.name)
                            if not is_within_directory(path, member_path):
                                raise Exception("BANNED: Zip-Slip Path Traversal in Tar detected.")
                        tar.extractall(path, members, numeric_owner=numeric_owner)

                    safe_tar_extract(tar, str(dest_path))

            return FileOperationResult(
                success=True,
                operation=FileOperationType.EXTRACT,
                source=source,
                destination=str(dest_path),
                message=f"Arşiv çıkarıldı: {dest_path}"
            )

        except Exception as e:
            return FileOperationResult(
                success=False,
                operation=FileOperationType.EXTRACT,
                source=source,
                error=str(e)
            )

    async def backup_files(self, source: str, backup_dir: Optional[str] = None) -> FileOperationResult:
        """Create a backup of files"""
        try:
            source_path = Path(source).expanduser().resolve()

            if not source_path.exists():
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.BACKUP,
                    source=source,
                    error=f"Kaynak bulunamadı: {source}"
                )

            if backup_dir:
                backup_path = Path(backup_dir).expanduser().resolve()
            else:
                backup_path = Path.home() / "Backups" / "Elyan"

            backup_path.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{source_path.name}_backup_{timestamp}"

            if source_path.suffix:
                backup_file = backup_path / f"{backup_name}.zip"
            else:
                backup_file = backup_path / f"{backup_name}.zip"

            # Create zip backup
            result = await self.compress_files(source, str(backup_file))

            if result.success:
                return FileOperationResult(
                    success=True,
                    operation=FileOperationType.BACKUP,
                    source=source,
                    destination=str(backup_file),
                    message=f"Yedek oluşturuldu: {backup_file}"
                )
            else:
                return FileOperationResult(
                    success=False,
                    operation=FileOperationType.BACKUP,
                    source=source,
                    error=result.error
                )

        except Exception as e:
            return FileOperationResult(
                success=False,
                operation=FileOperationType.BACKUP,
                source=source,
                error=str(e)
            )


# ============================================================================
# ENHANCED APP OPERATIONS
# ============================================================================

class EnhancedAppOperations:
    """Advanced application management for macOS"""

    def __init__(self):
        self.app_cache: Dict[str, str] = {}

    async def list_running_apps(self) -> List[Dict[str, Any]]:
        """List all running applications"""
        apps = []
        try:
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of every process whose background only is false'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                app_names = result.stdout.strip().split(", ")
                for name in app_names:
                    apps.append({"name": name, "running": True})
        except Exception as e:
            logger.error(f"Error listing apps: {e}")

        return apps

    async def open_app(self, app_name: str) -> Dict[str, Any]:
        """Open an application"""
        try:
            result = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True, text=True
            )

            if result.returncode == 0:
                return {"success": True, "message": f"{app_name} açıldı"}
            else:
                return {"success": False, "error": f"{app_name} açılamadı: {result.stderr}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close_app(self, app_name: str, force: bool = False) -> Dict[str, Any]:
        """Close an application"""
        try:
            if force:
                subprocess.run(["pkill", "-f", app_name], capture_output=True)
            else:
                subprocess.run([
                    "osascript", "-e",
                    f'tell application "{app_name}" to quit'
                ], capture_output=True)

            return {"success": True, "message": f"{app_name} kapatıldı"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_app_info(self, app_name: str) -> Dict[str, Any]:
        """Get information about an application"""
        try:
            # Find app bundle
            result = subprocess.run(
                ["mdfind", f"kMDItemKind=='Application' && kMDItemDisplayName=='{app_name}'"],
                capture_output=True, text=True
            )

            if result.returncode == 0 and result.stdout.strip():
                app_path = result.stdout.strip().split('\n')[0]
                info_plist = Path(app_path) / "Contents" / "Info.plist"

                if info_plist.exists():
                    # Read plist
                    plist_result = subprocess.run(
                        ["plutil", "-convert", "json", "-o", "-", str(info_plist)],
                        capture_output=True, text=True
                    )

                    if plist_result.returncode == 0:
                        info = json.loads(plist_result.stdout)
                        return {
                            "name": app_name,
                            "path": app_path,
                            "version": info.get("CFBundleShortVersionString", "Unknown"),
                            "bundle_id": info.get("CFBundleIdentifier", "Unknown"),
                            "copyright": info.get("NSHumanReadableCopyright", "")
                        }

            return {"name": app_name, "error": "Uygulama bulunamadı"}

        except Exception as e:
            return {"name": app_name, "error": str(e)}

    async def search_apps(self, query: str) -> List[Dict[str, Any]]:
        """Search for installed applications"""
        apps = []
        try:
            result = subprocess.run(
                ["mdfind", f"kMDItemKind=='Application' && kMDItemDisplayName=='*{query}*'"],
                capture_output=True, text=True
            )

            if result.returncode == 0:
                for app_path in result.stdout.strip().split('\n'):
                    if app_path:
                        app_name = Path(app_path).stem
                        apps.append({
                            "name": app_name,
                            "path": app_path
                        })

        except Exception as e:
            logger.error(f"App search error: {e}")

        return apps


# ============================================================================
# ENHANCED RESEARCH OPERATIONS
# ============================================================================

@dataclass
class ResearchSource:
    """A research source"""
    url: str
    title: str
    content: str
    reliability_score: float
    timestamp: str


@dataclass
class ResearchFinding:
    """A research finding"""
    topic: str
    summary: str
    sources: List[ResearchSource]
    confidence: float


class EnhancedResearchOperations:
    """Advanced research and information gathering"""

    def __init__(self):
        self.search_engines = ["google", "bing", "duckduckgo"]
        self.findings_cache: Dict[str, ResearchFinding] = {}

    async def quick_search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Perform a quick web search"""
        try:
            # Use web_tools if available
            from tools.web_tools import web_search

            results = await web_search(query)
            return {
                "success": True,
                "query": query,
                "results": results[:max_results] if results else [],
                "count": len(results) if results else 0
            }

        except Exception as e:
            logger.error(f"Quick search error: {e}")
            return {"success": False, "error": str(e)}

    async def deep_research(self, topic: str, depth: str = "medium") -> Dict[str, Any]:
        """Perform deep research on a topic"""
        try:
            # Use research_tools if available
            from tools.research_tools import deep_research

            result = await deep_research(topic, depth)
            return {
                "success": True,
                "topic": topic,
                "depth": depth,
                "findings": result
            }

        except Exception as e:
            logger.error(f"Deep research error: {e}")
            return {"success": False, "error": str(e)}

    async def generate_report(self, research_data: Dict[str, Any],
                             format: str = "markdown") -> Dict[str, Any]:
        """Generate a report from research data"""
        try:
            report_content = self._format_research_report(research_data, format)

            return {
                "success": True,
                "format": format,
                "content": report_content,
                "word_count": len(report_content.split())
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _format_research_report(self, data: Dict[str, Any], format: str) -> str:
        """Format research data into a report"""
        if format == "markdown":
            return self._format_markdown_report(data)
        elif format == "html":
            return self._format_html_report(data)
        else:
            return self._format_text_report(data)

    def _format_markdown_report(self, data: Dict[str, Any]) -> str:
        """Format as Markdown"""
        lines = []
        lines.append(f"# Araştırma Raporu: {data.get('topic', 'Bilinmeyen Konu')}")
        lines.append(f"\n*Oluşturulma Tarihi: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

        lines.append("## Özet")
        lines.append(data.get('summary', 'Özet mevcut değil.'))

        if 'findings' in data:
            lines.append("\n## Bulgular")
            for i, finding in enumerate(data['findings'], 1):
                lines.append(f"\n### {i}. {finding.get('title', 'Bulgu')}")
                lines.append(finding.get('content', ''))

        if 'sources' in data:
            lines.append("\n## Kaynaklar")
            for source in data['sources']:
                lines.append(f"- [{source.get('title', 'Kaynak')}]({source.get('url', '#')})")

        return "\n".join(lines)

    def _format_html_report(self, data: Dict[str, Any]) -> str:
        """Format as HTML"""
        html = f"""
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Araştırma Raporu: {data.get('topic', 'Bilinmeyen Konu')}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #1a1a2e; border-bottom: 2px solid #6366f1; }}
        h2 {{ color: #27272a; }}
        .meta {{ color: #71717a; font-style: italic; }}
        .finding {{ background: #f4f4f5; padding: 16px; border-radius: 8px; margin: 16px 0; }}
        .sources {{ list-style: none; padding: 0; }}
        .sources li {{ margin: 8px 0; }}
        a {{ color: #6366f1; }}
    </style>
</head>
<body>
    <h1>Araştırma Raporu: {data.get('topic', 'Bilinmeyen Konu')}</h1>
    <p class="meta">Oluşturulma Tarihi: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

    <h2>Özet</h2>
    <p>{data.get('summary', 'Özet mevcut değil.')}</p>
"""

        if 'findings' in data:
            html += "<h2>Bulgular</h2>"
            for i, finding in enumerate(data['findings'], 1):
                html += f"""
    <div class="finding">
        <h3>{i}. {finding.get('title', 'Bulgu')}</h3>
        <p>{finding.get('content', '')}</p>
    </div>
"""

        if 'sources' in data:
            html += "<h2>Kaynaklar</h2><ul class='sources'>"
            for source in data['sources']:
                html += f"<li><a href=\"{source.get('url', '#')}\">{source.get('title', 'Kaynak')}</a></li>"
            html += "</ul>"

        html += "</body></html>"
        return html

    def _format_text_report(self, data: Dict[str, Any]) -> str:
        """Format as plain text"""
        lines = []
        lines.append(f"ARAŞTIRMA RAPORU: {data.get('topic', 'Bilinmeyen Konu').upper()}")
        lines.append("=" * 60)
        lines.append(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")

        lines.append("ÖZET")
        lines.append("-" * 40)
        lines.append(data.get('summary', 'Özet mevcut değil.'))
        lines.append("")

        if 'findings' in data:
            lines.append("BULGULAR")
            lines.append("-" * 40)
            for i, finding in enumerate(data['findings'], 1):
                lines.append(f"{i}. {finding.get('title', 'Bulgu')}")
                lines.append(f"   {finding.get('content', '')}")
                lines.append("")

        return "\n".join(lines)


# ============================================================================
# UNIFIED OPERATIONS MANAGER
# ============================================================================

class EnhancedOperationsManager:
    """Unified manager for all enhanced operations"""

    def __init__(self):
        self.file_ops = EnhancedFileOperations()
        self.app_ops = EnhancedAppOperations()
        self.research_ops = EnhancedResearchOperations()

    # File Operations
    async def copy(self, source: str, dest: str, overwrite: bool = False) -> FileOperationResult:
        return await self.file_ops.copy_file(source, dest, overwrite)

    async def move(self, source: str, dest: str) -> FileOperationResult:
        return await self.file_ops.move_file(source, dest)

    async def rename(self, source: str, new_name: str) -> FileOperationResult:
        return await self.file_ops.rename_file(source, new_name)

    async def delete(self, path: str, to_trash: bool = True) -> FileOperationResult:
        return await self.file_ops.delete_file(path, to_trash)

    async def create_folder(self, path: str) -> FileOperationResult:
        return await self.file_ops.create_folder(path)

    async def search(self, directory: str, pattern: str, **kwargs) -> FileOperationResult:
        return await self.file_ops.search_files(directory, pattern, **kwargs)

    async def organize(self, directory: str, by: str = "type") -> FileOperationResult:
        return await self.file_ops.organize_files(directory, by)

    async def compress(self, source, dest: str, format: str = "zip") -> FileOperationResult:
        return await self.file_ops.compress_files(source, dest, format)

    async def extract(self, source: str, dest: str = None) -> FileOperationResult:
        return await self.file_ops.extract_archive(source, dest)

    async def backup(self, source: str, dest: str = None) -> FileOperationResult:
        return await self.file_ops.backup_files(source, dest)

    # App Operations
    async def open_app(self, name: str) -> Dict[str, Any]:
        return await self.app_ops.open_app(name)

    async def close_app(self, name: str, force: bool = False) -> Dict[str, Any]:
        return await self.app_ops.close_app(name, force)

    async def list_apps(self) -> List[Dict[str, Any]]:
        return await self.app_ops.list_running_apps()

    async def app_info(self, name: str) -> Dict[str, Any]:
        return await self.app_ops.get_app_info(name)

    async def search_apps(self, query: str) -> List[Dict[str, Any]]:
        return await self.app_ops.search_apps(query)

    # Research Operations
    async def quick_search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        return await self.research_ops.quick_search(query, max_results)

    async def research(self, topic: str, depth: str = "medium") -> Dict[str, Any]:
        return await self.research_ops.deep_research(topic, depth)

    async def generate_report(self, data: Dict, format: str = "markdown") -> Dict[str, Any]:
        return await self.research_ops.generate_report(data, format)


# Create global instance
_operations_manager = None


def get_operations_manager() -> EnhancedOperationsManager:
    """Get the global operations manager instance"""
    global _operations_manager
    if _operations_manager is None:
        _operations_manager = EnhancedOperationsManager()
    return _operations_manager
