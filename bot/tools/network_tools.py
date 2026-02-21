import asyncio
import re
from typing import Dict, Any, List
from .terminal_tools import execute_safe_command

async def get_wifi_stats() -> Dict[str, Any]:
    """Get detailed WiFi statistics on macOS"""
    # Use the airport utility (already whitelisted in v22.0)
    cmd = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I"
    result = await execute_safe_command(cmd)
    
    if not result["success"]:
        return {"success": False, "error": "Could not retrieve WiFi stats"}
        
    output = result["output"]
    stats = {}
    
    # Parse airport -I output
    patterns = {
        "ssid": r"SSID: (.*)",
        "bssid": r"BSSID: (.*)",
        "rssi": r"agrCtlRSSI: (.*)",
        "noise": r"agrCtlNoise: (.*)",
        "channel": r"channel: (.*)",
        "phy_mode": r"op mode: (.*)",
        "transmit_rate": r"lastTxRate: (.*)"
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, output)
        if match:
            stats[key] = match.group(1).strip()
            
    return {
        "success": True,
        "stats": stats,
        "message": f"Connected to {stats.get('ssid', 'unknown')} (RSSI: {stats.get('rssi', '0')} dBm)"
    }

async def get_public_ip() -> Dict[str, Any]:
    """Get external public IP address"""
    result = await execute_safe_command("curl -s https://ifconfig.me")
    if result["success"]:
        ip = result["output"].strip()
        return {"success": True, "ip": ip, "message": f"Public IP: {ip}"}
    return {"success": False, "error": "Could not fetch public IP"}

async def scan_local_network() -> Dict[str, Any]:
    """Scan local network for devices using arp"""
    result = await execute_safe_command("arp -a")
    if not result["success"]:
        return {"success": False, "error": "Network scan failed"}
        
    lines = result["output"].strip().split("\n")
    devices = []
    for line in lines:
        # Example: ? (192.168.1.1) at 00:00:00:00:00:00 on en0 ifscope [ethernet]
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
        "message": f"{len(devices)} devices found on local network"
    }
