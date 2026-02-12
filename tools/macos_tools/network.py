"""macOS Network Settings - WiFi, Bluetooth Control"""

import asyncio
from typing import Any
from utils.logger import get_logger

logger = get_logger("macos.network")


async def wifi_status() -> dict[str, Any]:
    """Get WiFi connection status and network info"""
    try:
        # Get WiFi power status
        proc = await asyncio.create_subprocess_exec(
            "networksetup", "-getairportpower", "en0",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("WiFi status check timed out")
            return {"success": False, "error": "WiFi durumu kontrol zaman aşımına uğradı (5s)"}

        power_output = stdout.decode().strip()
        is_on = "On" in power_output

        if not is_on:
            return {
                "success": True,
                "wifi_on": False,
                "connected": False,
                "network": None
            }

        # Get current network name
        proc2 = await asyncio.create_subprocess_exec(
            "networksetup", "-getairportnetwork", "en0",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc2.kill()
            logger.error("WiFi network name check timed out")
            return {"success": True, "wifi_on": is_on, "connected": False, "network": "Bilinmiyor"}

        network_output = stdout2.decode().strip()
        network_name = None
        connected = False

        if "Current Wi-Fi Network:" in network_output:
            network_name = network_output.split(": ")[-1]
            connected = True
        elif "not associated" not in network_output.lower():
            network_name = network_output.split(": ")[-1] if ": " in network_output else None
            connected = network_name is not None

        logger.info(f"WiFi status: on={is_on}, connected={connected}, network={network_name}")

        return {
            "success": True,
            "wifi_on": is_on,
            "connected": connected,
            "network": network_name
        }

    except Exception as e:
        logger.error(f"WiFi status error: {e}")
        return {"success": False, "error": str(e)}


async def wifi_toggle(enable: bool = None) -> dict[str, Any]:
    """Toggle WiFi on/off or set specific state"""
    try:
        # If no specific state, toggle current state
        if enable is None:
            status = await wifi_status()
            if not status.get("success"):
                return status
            enable = not status.get("wifi_on", True)

        state = "on" if enable else "off"

        proc = await asyncio.create_subprocess_exec(
            "networksetup", "-setairportpower", "en0", state,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("WiFi toggle timed out")
            return {"success": False, "error": "WiFi değişim zaman aşımına uğradı (5s)"}

        if proc.returncode != 0:
            error = stderr.decode().strip()
            logger.error(f"WiFi toggle failed: {error}")
            return {"success": False, "error": f"WiFi değiştirilemedi: {error}"}

        action = "açıldı" if enable else "kapatıldı"
        logger.info(f"WiFi {action}")

        return {
            "success": True,
            "wifi_on": enable,
            "action": action
        }

    except Exception as e:
        logger.error(f"WiFi toggle error: {e}")
        return {"success": False, "error": str(e)}


async def bluetooth_status() -> dict[str, Any]:
    """Get Bluetooth status"""
    try:
        # Check if blueutil is available
        proc = await asyncio.create_subprocess_exec(
            "which", "blueutil",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("blueutil check timed out")
            return {"success": True, "bluetooth_on": False, "status": "Bilinmiyor"}

        if proc.returncode == 0:
            # Use blueutil if available
            proc2 = await asyncio.create_subprocess_exec(
                "blueutil", "-p",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, _ = await asyncio.wait_for(proc2.communicate(), timeout=5)
            except asyncio.TimeoutError:
                proc2.kill()
                logger.error("blueutil status check timed out")
                return {"success": True, "bluetooth_on": False, "status": "Bilinmiyor"}

            is_on = stdout.decode().strip() == "1"
        else:
            # Fallback to system_profiler
            proc2 = await asyncio.create_subprocess_exec(
                "system_profiler", "SPBluetoothDataType",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, _ = await asyncio.wait_for(proc2.communicate(), timeout=5)
            except asyncio.TimeoutError:
                proc2.kill()
                logger.error("system_profiler Bluetooth check timed out")
                return {"success": True, "bluetooth_on": False, "status": "Bilinmiyor"}

            output = stdout.decode()
            is_on = "State: On" in output or "Bluetooth:" in output

        return {
            "success": True,
            "bluetooth_on": is_on,
            "status": "açık" if is_on else "kapalı"
        }

    except Exception as e:
        logger.error(f"Bluetooth status error: {e}")
        return {"success": False, "error": str(e)}


async def get_wifi_details() -> dict[str, Any]:
    """Get detailed WiFi statistics on macOS using system_profiler (v22.0)"""
    from ..terminal_tools import execute_safe_command
    # system_profiler is better on modern macOS
    cmd = "system_profiler SPAirPortDataType"
    result = await execute_safe_command(cmd)
    
    if not result["success"]:
        return {"success": False, "error": "WiFi detayları alınamadı"}
        
    import re
    output = result["output"]
    stats = {}
    
    # Simple extraction via regex
    patterns = {
        "ssid": r"Current Network Information:\s+(.*?):",
        "phy_mode": r"PHY Mode:\s+(.*)",
        "channel": r"Channel:\s+(.*)",
        "security": r"Security:\s+(.*)",
        "signal": r"Signal / Noise:\s+(.*?) /",
        "noise": r"Signal / Noise:.*?/ (.*)",
        "transmit_rate": r"Transmit Rate:\s+(.*)"
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, output, re.DOTALL)
        if match:
            stats[key] = match.group(1).strip()
            
    if not stats.get("ssid"):
        # Fallback for SSID if it's not the current network header
        ssid_match = re.search(r"Status: Connected.*?Current Network Information:\s+(.*?):", output, re.DOTALL)
        if ssid_match:
            stats["ssid"] = ssid_match.group(1).strip()

    return {
        "success": True,
        "stats": stats,
        "message": f"{stats.get('ssid', 'Bilinmeyen')} ağına bağlı" + (f" (Sinyal: {stats.get('signal')})" if stats.get('signal') else "")
    }


async def get_public_ip() -> dict[str, Any]:
    """Get external public IP address"""
    from ..terminal_tools import execute_safe_command
    result = await execute_safe_command("curl -s https://ifconfig.me")
    if result["success"]:
        ip = result["output"].strip()
        return {"success": True, "ip": ip, "message": f"Dış IP Adresi: {ip}"}
    return {"success": False, "error": "Dış IP adresi alınamadı"}


async def scan_local_network() -> dict[str, Any]:
    """Scan local network for devices using arp"""
    from ..terminal_tools import execute_safe_command
    import re
    result = await execute_safe_command("arp -a")
    if not result["success"]:
        return {"success": False, "error": "Ağ taraması başarısız"}
        
    lines = result["output"].strip().split("\n")
    devices = []
    for line in lines:
        match = re.search(r"\((.*?)\) at (.*?) on", line)
        if match:
            devices.append({
                "ip": match.group(1),
                "mac": match.group(2)
            })
            
    return {
        "success": True,
        "devices": devices,
        "count": len(devices),
        "message": f"Yerel ağda {len(devices)} cihaz bulundu"
    }
