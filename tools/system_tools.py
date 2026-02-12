import platform
import asyncio
import subprocess
from typing import Any
from pathlib import Path

async def _run_osascript(script: str) -> tuple[int, str, str]:
    """Run osascript and return (returncode, stdout, stderr)."""
    process = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return (
        process.returncode,
        stdout.decode("utf-8", errors="ignore").strip(),
        stderr.decode("utf-8", errors="ignore").strip(),
    )

async def get_system_info() -> dict[str, Any]:
    """Retrieve system information using native macOS commands (v21.0 - psutil removal)"""
    try:
        # 1. CPU Usage (via top)
        cpu_cmd = "top -l 1 | grep 'CPU usage' | awk '{print $3}' | tr -d '%'"
        cpu_proc = await asyncio.create_subprocess_shell(cpu_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        cpu_out, _ = await cpu_proc.communicate()
        cpu_percent = float(cpu_out.decode().strip() or 0.0)

        # 2. CPU Cores (via sysctl)
        cores_proc = await asyncio.create_subprocess_shell("sysctl -n hw.physicalcpu", stdout=asyncio.subprocess.PIPE)
        cores_out, _ = await cores_proc.communicate()
        cores = int(cores_out.decode().strip() or 0)

        # 3. Memory (via sysctl and vm_stat)
        mem_total_proc = await asyncio.create_subprocess_shell("sysctl -n hw.memsize", stdout=asyncio.subprocess.PIPE)
        mem_total_out, _ = await mem_total_proc.communicate()
        total_bytes = int(mem_total_out.decode().strip() or 0)
        total_gb = round(total_bytes / (1024**3), 2)

        # Get free memory via vm_stat (approximate)
        vm_proc = await asyncio.create_subprocess_shell("vm_stat | grep 'Pages free' | awk '{print $3}' | tr -d '.'", stdout=asyncio.subprocess.PIPE)
        vm_out, _ = await vm_proc.communicate()
        free_pages = int(vm_out.decode().strip() or 0)
        free_gb = round((free_pages * 4096) / (1024**3), 2)
        used_gb = round(total_gb - free_gb, 2)
        mem_percent = round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0

        # 4. Disk Usage (via df)
        disk_proc = await asyncio.create_subprocess_shell("df -g / | tail -1 | awk '{print $2, $3, $4, $5}'", stdout=asyncio.subprocess.PIPE)
        disk_out, _ = await disk_proc.communicate()
        disk_parts = disk_out.decode().strip().split()
        
        if len(disk_parts) >= 4:
            d_total = float(disk_parts[0])
            d_used = float(disk_parts[1])
            d_free = float(disk_parts[2])
            d_percent = float(disk_parts[3].replace('%', ''))
        else:
            d_total, d_used, d_free, d_percent = 0, 0, 0, 0

        # 5. Battery (via pmset)
        battery_proc = await asyncio.create_subprocess_shell("pmset -g batt | grep -o '[0-9]*%' | tr -d '%'", stdout=asyncio.subprocess.PIPE)
        batt_out, _ = await battery_proc.communicate()
        batt_percent = int(batt_out.decode().strip() or 0)
        
        charging_proc = await asyncio.create_subprocess_shell("pmset -g batt | grep 'AC Power'", stdout=asyncio.subprocess.PIPE)
        charging_out, _ = await charging_proc.communicate()
        is_charging = bool(charging_out.decode().strip())

        info = {
            "success": True,
            "system": {
                "os": platform.system(),
                "os_version": platform.mac_ver()[0] if platform.system() == "Darwin" else platform.version(),
                "machine": platform.machine(),
                "hostname": platform.node()
            },
            "cpu": {
                "percent": cpu_percent,
                "cores": cores
            },
            "memory": {
                "total_gb": total_gb,
                "used_gb": used_gb,
                "available_gb": free_gb,
                "percent": mem_percent
            },
            "disk": {
                "total_gb": d_total,
                "used_gb": d_used,
                "free_gb": d_free,
                "percent": d_percent
            },
            "battery": {
                "percent": batt_percent,
                "charging": is_charging
            }
        }

        return info

    except Exception as e:
        return {"success": False, "error": str(e)}

async def open_app(app_name: str) -> dict[str, Any]:
    try:
        safe_apps = {
            "safari": "Safari",
            "chrome": "Google Chrome",
            "firefox": "Firefox",
            "finder": "Finder",
            "terminal": "Terminal",
            "notes": "Notes",
            "notlar": "Notes",
            "calculator": "Calculator",
            "hesap makinesi": "Calculator",
            "music": "Music",
            "müzik": "Music",
            "photos": "Photos",
            "fotoğraflar": "Photos",
            "mail": "Mail",
            "calendar": "Calendar",
            "takvim": "Calendar",
            "messages": "Messages",
            "mesajlar": "Messages",
            "facetime": "FaceTime",
            "preview": "Preview",
            "textedit": "TextEdit",
            "vscode": "Visual Studio Code",
            "code": "Visual Studio Code",
            "spotify": "Spotify",
            "slack": "Slack",
            "discord": "Discord",
            "zoom": "zoom.us",
            "whatsapp": "WhatsApp",
            "telegram": "Telegram",
            "notion": "Notion",
            "obsidian": "Obsidian",
        }

        app_lower = app_name.lower().strip()
        actual_app = safe_apps.get(app_lower, app_name)

        process = await asyncio.create_subprocess_exec(
            "open", "-a", actual_app,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            return {"success": False, "error": f"Uygulama açılamadı: {actual_app}"}

        return {"success": True, "app": actual_app, "message": f"{actual_app} açıldı"}

    except Exception as e:
        return {"success": False, "error": str(e)}

async def open_url(url: str) -> dict[str, Any]:
    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        blocked_patterns = ["file://", "javascript:", "data:"]
        for pattern in blocked_patterns:
            if pattern in url.lower():
                return {"success": False, "error": "Bu URL türü engellenmiş"}

        process = await asyncio.create_subprocess_exec(
            "open", url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

        if process.returncode != 0:
            return {"success": False, "error": "URL açılamadı"}

        return {"success": True, "url": url, "message": f"URL açıldı: {url}"}

    except Exception as e:
        return {"success": False, "error": str(e)}

async def get_running_apps() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get name of every process whose background only is false'],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            apps = [app.strip() for app in result.stdout.strip().split(",")]
            return {"success": True, "apps": apps, "count": len(apps)}

        return {"success": False, "error": "Uygulama listesi alınamadı"}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def take_screenshot(filename: str = None) -> dict[str, Any]:
    """Ekran görüntüsü alır ve masaüstüne kaydeder"""
    try:
        from datetime import datetime
        desktop = Path.home() / "Desktop"

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"

        if not filename.endswith(".png"):
            filename += ".png"

        filepath = desktop / filename

        process = await asyncio.create_subprocess_exec(
            "screencapture", "-x", str(filepath),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

        if process.returncode == 0 and filepath.exists():
            return {
                "success": True,
                "path": str(filepath),
                "filename": filename,
                "message": f"Screenshot kaydedildi: {filename}"
            }

        return {"success": False, "error": "Screenshot alınamadı"}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def read_clipboard() -> dict[str, Any]:
    """Panodaki metni okur"""
    try:
        process = await asyncio.create_subprocess_exec(
            "pbpaste",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()

        content = stdout.decode("utf-8", errors="replace")
        return {
            "success": True,
            "content": content,
            "length": len(content),
            "message": "Pano içeriği okundu"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


async def write_clipboard(text: str) -> dict[str, Any]:
    """Panoya metin yazar"""
    try:
        process = await asyncio.create_subprocess_exec(
            "pbcopy",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate(input=text.encode("utf-8"))

        if process.returncode == 0:
            return {
                "success": True,
                "length": len(text),
                "message": "Metin panoya kopyalandı"
            }

        return {"success": False, "error": "Panoya yazılamadı"}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def close_app(app_name: str) -> dict[str, Any]:
    """Uygulamayı kapatır"""
    try:
        safe_apps = {
            "safari": "Safari",
            "chrome": "Google Chrome",
            "firefox": "Firefox",
            "finder": "Finder",
            "notes": "Notes",
            "notlar": "Notes",
            "music": "Music",
            "müzik": "Music",
            "photos": "Photos",
            "mail": "Mail",
            "calendar": "Calendar",
            "takvim": "Calendar",
            "messages": "Messages",
            "preview": "Preview",
            "textedit": "TextEdit",
            "vscode": "Visual Studio Code",
            "code": "Visual Studio Code",
            "spotify": "Spotify",
            "slack": "Slack",
            "discord": "Discord",
            "telegram": "Telegram",
        }

        app_lower = app_name.lower().strip()
        actual_app = safe_apps.get(app_lower, app_name)

        script = f'tell application "{actual_app}" to quit'
        code, _, err = await _run_osascript(script)
        if code != 0:
            return {"success": False, "error": f"Uygulama kapatılamadı: {actual_app}. {err}".strip()}

        return {
            "success": True,
            "app": actual_app,
            "message": f"{actual_app} kapatıldı"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


async def shutdown_system() -> dict[str, Any]:
    """macOS sistemi kapatır."""
    try:
        code, _, err = await _run_osascript('tell application "System Events" to shut down')
        if code != 0:
            return {"success": False, "error": f"Sistem kapatma başarısız: {err or 'yetki/izin hatası'}"}
        return {"success": True, "message": "Sistem kapatma komutu gönderildi"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def restart_system() -> dict[str, Any]:
    """macOS sistemi yeniden başlatır."""
    try:
        code, _, err = await _run_osascript('tell application "System Events" to restart')
        if code != 0:
            return {"success": False, "error": f"Sistem yeniden başlatma başarısız: {err or 'yetki/izin hatası'}"}
        return {"success": True, "message": "Sistem yeniden başlatma komutu gönderildi"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def sleep_system() -> dict[str, Any]:
    """macOS sistemi uyku moduna alır."""
    try:
        code, _, err = await _run_osascript('tell application "System Events" to sleep')
        if code != 0:
            return {"success": False, "error": f"Uyku modu başarısız: {err or 'yetki/izin hatası'}"}
        return {"success": True, "message": "Sistem uyku moduna alınıyor"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def lock_screen() -> dict[str, Any]:
    """Ekranı kilitle."""
    try:
        process = await asyncio.create_subprocess_exec(
            "/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession",
            "-suspend",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore").strip()
            return {"success": False, "error": f"Ekran kilitleme başarısız: {err or 'bilinmeyen hata'}"}
        return {"success": True, "message": "Ekran kilitlendi"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def set_volume(level: int = None, mute: bool = None) -> dict[str, Any]:
    """Ses seviyesini ayarlar veya sessize alır"""
    try:
        if mute is not None:
            mute_script = "set volume with output muted" if mute else "set volume without output muted"
            process = await asyncio.create_subprocess_exec(
                "osascript", "-e", mute_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()

            return {
                "success": True,
                "muted": mute,
                "message": "Ses kapatıldı" if mute else "Ses açıldı"
            }

        if level is not None:
            level = max(0, min(100, level))
            vol_value = int(level / 100 * 7)

            script = f"set volume output volume {level}"
            process = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()

            return {
                "success": True,
                "level": level,
                "message": f"Ses seviyesi %{level} yapıldı"
            }

        # Mevcut ses seviyesini al
        process = await asyncio.create_subprocess_exec(
            "osascript", "-e", "output volume of (get volume settings)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        current = stdout.decode().strip()

        return {
            "success": True,
            "level": int(current) if current.isdigit() else 0,
            "message": f"Mevcut ses seviyesi: %{current}"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


async def send_notification(title: str, message: str = "", sound: bool = True) -> dict[str, Any]:
    """Masaüstü bildirimi gönderir"""
    try:
        sound_part = 'sound name "default"' if sound else ""
        script = f'display notification "{message}" with title "{title}" {sound_part}'

        process = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

        return {
            "success": True,
            "title": title,
            "message": message,
            "notification_sent": True
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


async def kill_process(process_name: str) -> dict[str, Any]:
    """Process'i PID veya adıyla sonlandırır (Whitelist tabanlı güvenlik)"""
    try:
        # Playbook Section 5.2: Process whitelist
        PROCESS_WHITELIST = {
            # Browsers
            "chrome", "google chrome", "safari", "firefox", "brave", "edge",
            # Development
            "python", "python3", "node", "npm", "code", "vscode", "visual studio code",
            # Communication
            "slack", "discord", "telegram", "zoom", "teams", "whatsapp",
            # Media
            "spotify", "music", "vlc", "quicktime",
            # Productivity
            "notion", "obsidian", "notes", "preview",
            # Terminal (sadece user-initiated)
            "terminal", "iterm",
        }

        # System process blacklist (NEVER terminate)
        SYSTEM_BLACKLIST = {
            "kernel", "launchd", "windowserver", "loginwindow", "systemuiserver",
            "finder", "dock", "coreaudiod", "bluetoothd", "airportd", "cfprefsd",
            "notifyd", "securityd", "diskarbitrationd", "coreservicesd", "mds",
            "mdworker", "spotlight", "usbd", "powerd", "syslogd"
        }

        process_lower = process_name.lower().strip()

        # System process kontrolü
        if process_lower in SYSTEM_BLACKLIST or any(sys_proc in process_lower for sys_proc in SYSTEM_BLACKLIST):
            return {"success": False, "error": "Sistem process'i sonlandırılamaz (güvenlik)"}

        # Whitelist kontrolü
        if not any(allowed in process_lower for allowed in PROCESS_WHITELIST):
            return {"success": False, "error": f"Bu process whitelist'te değil: {process_name}"}

        process = await asyncio.create_subprocess_exec(
            "pkill", "-f", process_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            return {
                "success": True,
                "process": process_name,
                "message": f"Process sonlandırıldı: {process_name}"
            }
        else:
            return {"success": False, "error": f"Process bulunamadı: {process_name}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_process_info(process_name: str = None) -> dict[str, Any]:
    """Çalışan process'ler hakkında bilgi döner"""
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode != 0:
            return {"success": False, "error": "Process listesi alınamadı"}

        processes = []
        lines = result.stdout.strip().split('\n')[1:]  # Header'ı atla

        for line in lines[:50]:  # İlk 50 process
            parts = line.split()
            if len(parts) >= 11:
                pid = parts[1]
                cpu = parts[2]
                mem = parts[3]
                comm = ' '.join(parts[10:])

                # Filtreleme
                if process_name and process_name.lower() not in comm.lower():
                    continue

                processes.append({
                    "pid": pid,
                    "cpu": f"{cpu}%",
                    "memory": f"{mem}%",
                    "name": comm[:60]
                })

        return {
            "success": True,
            "processes": processes[:20],
            "count": len(processes),
            "message": f"{len(processes)} process bulundu"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


async def run_safe_command(command: str, timeout: int = 30) -> dict[str, Any]:
    """Güvenli terminal komutlarını çalıştırır (whitelist tabanlı)"""
    try:
        # Güvenli komut whitelist'i
        safe_commands = {
            # Sistem bilgisi
            "date": ["date"],
            "uptime": ["uptime"],
            "whoami": ["whoami"],
            "pwd": ["pwd"],
            "ls": ["ls", "-la", "-l", "-h"],
            "df": ["df", "-h"],
            "du": ["du", "-h", "-sh"],
            
            # Ağ
            "ping": ["ping", "-c", "4"],
            "ifconfig": ["ifconfig"],
            "netstat": ["netstat", "-tuln"],
            
            # Process
            "ps": ["ps", "aux"],
            "top": ["top", "-l", "1"],
            
            # Dosya işlemleri (temel)
            "head": ["head", "-n", "10"],
            "tail": ["tail", "-n", "10"],
            "wc": ["wc", "-l"],
            "file": ["file"],
            
            # Geliştirme araçları
            "python": ["python", "--version"],
            "node": ["node", "--version"],
            "npm": ["npm", "--version"],
            "git": ["git", "--version", "status", "log", "--oneline", "-5"],
        }

        # Komutu parçalara ayır
        parts = command.strip().split()
        if not parts:
            return {"success": False, "error": "Boş komut"}

        base_cmd = parts[0]
        
        # Güvenli komut kontrolü
        if base_cmd not in safe_commands:
            return {"success": False, "error": f"Güvenli olmayan komut: {base_cmd}"}

        # Parametre kontrolü
        allowed_args = safe_commands[base_cmd]
        for arg in parts[1:]:
            if arg not in allowed_args:
                return {"success": False, "error": f"Güvenli olmayan parametre: {arg}"}

        # Komutu çalıştır
        process = await asyncio.create_subprocess_exec(
            *parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=None  # Current directory
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            return {"success": False, "error": f"Komut zaman aşımına uğradı ({timeout}s)"}

        output = stdout.decode('utf-8', errors='ignore').strip()
        error = stderr.decode('utf-8', errors='ignore').strip()

        result = {
            "success": process.returncode == 0,
            "command": command,
            "return_code": process.returncode,
            "output": output,
            "error": error
        }

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_installed_apps() -> dict[str, Any]:
    """List applications installed in /Applications folder"""
    from .terminal_tools import execute_safe_command
    result = await execute_safe_command("ls /Applications")
    
    if result["success"]:
        apps = [app.replace(".app", "") for app in result["output"].strip().split("\n") if app.endswith(".app")]
        return {
            "success": True,
            "apps": apps,
            "count": len(apps),
            "message": f"{len(apps)} uygulama bulundu."
        }
    return {"success": False, "error": "Uygulama listesi alınamadı"}


async def get_display_info() -> dict[str, Any]:
    """Get connected displays information"""
    from .terminal_tools import execute_safe_command
    # system_profiler is whitelisted
    result = await execute_safe_command("system_profiler SPDisplaysDataType")
    
    if result["success"]:
        # Basic parsing of displays
        import re
        output = result["output"]
        displays = re.findall(r"Display Type: (.*?)\n.*?Resolution: (.*?)\n", output, re.DOTALL)
        
        info = []
        for d in displays:
            info.append({
                "type": d[0].strip(),
                "resolution": d[1].strip()
            })
            
        return {
            "success": True,
            "displays": info,
            "message": f"{len(info)} ekran tespit edildi."
        }
    return {"success": False, "error": "Ekran bilgisi alınamadı"}
