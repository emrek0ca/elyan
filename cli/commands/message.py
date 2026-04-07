import httpx
import asyncio
import sys
from config import get_gateway_api_root_url

def handle_message(args):
    if args.action == "send":
        if not args.text:
            print("Error: Text required.")
            return 1
        asyncio.run(send_message(args.text, channel=getattr(args, "channel", None)))
        return 0
    if args.action == "poll":
        asyncio.run(poll_recent_runs())
        return 0
    if args.action == "broadcast":
        print("Broadcast CLI yuzeyi henuz tek kanalli gateway akisi ile sinirli. once 'message send' kullanin.")
        return 0
    print("Usage: elyan message send --text '...' [--channel telegram]\n       elyan message poll")
    return 1

async def send_message(text: str, channel: str | None = None):
    url = f"{get_gateway_api_root_url().rstrip('/')}/message"
    channel_name = str(channel or "cli").strip() or "cli"
    
    print(f"💬  Sending [{channel_name}]: {text}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"text": text, "channel": channel_name})
            if resp.status_code == 200:
                data = resp.json()
                print(f"🤖  Response: {data.get('status', 'OK')}")
            else:
                print(f"❌  Error: {resp.status_code}")
    except Exception as e:
        print(f"❌  Gateway not reachable: {e}")


async def poll_recent_runs():
    url = f"{get_gateway_api_root_url().rstrip('/')}/runs/recent?limit=5"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                print(f"❌  Poll failed: {resp.status_code}")
                return
            data = resp.json()
    except Exception as e:
        print(f"❌  Gateway not reachable: {e}")
        return

    runs = data.get("runs", []) if isinstance(data, dict) else []
    if not runs:
        print("Yeni run bulunamadi.")
        return
    print("Son calismalar:")
    for row in runs[:5]:
        run_id = str(row.get("run_id") or row.get("id") or "-")
        status = str(row.get("status") or "-")
        text = str(row.get("response_text") or row.get("summary") or "").strip().replace("\n", " ")
        print(f"- {run_id} [{status}] {text[:120]}")
