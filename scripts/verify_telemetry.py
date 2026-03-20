import asyncio

from core.dependencies.autoinstall_hook import activate as _activate_autoinstall_hook

_activate_autoinstall_hook()

import aiohttp
import time
import json

async def test_telemetry():
    url = "http://127.0.0.1:18789/api/health/telemetry"
    ws_url = "ws://127.0.0.1:18789/ws/dashboard"
    
    print(f"Testing Telemetry API: {url}")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                data = await resp.json()
                print(f"API Response status: {resp.status}")
                print(f"Telemetry Data Sample: {json.dumps(data, indent=2)[:500]}...")
                if data.get('ok'):
                    print("✅ Telemetry API is working.")
                else:
                    print(f"❌ Telemetry API error: {data.get('error')}")
        except Exception as e:
            print(f"❌ API Connection failed: {e}")

    print(f"\nTesting WebSocket Telemetry: {ws_url}")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.ws_connect(ws_url) as ws:
                print("Connected to WebSocket.")
                # Wait for a telemetry message (broadcast every 5s)
                start_time = time.time()
                while time.time() - start_time < 10:
                    msg = await ws.receive_json(timeout=6)
                    if msg.get('type') == 'telemetry':
                        print("✅ Received Telemetry broadcast via WebSocket.")
                        print(f"Telemetry event data: {json.dumps(msg['data'], indent=2)[:300]}...")
                        return
                    elif msg.get('event') == 'activity':
                        print(f"Received activity: {msg['data']['detail']}")
                print("❌ No telemetry message received within 10 seconds.")
        except Exception as e:
            print(f"❌ WebSocket Connection failed: {e}")

if __name__ == "__main__":
    # Ensure the server is running first.
    # We can't easily start it here if it's already running or complex to start.
    # So we assume it's running (user usually has it running or we can start it).
    asyncio.run(test_telemetry())
