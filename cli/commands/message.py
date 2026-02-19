import httpx
import asyncio
import sys
from config.elyan_config import elyan_config

def handle_message(args):
    if args.action == "send":
        if not args.text:
            print("Error: Text required.")
            return
        
        loop = asyncio.get_event_loop()
        loop.run_until_complete(send_message(args.text))

async def send_message(text: str):
    port = elyan_config.get("gateway.port", 18789)
    url = f"http://localhost:{port}/api/message"
    
    print(f"💬  Sending: {text}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"text": text, "channel": "cli"})
            if resp.status_code == 200:
                data = resp.json()
                print(f"🤖  Response: {data.get('status', 'OK')}")
            else:
                print(f"❌  Error: {resp.status_code}")
    except Exception as e:
        print(f"❌  Gateway not reachable: {e}")
