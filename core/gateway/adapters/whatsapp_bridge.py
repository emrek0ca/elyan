"""Local WhatsApp bridge runtime helpers (QR pairing + HTTP control)."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib import error, parse, request

from utils.logger import get_logger

logger = get_logger("whatsapp_bridge")

BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = int(os.environ.get("ELYAN_WHATSAPP_BRIDGE_PORT", "18792"))
BRIDGE_HOME = Path.home() / ".elyan" / "whatsapp_bridge"
BRIDGE_SCRIPT_PATH = BRIDGE_HOME / "bridge.js"
BRIDGE_PACKAGE_JSON_PATH = BRIDGE_HOME / "package.json"
BRIDGE_LOG_PATH = Path.home() / ".elyan" / "logs" / "whatsapp_bridge.log"
BRIDGE_ENV_KEY = "WHATSAPP_BRIDGE_TOKEN"

_BRIDGE_PACKAGE_JSON = {
    "name": "elyan-whatsapp-bridge",
    "version": "1.0.0",
    "private": True,
    "description": "Local WhatsApp bridge for Elyan",
    "license": "UNLICENSED",
    "dependencies": {
        "express": "^4.21.2",
        "qrcode-terminal": "^0.12.0",
        "whatsapp-web.js": "^1.34.1",
    },
}

_BRIDGE_SCRIPT = r"""#!/usr/bin/env node
const fs = require("fs");
const path = require("path");
const express = require("express");
const qrcode = require("qrcode-terminal");
const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const raw = String(argv[i] || "");
    if (!raw.startsWith("--")) continue;
    const key = raw.slice(2);
    const next = argv[i + 1];
    if (!next || String(next).startsWith("--")) {
      out[key] = "true";
      continue;
    }
    out[key] = String(next);
    i += 1;
  }
  return out;
}

function exists(p) {
  try { return fs.existsSync(p); } catch (_) { return false; }
}

function normalizeChatId(raw) {
  const v = String(raw || "").trim();
  if (!v) return "";
  if (v.endsWith("@c.us") || v.endsWith("@g.us")) return v;
  const digits = v.replace(/\D/g, "");
  if (!digits) return "";
  return `${digits}@c.us`;
}

function parseLimit(raw, fallbackValue) {
  const n = Number(raw);
  if (!Number.isFinite(n)) return fallbackValue;
  return Math.max(1, Math.min(500, Math.floor(n)));
}

const args = parseArgs(process.argv.slice(2));
const host = String(args.host || "127.0.0.1");
const port = Number(args.port || 18792);
const token = String(args.token || "");
const printQr = String(args["print-qr"] || "").toLowerCase() === "true";
const sessionDir = path.resolve(
  String(
    args["session-dir"] ||
    path.join(process.env.HOME || ".", ".elyan", "channels", "whatsapp", "default")
  )
);
const clientId = String(args["client-id"] || "default");

fs.mkdirSync(sessionDir, { recursive: true });

const browserCandidates = [
  process.env.ELYAN_CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/snap/bin/chromium",
].filter(Boolean);
const executablePath = browserCandidates.find((p) => exists(p));

const app = express();
app.use(express.json({ limit: "1mb" }));

const state = {
  ready: false,
  authenticated: false,
  hasQr: false,
  qrText: "",
  startedAt: Date.now(),
  lastQrAt: null,
  lastError: "",
  lastErrorAt: null,
  phone: "",
};

let seq = 0;
const messageQueue = [];

function setError(message) {
  state.lastError = String(message || "");
  state.lastErrorAt = Date.now();
}

function auth(req, res, next) {
  if (!token) return next();
  const received = String(req.get("x-elyan-token") || "");
  if (received !== token) {
    return res.status(401).json({ ok: false, error: "unauthorized" });
  }
  return next();
}

app.use(auth);

app.get("/health", (_req, res) => {
  res.json({
    ok: true,
    state: {
      ...state,
      queueLength: messageQueue.length,
    },
  });
});

app.get("/messages", (req, res) => {
  const limit = parseLimit(req.query.limit, 100);
  const items = messageQueue.splice(0, limit);
  res.json({
    ok: true,
    count: items.length,
    items,
  });
});

app.post("/send", async (req, res) => {
  const to = normalizeChatId(req.body?.to || req.body?.chat_id || "");
  const text = String(req.body?.text || "").trim();
  if (!to) return res.status(400).json({ ok: false, error: "invalid chat id" });
  if (!text) return res.status(400).json({ ok: false, error: "text required" });
  if (!state.ready) return res.status(409).json({ ok: false, error: "whatsapp not ready" });

  try {
    const sent = await client.sendMessage(to, text);
    res.json({ ok: true, id: sent?.id?._serialized || "" });
  } catch (err) {
    setError(err?.message || String(err));
    res.status(500).json({ ok: false, error: state.lastError });
  }
});

app.post("/send-media", async (req, res) => {
  const to = normalizeChatId(req.body?.to || req.body?.chat_id || "");
  const mediaPathRaw = String(req.body?.path || "").trim();
  const caption = String(req.body?.caption || "").trim();
  if (!to) return res.status(400).json({ ok: false, error: "invalid chat id" });
  if (!mediaPathRaw) return res.status(400).json({ ok: false, error: "path required" });
  if (!state.ready) return res.status(409).json({ ok: false, error: "whatsapp not ready" });

  const mediaPath = path.resolve(mediaPathRaw);
  if (!exists(mediaPath)) {
    return res.status(400).json({ ok: false, error: "file not found" });
  }

  try {
    const media = MessageMedia.fromFilePath(mediaPath);
    const options = caption ? { caption } : undefined;
    const sent = await client.sendMessage(to, media, options);
    res.json({ ok: true, id: sent?.id?._serialized || "", path: mediaPath });
  } catch (err) {
    setError(err?.message || String(err));
    res.status(500).json({ ok: false, error: state.lastError });
  }
});

app.post("/logout", async (_req, res) => {
  try {
    await client.logout();
    state.ready = false;
    state.authenticated = false;
    res.json({ ok: true });
  } catch (err) {
    setError(err?.message || String(err));
    res.status(500).json({ ok: false, error: state.lastError });
  }
});

async function gracefulShutdown() {
  try { await client.destroy(); } catch (_) {}
  try { server.close(() => process.exit(0)); } catch (_) { process.exit(0); }
}

app.post("/shutdown", async (_req, res) => {
  res.json({ ok: true, shutting_down: true });
  setTimeout(() => { gracefulShutdown(); }, 100);
});

const server = app.listen(port, host, () => {
  console.log(`[BRIDGE] listening on http://${host}:${port}`);
});

const client = new Client({
  authStrategy: new LocalAuth({
    clientId,
    dataPath: sessionDir,
  }),
  puppeteer: {
    headless: true,
    executablePath: executablePath || undefined,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
    ],
  },
});

client.on("qr", (qr) => {
  state.hasQr = true;
  state.lastQrAt = Date.now();
  qrcode.generate(qr, { small: true }, (rendered) => {
    state.qrText = String(rendered || "");
    if (printQr) {
      console.log("");
      console.log("[ELYAN] WhatsApp QR hazır. Telefonda WhatsApp > Bağlı Cihazlar > Cihaz Bağla.");
      console.log(state.qrText);
      console.log("[QR_READY]");
      console.log("");
    }
  });
});

client.on("authenticated", () => {
  state.authenticated = true;
  state.hasQr = false;
  state.qrText = "";
  console.log("[AUTHENTICATED]");
});

client.on("ready", async () => {
  state.ready = true;
  state.authenticated = true;
  state.qrText = "";
  try {
    const wid = client?.info?.wid?._serialized || "";
    state.phone = wid;
  } catch (_) {}
  console.log("[READY]");
});

client.on("auth_failure", (msg) => {
  state.authenticated = false;
  state.ready = false;
  setError(`auth_failure: ${msg || ""}`);
  console.error("[AUTH_FAILURE]", state.lastError);
});

client.on("disconnected", (reason) => {
  state.ready = false;
  setError(`disconnected: ${reason || ""}`);
  console.error("[DISCONNECTED]", reason || "unknown");
});

client.on("message", (msg) => {
  const item = {
    id: String(msg?.id?._serialized || `${Date.now()}-${seq + 1}`),
    seq: ++seq,
    from: String(msg?.from || ""),
    fromMe: Boolean(msg?.fromMe || false),
    body: String(msg?.body || ""),
    type: String(msg?.type || "chat"),
    timestamp: Number(msg?.timestamp || Math.floor(Date.now() / 1000)),
    pushName: String(msg?.notifyName || msg?.from || ""),
    isGroup: String(msg?.from || "").endsWith("@g.us"),
  };
  messageQueue.push(item);
  if (messageQueue.length > 1000) messageQueue.shift();
});

async function boot() {
  try {
    await client.initialize();
  } catch (err) {
    setError(err?.message || String(err));
    console.error("[INIT_ERROR]", state.lastError);
  }
}

process.on("SIGINT", gracefulShutdown);
process.on("SIGTERM", gracefulShutdown);

boot();
"""


class BridgeRuntimeError(RuntimeError):
    """Raised when WhatsApp bridge runtime setup/usage fails."""


def build_bridge_url(host: str = BRIDGE_HOST, port: int = DEFAULT_BRIDGE_PORT) -> str:
    return f"http://{host}:{int(port)}"


def default_session_dir(channel_id: str = "default") -> Path:
    cid = str(channel_id or "default").strip().replace("/", "_")
    return (Path.home() / ".elyan" / "channels" / "whatsapp" / cid).expanduser()


def generate_bridge_token() -> str:
    return secrets.token_urlsafe(32)


def _write_if_changed(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old = ""
    if path.exists():
        try:
            old = path.read_text(encoding="utf-8")
        except Exception:
            old = ""
    if old != content:
        path.write_text(content, encoding="utf-8")


def ensure_bridge_runtime(force_install: bool = False) -> Path:
    """Ensure Node runtime + bridge files/deps are available."""
    if not shutil.which("node"):
        raise BridgeRuntimeError("Node.js bulunamadı. WhatsApp QR için önce Node.js kurun.")
    if not shutil.which("npm"):
        raise BridgeRuntimeError("npm bulunamadı. Node.js kurulumunu kontrol edin.")

    BRIDGE_HOME.mkdir(parents=True, exist_ok=True)
    _write_if_changed(BRIDGE_PACKAGE_JSON_PATH, json.dumps(_BRIDGE_PACKAGE_JSON, indent=2, ensure_ascii=False))
    _write_if_changed(BRIDGE_SCRIPT_PATH, _BRIDGE_SCRIPT)
    BRIDGE_SCRIPT_PATH.chmod(0o755)

    node_modules_ok = (BRIDGE_HOME / "node_modules" / "whatsapp-web.js").exists()
    if force_install or not node_modules_ok:
        env = os.environ.copy()
        env.setdefault("PUPPETEER_SKIP_DOWNLOAD", "1")
        proc = subprocess.run(
            ["npm", "install", "--omit=dev", "--no-audit", "--no-fund"],
            cwd=str(BRIDGE_HOME),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise BridgeRuntimeError(
                "WhatsApp bridge bağımlılık kurulumu başarısız.\n"
                f"stdout:\n{proc.stdout[-600:]}\n"
                f"stderr:\n{proc.stderr[-600:]}"
            )

    return BRIDGE_SCRIPT_PATH


def _auth_headers(token: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if token:
        headers["x-elyan-token"] = token
    return headers


def bridge_request(
    bridge_url: str,
    method: str,
    path: str,
    token: str = "",
    payload: Optional[Dict[str, Any]] = None,
    timeout_s: float = 5.0,
) -> Tuple[int, Dict[str, Any]]:
    url = parse.urljoin(bridge_url.rstrip("/") + "/", path.lstrip("/"))
    data_bytes = None
    headers = _auth_headers(token)
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url=url, method=method.upper(), data=data_bytes, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout_s) as resp:
            code = int(resp.status)
            body = resp.read().decode("utf-8", errors="replace").strip()
    except error.HTTPError as http_err:
        code = int(http_err.code)
        body = http_err.read().decode("utf-8", errors="replace").strip()
    except Exception as exc:
        raise BridgeRuntimeError(f"Bridge request failed: {exc}") from exc

    parsed: Dict[str, Any] = {}
    if body:
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
    return code, parsed


def bridge_health(bridge_url: str, token: str = "", timeout_s: float = 3.0) -> Dict[str, Any]:
    code, data = bridge_request(bridge_url, "GET", "/health", token=token, timeout_s=timeout_s)
    if code >= 400:
        raise BridgeRuntimeError(f"Bridge health check failed (HTTP {code})")
    return data if isinstance(data, dict) else {}


def wait_for_bridge(
    bridge_url: str,
    token: str = "",
    timeout_s: float = 60.0,
    require_connected: bool = False,
    poll_interval_s: float = 1.0,
) -> Dict[str, Any]:
    deadline = time.time() + max(1.0, float(timeout_s))
    last_state: Dict[str, Any] = {}
    while time.time() < deadline:
        try:
            health = bridge_health(bridge_url, token=token, timeout_s=min(3.0, poll_interval_s + 1.0))
            state = health.get("state", {}) if isinstance(health, dict) else {}
            last_state = state if isinstance(state, dict) else {}
            if not require_connected:
                return health
            if bool(last_state.get("ready")):
                return health
        except Exception:
            pass
        time.sleep(max(0.2, float(poll_interval_s)))
    raise BridgeRuntimeError(
        "WhatsApp bridge zaman aşımına uğradı."
        + (" (QR eşleştirmesi tamamlanmadı)" if require_connected else "")
    )


def start_bridge_process(
    *,
    session_dir: Path,
    token: str,
    host: str = BRIDGE_HOST,
    port: int = DEFAULT_BRIDGE_PORT,
    print_qr: bool = False,
    detached: bool = True,
    log_path: Optional[Path] = None,
    client_id: str = "default",
) -> subprocess.Popen:
    ensure_bridge_runtime(force_install=False)

    sd = Path(session_dir).expanduser()
    sd.mkdir(parents=True, exist_ok=True)
    cmd = [
        "node",
        str(BRIDGE_SCRIPT_PATH),
        "--host",
        str(host),
        "--port",
        str(int(port)),
        "--session-dir",
        str(sd),
        "--token",
        str(token or ""),
        "--client-id",
        str(client_id or "default"),
    ]
    if print_qr:
        cmd.extend(["--print-qr", "true"])

    if detached:
        target_log = Path(log_path or BRIDGE_LOG_PATH).expanduser()
        target_log.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(target_log, "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=str(BRIDGE_HOME),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BRIDGE_HOME),
        )
    return proc


def stop_bridge(bridge_url: str, token: str = "", timeout_s: float = 3.0) -> bool:
    try:
        code, _ = bridge_request(
            bridge_url=bridge_url,
            method="POST",
            path="/shutdown",
            token=token,
            payload={},
            timeout_s=timeout_s,
        )
        return code < 400
    except Exception:
        return False
