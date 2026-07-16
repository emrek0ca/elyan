import socket
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
server = subprocess.Popen(
    ["npm", "run", "preview", "--", "--host", "127.0.0.1"],
    cwd=root,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

try:
    for _ in range(80):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 4173)) == 0:
                break
        if server.poll() is not None:
            raise RuntimeError("Vite preview server stopped before becoming ready")
        time.sleep(0.1)
    else:
        raise TimeoutError("Vite preview server did not start on port 4173")

    result = subprocess.run(
        [sys.executable, "tests/site_qa.py"],
        cwd=root,
        check=False,
    )
    raise SystemExit(result.returncode)
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
