import asyncio
import json
from tools import AVAILABLE_TOOLS

async def verify_tools():
    print("=== Wiqo v22.0 Tool Verification ===\n")
    
    tools_to_test = [
        ("get_wifi_details", {}),
        ("get_public_ip", {}),
        ("scan_local_network", {}),
        ("get_now_playing", {}),
        ("get_installed_apps", {}),
        ("get_display_info", {}),
        # control_music and set_display_brightness are skipped to avoid side effects during automated check
    ]
    
    for tool_name, params in tools_to_test:
        print(f"Testing {tool_name}...")
        try:
            tool_func = AVAILABLE_TOOLS.get(tool_name)
            if not tool_func:
                print(f"  FAILED: Tool {tool_name} not found in AVAILABLE_TOOLS")
                continue
                
            result = await tool_func(**params)
            if result.get("success"):
                print(f"  SUCCESS: {result.get('message', 'No message')}")
                # print(f"  Data: {json.dumps(result, indent=2)}")
            else:
                print(f"  ERROR: {result.get('error', 'Unknown error')}")
        except Exception as e:
            print(f"  EXCEPTION: {str(e)}")
        print("-" * 30)

if __name__ == "__main__":
    asyncio.run(verify_tools())
