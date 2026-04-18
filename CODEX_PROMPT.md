# CODEX — ELYAN'I ÇALIŞIR HALE GETİRME DİREKTİFİ

> **MİSYON**: Elyan'ı, `elyan setup && elyan start --daemon` ile kurulduktan sonra arka planda sorunsuz çalışan, Telegram/WhatsApp/iMessage'dan komut alan ve bilgisayarda her şeyi yapabilen bir AI operatöre dönüştür.
>
> Şu an Elyan'ın kodu büyük çoğunlukla mevcut ama **birbirine bağlı değil**, **daemon olarak stabil çalışmıyor**, **kanal adaptörleri gateway'e düzgün wire edilmemiş** ve **desktop yüzeyi kırık**. Bu dosya tüm bu sorunları tespit eder ve sırasıyla çözüm direktifleri verir.

---

## BÖLÜM 0: MEVCUT DURUM ANALİZİ

### Neler VAR ama ÇALIŞMIYOR:

| Bileşen | Kod Durumu | Çalışma Durumu | Sorun |
|---------|-----------|---------------|-------|
| `elyan start --daemon` | ✅ Var | ⚠️ Kısmi | PID yönetimi kırılgan, process orphan kalıyor, crash recovery yok |
| launchd daemon (`cli/daemon.py`) | ✅ Var | ❌ Kırık | `elyan gateway start` komutunu çağırıyor ama böyle bir komut yok (`main.py:start`) |
| Telegram adapter | ✅ Var (941 satır) | ⚠️ Kısmi | Gateway start'ta bağlanıyor ama disconnect/reconnect kırılgan, conflict handling var ama auto-retry yok |
| WhatsApp adapter | ✅ Var (502 satır) | ❌ Kırık | Bridge runtime (Node.js) auto-start yok, QR pairing düzgün çalışmıyor, session persist eksik |
| iMessage adapter | ✅ Var (281 satır) | ❌ Kırık | `_supports_secure_websocket()` hardcoded `False`, polling yok, BlueBubbles bağlantısı çalışmıyor |
| Discord adapter | ✅ Var | ⚠️ Kısmi | Token ile başlıyor ama lifecycle management zayıf |
| Desktop (Tauri) | ✅ Var | ❌ Kırık | `npm run tauri:dev` komutu package.json'da tanımlı değil, Tauri binary build yok |
| Gateway server | ✅ Var (11.300 satır) | ⚠️ Kısmi | `_init_adapters()` çalışıyor ama adapter connect hataları sessizce yutuluyor |
| Agent core | ✅ Var (674KB) | ✅ Çalışıyor | Ana ajan mantığı sağlam |
| CLI | ✅ Var (985 satır main.py + 67KB cli/main.py) | ⚠️ Kısmi | İki ayrı CLI var (`main.py` click, `cli/main.py` typer), karışıklık |
| Healthz endpoint | ✅ Var | ✅ Çalışıyor | OK |
| Config sistemi | ✅ Var | ✅ Çalışıyor | `~/.elyan/elyan.json` |

### KRİTİK SORUNLAR (Bu çözülmeden Elyan daemon olarak çalışamaz):

1. **[P0-DAEMON] Daemon modunda process yönetimi kırık** — `elyan start --daemon` subprocess spawn ediyor ama crash recovery, otomatik restart, watchdog yok. launchd plist'i yanlış komut çağırıyor.

2. **[P0-ADAPTER-CONNECT] Adapter bağlantıları start'ta sessizce hata veriyor** — `_init_adapters()` adapter'ı register ediyor ama `router.start_all()` connect hatalarını sadece log'luyor, retry mekanizması supervisor task'lar ile var ama backoff stratejisi çalışmıyor.

3. **[P0-CLI-SPLIT] İki farklı CLI entry point birbiriyle çelişiyor** — `main.py` (click-based, setup/start/stop/models) vs `cli/main.py` (typer-based, 72+ komut). `elyan` komutu `elyan_entrypoint.py` → `cli/main.py`'ye gidiyor. `main.py` direkt `python main.py` ile çalışıyor. Daemon `main.py:_run_gateway()` çağırıyor ama CLI komutları `cli/main.py`'de.

4. **[P0-DESKTOP-BROKEN] Desktop tamamen kırık** — `tauri:dev` script'i package.json'da yok, Tauri build yapılmamış, `open_desktop()` fonksiyonu her iki path'te de başarısız oluyor.

5. **[P0-IMESSAGE-DEAD] iMessage adapter WebSocket hardcoded kapalı** — `_supports_secure_websocket()` her zaman `False` dönüyor, polling modu implement edilmemiş, adapter bağlansa bile mesaj alamıyor.

---

## BÖLÜM 1: DOKUNULMAZ KURALLAR (HER ZAMAN GEÇERLI)

> Bu kurallar AGENTS.md'den gelir. İhlal = REJECT.

### K-01: Var Olmayan Fonksiyon/Sınıf Çağırma YASAK
```bash
grep -r "def fonksiyon_adi" .
grep -r "class SinifAdi" .
```

### K-02: SQLAlchemy 2.0 — text() Zorunlu
```python
from sqlalchemy import text
conn.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
```

### K-03: DB Tabloları Sadece runtime_db.py'de
Yeni tablo → `core/persistence/runtime_db.py` → `LOCAL_METADATA` → `Table(...)`.

### K-04: Routing Guard Sırası DEĞİŞTİRME
`apps/desktop/src/app/routes.tsx`: onboarding → login → home

### K-05: Auth Middleware — Üç Yol
`_require_user_session()`: Header → Cookie → Admin Token (loopback only)

### K-06: Learning Loop — BOZMA
`core/agent.py` → `_finalize_turn()` → `record_task_outcome()`

### K-07: Stub/pass Bırakma YASAK

### K-08: Feature Flag Olmadan Core Değişikliği YASAK

### K-09: Async/Threading Karıştırma YASAK

### K-10: Silent Exception Catch YASAK

### K-11: Monolith Dosya Politikası
- `core/agent.py` (674KB), `core/gateway/server.py` (533KB), `core/pipeline.py` (266KB)
- Küçük targeted değişiklik → OK
- Büyük refactor → YASAK

---

## BÖLÜM 2: KRİTİK DOSYA HARİTASI

| Dosya | Rol | Risk |
|-------|-----|------|
| `main.py` | Click CLI entry (setup/start/stop/models/status) | ORTA |
| `cli/main.py` | Typer CLI entry (72+ komut) | ORTA |
| `elyan_entrypoint.py` | `pip install` sonrası `elyan` komutu → cli/main.py | DÜŞÜK |
| `cli/daemon.py` | launchd/systemd plist yönetimi | KRİTİK |
| `cli/commands/gateway.py` | Gateway start/stop/restart/status/health | KRİTİK |
| `cli/commands/desktop.py` | Desktop launcher | ORTA |
| `cli/commands/channels.py` | Kanal CRUD (add/remove/login/status) | KRİTİK |
| `core/gateway/server.py` | HTTP + WS server (11.3K satır) | YÜKSEK |
| `core/gateway/router.py` | Mesaj routing (1.5K satır) | YÜKSEK |
| `core/gateway/adapters/__init__.py` | Adapter registry | ORTA |
| `core/gateway/adapters/telegram.py` | Telegram bot (941 satır) | ORTA |
| `core/gateway/adapters/whatsapp.py` | WhatsApp bridge/cloud (502 satır) | ORTA |
| `core/gateway/adapters/imessage_adapter.py` | iMessage via BlueBubbles (281 satır) | ORTA |
| `core/gateway/adapters/discord.py` | Discord bot | ORTA |
| `core/gateway/adapters/base.py` | BaseChannelAdapter | DÜŞÜK |
| `core/agent.py` | Ana ajan orkestratörü (674KB) | YÜKSEK |
| `core/persistence/runtime_db.py` | SQLite DB | KRİTİK |
| `install.sh` | Tek komutla kurulum | ORTA |
| `config/elyan_config.py` | Config manager | ORTA |

---

## BÖLÜM 3: ÇALIŞMA AKIŞI (EXECUTION ORDER)

### Faz 0: Self-Diagnostic (15 dk)

Önce mevcut durumu ölç. Hiçbir şey değiştirmeden:

```bash
# 1. Python ortam kontrolü
.venv/bin/python -c "import core.gateway.server; print('server OK')"
.venv/bin/python -c "import core.agent; print('agent OK')"
.venv/bin/python -c "import core.gateway.adapters; print('adapters OK')"

# 2. Başlat ve healthz kontrol et
.venv/bin/python main.py start --port 18789 &
sleep 8
curl -s http://127.0.0.1:18789/healthz | python3 -m json.tool
curl -s http://127.0.0.1:18789/api/channels | python3 -m json.tool

# 3. Adapter durumlarını kontrol et
curl -s http://127.0.0.1:18789/api/channels/status | python3 -m json.tool

# 4. Daemon log kontrol
cat ~/.elyan/logs/gateway.log 2>/dev/null | tail -50

# 5. Kapat
kill %1
```

Sonuçları not al. Bu baseline.

---

### Faz 1: CLI Birleştirme ve Daemon Düzeltmesi (45 dk)

**Sorun**: İki ayrı CLI (`main.py` click, `cli/main.py` typer) var. `main.py` setup/start/stop sağlıyor. CLI komutu (`elyan`) ise `cli/main.py`'ye gidiyor. Daemon plist yanlış komutu çağırıyor.

**Yapılacak**:

#### 1.1 CLI Entrypoint Birleştirme

**Dosya**: `cli/main.py`

`cli/main.py` Typer CLI'ı ana CLI olmalı. `main.py`'deki `setup`, `start`, `stop`, `restart`, `status`, `models`, `doctor`, `desktop`, `config`, `logs`, `team` komutlarının hepsini `cli/main.py`'ye taşı veya import et. `main.py` sadece `_run_gateway()` fonksiyonunu export etsin.

```python
# main.py — sadece gateway runner
def _run_gateway(port: int): ...  # mevcut haliyle kalsın

# cli/main.py — tüm CLI komutları burada
# main.py:setup, start, stop, models komutlarını buraya taşı
```

#### 1.2 Daemon Plist Düzeltmesi

**Dosya**: `cli/daemon.py`

`_program_arguments()` şu an `["elyan", "gateway", "start"]` üretiyor. Ama `elyan gateway start` komutu eğer `cli/main.py`'deki gateway subcommand ise sorun yok. Kontrol et:

```bash
grep -r "def start_gateway\|gateway.*start" cli/commands/gateway.py
```

Eğer `cli/commands/gateway.py:start_gateway()` zaten `main.py:_run_gateway()` çağırıyorsa → daemon plist doğru. Sadece şunları doğrula:
- `elyan` binary'si `.venv/bin/elyan` olarak çalışabilir mi?
- `gateway start` → `cli/commands/gateway.py:start_gateway(daemon=False)` çağrılıyor mu?

Daemon plist'e **environment variables** ekle:
```python
# cli/daemon.py → _install_macos()
# plist içine EnvironmentVariables ekle:
"""
    <key>EnvironmentVariables</key>
    <dict>
        <key>ELYAN_PROJECT_DIR</key>
        <string>{self.project_root}</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
"""
```

#### 1.3 Crash Recovery / Watchdog

**Dosya**: `cli/daemon.py` (launchd KeepAlive zaten var — doğrula)

launchd plist'te `KeepAlive: true` var. Bu macOS'ta otomatik restart sağlar. Ama ek olarak:

**Dosya**: YENİ `core/watchdog.py`
```python
"""Gateway health watchdog — daemon modda crash sonrası restart."""
import asyncio
import time
import httpx
from utils.logger import get_logger

logger = get_logger("watchdog")

class GatewayWatchdog:
    def __init__(self, port: int = 18789, check_interval: int = 30):
        self.port = port
        self.check_interval = check_interval
        self._consecutive_failures = 0
        self._max_failures = 3
    
    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://127.0.0.1:{self.port}/healthz")
                data = resp.json()
                return bool(data.get("ok"))
        except Exception:
            return False
    
    async def run(self):
        while True:
            await asyncio.sleep(self.check_interval)
            ok = await self.health_check()
            if ok:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1
                logger.warning(f"Health check failed ({self._consecutive_failures}/{self._max_failures})")
                if self._consecutive_failures >= self._max_failures:
                    logger.error("Gateway unresponsive. Watchdog triggering restart.")
                    # launchd KeepAlive will restart the process
                    import sys
                    sys.exit(1)
```

---

### Faz 2: Adapter Connect Güçlendirme (60 dk)

**Sorun**: `_init_adapters()` adapter'ları register ediyor, `router.start_all()` connect'leri çağırıyor. Ama connect hataları disconnect olan adapter'ı deaktif bırakıyor. Otomatik retry/reconnect mekanizması yeterli değil.

#### 2.1 Adapter Supervisor Güçlendirme

**Dosya**: `core/gateway/router.py`

`start_all()` ve supervisor mekanizmasını incele. Emin ol ki:

```python
async def start_all(self):
    """Tüm adapter'ları başlat. Başarısız olanlar için retry supervisor başlat."""
    for name, adapter in self.adapters.items():
        try:
            await adapter.connect()
            self._adapter_health[name]["connected"] = True
            self._adapter_health[name]["status"] = "connected"
            logger.info(f"Adapter {name} connected successfully")
        except Exception as e:
            logger.error(f"Adapter {name} connect failed: {e}")
            self._adapter_health[name]["last_error"] = str(e)
            self._adapter_health[name]["status"] = "failed"
            # Supervisor task başlat — retry'ı burada yap
            self._start_supervisor(name)
```

Supervisor task'ların şunları yaptığından emin ol:
1. Exponential backoff ile retry (5s, 10s, 30s, 60s, 120s, max 300s)
2. Her retry'da `adapter.connect()` çağır
3. Başarılı olunca health state güncelle
4. 10 ardışık başarısızlıktan sonra durma ama 5 dakikada bir tekrar dene

#### 2.2 Telegram Adapter — Polling Conflict Recovery

**Dosya**: `core/gateway/adapters/telegram.py`

Mevcut `_handle_polling_error` conflict algılayıp polling durduruyor. Ama otomatik reconnect yok.

```python
async def _stop_after_conflict(self) -> None:
    """Conflict sonrası polling durdur ve supervisor'a bırak."""
    # Mevcut logic...
    # Ekle: self._is_connected = False → supervisor retry'ı algılar
    self._is_connected = False
    self._polling_conflict = True
```

Supervisor'ın conflict sonrası 30 saniye bekleyip tekrar `connect()` çağırdığından emin ol.

#### 2.3 iMessage Adapter — Polling Mode

**Dosya**: `core/gateway/adapters/imessage_adapter.py`

WebSocket `_supports_secure_websocket()` kapalı. Polling modu implement et:

```python
async def connect(self):
    # ... mevcut kod ...
    self._is_connected = True
    # WebSocket yerine polling başlat
    self._poll_task = asyncio.create_task(self._poll_loop())

async def _poll_loop(self):
    """BlueBubbles REST API polling ile yeni mesajları al."""
    while self._is_connected:
        try:
            url = f"{self.server_url}/api/v1/message"
            params = {
                "password": self.password,
                "limit": 10,
                "offset": 0,
                "sort": "DESC",
                "after": self._last_poll_ts,
            }
            async with self._session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    messages = data.get("data", [])
                    for msg in messages:
                        await self._process_message(msg)
                    if messages:
                        # En son mesajın timestamp'ini kaydet
                        latest = max(
                            (m.get("dateCreated", 0) for m in messages),
                            default=0
                        )
                        if latest > self._last_poll_ts:
                            self._last_poll_ts = latest
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"iMessage poll error: {exc}")
        await asyncio.sleep(2.0)  # 2 saniye interval
```

#### 2.4 WhatsApp Adapter — Auto Bridge Start

**Dosya**: `core/gateway/adapters/whatsapp.py`

`connect()` içinde `_ensure_bridge_running()` çağrılıyor ama `auto_start_bridge` config'den geliyor. Emin ol ki:
1. Node.js runtime kontrolü (which node)
2. Bridge process crash recovery
3. QR pairing session persist (session_dir)

---

### Faz 3: Background Service Stabilizasyonu (45 dk)

**Sorun**: `elyan start --daemon` çalışıyor ama güvenilir değil.

#### 3.1 `elyan start --daemon` Güçlendirme

**Dosya**: `main.py` → `start()` ve `_run_gateway()`

Mevcut daemon mode:
```python
proc = subprocess.Popen(
    [sys.executable, "-c", f"...from main import _run_gateway; _run_gateway({port})"],
    stdout=open(HOME / "logs" / "gateway.out.log", "a"),
    stderr=open(HOME / "logs" / "gateway.err.log", "a"),
    start_new_session=True, cwd=str(project_root)
)
```

**Düzeltme**:
1. Log rotation ekle (dosya boyutu kontrolü)
2. PID dosyası güncelle (`~/.elyan/gateway.pid`)
3. Stdout/stderr log'larını birleştir tek dosyada
4. Startup health check ekle (daemon başlattıktan sonra 15s bekle, healthz kontrol et)

```python
@cli.command()
@click.option("--port", default=PORT)
@click.option("--daemon", is_flag=True)
def start(port, daemon):
    """🚀 Gateway'i başlat."""
    if daemon:
        # ... mevcut Popen kodu ...
        proc = subprocess.Popen(...)
        
        # PID dosyası yaz
        pid_file = HOME / "gateway.pid"
        pid_file.write_text(str(proc.pid))
        
        # Health check bekle
        click.echo(f"  ⏳ Gateway başlatılıyor (PID: {proc.pid})...")
        for _ in range(30):
            time.sleep(0.5)
            if _port_alive(port):
                health = _gateway_health(port)
                if health.get("ok"):
                    click.echo(f"  ✅ Gateway hazır — http://127.0.0.1:{port}")
                    return
        click.echo(f"  ⚠️ Gateway henüz hazır değil. Log: ~/.elyan/logs/gateway.err.log")
```

#### 3.2 launchd Service Install Komutu

**Dosya**: `main.py` veya `cli/main.py`

`elyan service install` ve `elyan service uninstall` komutları ekle:

```python
@cli.group()
def service():
    """🔧 Sistem servisi yönetimi (launchd/systemd)."""
    pass

@service.command("install")
def service_install():
    """Elyan'ı sistem servisi olarak kur (boot'ta otomatik başlar)."""
    from cli.daemon import daemon_manager
    ok = daemon_manager.install()
    if ok:
        click.echo("✅ Sistem servisi kuruldu. Elyan açılışta otomatik başlayacak.")
    else:
        click.echo("❌ Servis kurulumu başarısız.")

@service.command("uninstall")
def service_uninstall():
    """Sistem servisini kaldır."""
    from cli.daemon import daemon_manager
    ok = daemon_manager.uninstall()
    click.echo("✅ Servis kaldırıldı." if ok else "❌ Servis kaldırılamadı.")
```

---

### Faz 4: Channel Auto-Connect on Start (30 dk)

**Sorun**: Gateway başlayınca `_init_adapters()` config'den kanalları okuyor ve register ediyor. Sonra `router.start_all()` ile connect'leri çağırıyor. Ama env token'lar düzgün resolve edilmiyor.

#### 4.1 Token Resolution Fix

**Dosya**: `core/gateway/server.py` → `_init_adapters()`

Mevcut auto-detect sadece `TELEGRAM_BOT_TOKEN` ve `DISCORD_BOT_TOKEN` env var'larını kontrol ediyor. Bunu genişlet:

```python
# _init_adapters() sonuna ekle:
env_channels = {
    "telegram": "TELEGRAM_BOT_TOKEN",
    "discord": "DISCORD_BOT_TOKEN",
    "whatsapp": "WHATSAPP_BRIDGE_TOKEN",  # Bridge mode
}
```

Ayrıca config'deki `$ENV_VAR` referanslarının runtime'da doğru resolve edildiğinden emin ol:

```python
# Adapter config'teki $TOKEN referanslarını resolve et
for key, val in ch.items():
    if isinstance(val, str) and val.startswith("$"):
        env_key = val[1:]
        resolved = os.environ.get(env_key, "")
        if not resolved:
            # Keychain'den dene
            try:
                from security.keychain import keychain
                resolved = keychain.get_key(env_key) or ""
            except Exception:
                pass
        if resolved:
            ch[key] = resolved
```

#### 4.2 Startup Kanal Durumu Log

Gateway başlayınca kanal durumlarını açıkça logla:

```python
# _init_adapters() sonuna ekle
for name, health in self._adapter_health.items():
    status = health.get("status", "unknown")
    logger.info(f"Channel [{name}]: {status}")
```

---

### Faz 5: Güvenlik Düzeltmeleri (30 dk)

#### SEC-1: WebSocket Token URL'den Kaldır [KRİTİK]

**Dosya**: `apps/desktop/src/services/websocket/runtime-socket.ts`

```typescript
// KALDIR:
socketUrl.searchParams.set("token", token.trim());

// YERİNE:
socket.onopen = () => {
  socket.send(JSON.stringify({ type: "auth", token: token.trim() }));
};
```

#### SEC-2: Webhook Timing Attack [KRİTİK]

**Dosya**: `core/billing/iyzico_provider.py`

```python
# KALDIR:
if computed_signature == received_signature:

# YERİNE:
import hmac
if hmac.compare_digest(computed_signature, received_signature):
```

#### SEC-3: Query String Admin Auth Kaldır [YÜKSEK]

**Dosya**: `core/gateway/server.py` (~satır 1704)
```python
# KALDIR:
or query.get("token", "")
or query.get("admin_token", "")
```

#### SEC-4: Rate Limiter Auth Endpoint'lerine Bağla

**Dosya**: `core/gateway/server.py`
`handle_v1_auth_login` ve `handle_bootstrap_owner` başına rate limit ekle.

---

### Faz 6: Desktop Düzeltme veya Devre Dışı Bırakma (30 dk)

**Sorun**: Desktop (Tauri) tamamen kırık. `npm run tauri:dev` yok.

**Seçenek A (Hızlı — Önerilen)**: Desktop'u şimdilik devre dışı bırak, yalnızca CLI + Web Chat + Telegram olarak çalıştır.

```python
# cli/commands/desktop.py → open_desktop()
# Tauri yerine basit bir web UI aç:
def open_desktop(*, detached: bool = False) -> int:
    root = _project_root()
    _ensure_gateway_ready(root)
    port = int(os.environ.get("ELYAN_PORT", "18789"))
    import webbrowser
    webbrowser.open(f"http://127.0.0.1:{port}")
    print(f"🖥️  Elyan Web UI açıldı: http://127.0.0.1:{port}")
    return 0
```

**Seçenek B (Uzun — Tauri Fix)**:
1. `apps/desktop/package.json`'a `tauri:dev` script ekle
2. `apps/desktop/src-tauri/` altında Cargo.toml ve `main.rs` var mı kontrol et
3. Tauri binary build: `cd apps/desktop && npm run tauri build`

---

### Faz 7: Computer Control Yeteneği (45 dk)

Elyan'ın bilgisayarda her şeyi yapabilmesi için mevcut tool'ların gateway'e bağlı olması gerekiyor.

#### 7.1 Mevcut Tool Kontrolü

```bash
# Hangi tool'lar register edilmiş:
grep -r "tool_schemas\|register_tool\|ToolDefinition" core/tool_schemas*.py | head -30
grep -r "def execute_tool\|async def execute" core/tool_runtime/ | head -20
```

#### 7.2 Shell Execution

**Dosya**: `core/tool_runtime/` altında bir shell executor olmalı.

Eğer yoksa minimal implement et:
```python
# core/tool_runtime/shell_executor.py
import asyncio
import subprocess

async def execute_shell(command: str, timeout: int = 60) -> dict:
    """Execute shell command with safety checks."""
    # Güvenlik: destructive komutlar onay gerektirir
    dangerous = ["rm -rf", "mkfs", "dd if=", "format"]
    if any(d in command.lower() for d in dangerous):
        return {"error": "Bu komut onay gerektirir", "needs_approval": True}
    
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return {
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "returncode": proc.returncode,
        }
    except asyncio.TimeoutError:
        return {"error": f"Command timed out after {timeout}s"}
```

#### 7.3 AppleScript / Automator Entegrasyonu

**Dosya**: `core/personal_context_engine.py` zaten AppleScript polling yapıyor. Bunu genişlet:

```python
# core/os_adapters/ altında macOS aksiyonları:
# - open_application(name)
# - open_url(url)  
# - send_notification(title, body)
# - get_clipboard()
# - set_clipboard(text)
# - take_screenshot(path)
# - get_active_window()
```

---

### Faz 8: End-to-End Test (20 dk)

Her faz sonrası ve tüm fazlar tamamlandıktan sonra:

```bash
# 1. Gateway arka planda başlat
.venv/bin/python main.py start --daemon --port 18789

# 2. Health check
sleep 10
curl -s http://127.0.0.1:18789/healthz | python3 -m json.tool

# 3. Kanal durumları
curl -s http://127.0.0.1:18789/api/channels | python3 -m json.tool

# 4. External API üzerinden mesaj gönder
curl -s -X POST http://127.0.0.1:18789/api/message \
  -H "Content-Type: application/json" \
  -d '{"text": "merhaba", "channel": "api", "wait": true}' | python3 -m json.tool

# 5. Telegram adapter bağlı mı (TELEGRAM_BOT_TOKEN varsa)
curl -s http://127.0.0.1:18789/api/channels/status | python3 -m json.tool

# 6. Log kontrol
tail -20 ~/.elyan/logs/gateway.log

# 7. Process durumu
ps aux | grep elyan | grep -v grep

# 8. Kapat
.venv/bin/python main.py stop
```

---

## BÖLÜM 4: BİLİNEN TEKNİK BORÇ

### KRİTİK

**[C-1] Çift run_store.py**
- `core/run_store.py` → canonical
- `core/evidence/run_store.py` → kaldır veya redirect

**[C-2] Threading vs Async Lock**
- `core/performance/cache_manager.py`: asyncio.Lock() ✓
- `core/performance_cache.py`: threading.RLock() → deadlock riski async context'te

### YÜKSEK

**[H-1] Stub Modüller**
- `core/health_checks.py` — 13KB var ama implement durumu kontrol et
- `core/realtime_actuator/` — stub durumu kontrol et

**[H-2] Tutarsız Response Formatları**
- `dashboard_api.py`: `{"success": bool, "data": ...}`
- `http_server.py`: `(dict, int)` tuple

**[H-3] Versiyon Uyumsuzluğu**
- `core/version.py` canonical olmalı, `main.py` oradan import etmeli (zaten yapıyor: `from core.version import APP_VERSION as VERSION`)

---

## BÖLÜM 5: ENV YAPISI

```bash
# Zorunlu
ELYAN_PORT=18789

# Model (en az biri zorunlu)
OLLAMA_HOST=http://localhost:11434
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
GROQ_API_KEY=

# Kanallar (opsiyonel ama hedef)
TELEGRAM_BOT_TOKEN=        # Telegram bot token
TELEGRAM_CHAT_ID=          # Bildirimler için
DISCORD_BOT_TOKEN=
WHATSAPP_BRIDGE_TOKEN=     # WhatsApp bridge secret

# Güvenlik
ELYAN_ADMIN_TOKEN=         # yoksa otomatik üretilir

# Feature Flags
ELYAN_AUTO_INSTALL=0
ELYAN_GENESIS_ENABLED=0
ELYAN_VOICE_ENABLED=0
```

---

## BÖLÜM 6: KABUL KRİTERLERİ

Bu direktifin başarılı olması için aşağıdaki koşulların HEPSİ sağlanmalı:

### Tier 1: Gateway Daemon (ZORUNLU)
1. ✅ `elyan start --daemon` sonrası gateway arka planda çalışıyor
2. ✅ `curl http://127.0.0.1:18789/healthz` → `{"ok": true}`
3. ✅ Process crash sonrası launchd servis ile otomatik restart
4. ✅ PID dosyası düzgün yönetiliyor (`~/.elyan/gateway.pid`)
5. ✅ Log dosyaları düzgün yazılıyor (`~/.elyan/logs/`)

### Tier 2: Kanal Bağlantıları (ZORUNLU en az 1)
6. ✅ Telegram adapter TELEGRAM_BOT_TOKEN varsa otomatik bağlanıyor
7. ✅ Telegram'dan gelen mesaj → Agent → Yanıt → Telegram'a geri
8. ✅ Adapter disconnect sonrası otomatik reconnect (supervisor)
9. ⬜ WhatsApp QR pairing çalışıyor (`elyan channels login whatsapp`)
10. ⬜ iMessage BlueBubbles polling ile mesaj alıyor

### Tier 3: Computer Control (HEDEF)
11. ⬜ Shell execution tool çalışıyor (güvenlik kontrollü)
12. ⬜ Telegram'dan "masaüstünü temizle" → AppleScript çalışır
13. ⬜ Dosya okuma/yazma tool'ları aktif

### Tier 4: Stability (HEDEF)
14. ⬜ 24 saat kesintisiz daemon çalışması
15. ⬜ Memory leak yok (RSS < 500MB stabilize)
16. ⬜ Tüm pre-existing testler geçiyor (yeni kod bunları bozmuyor)

---

## BÖLÜM 7: TEST PROTOKOLÜ

```bash
# 1. Python syntax doğrulama
.venv/bin/python -c "import ast; ast.parse(open('main.py').read()); print('main.py OK')"
.venv/bin/python -c "import ast; ast.parse(open('core/gateway/server.py').read()); print('server.py OK')"

# 2. Unit testler (mevcut testleri bozmadan)
.venv/bin/python -m pytest tests/unit/ -x --timeout=30 -q 2>&1 | tail -20

# 3. Daemon integration test
.venv/bin/python main.py start --daemon
sleep 10
curl -sf http://127.0.0.1:18789/healthz && echo "PASS" || echo "FAIL"
.venv/bin/python main.py stop

# 4. Kanal testi (TELEGRAM_BOT_TOKEN varsa)
curl -s http://127.0.0.1:18789/api/channels | python3 -c "
import json, sys
data = json.load(sys.stdin)
channels = data.get('channels', [])
for ch in channels:
    print(f\"  {ch.get('type','?')}: {ch.get('status','?')}\")
"
```

### Test Kuralları
- ~2791 test, ~57 pre-existing failure var. BUNLARA DOKUNMA.
- Pre-existing failures: `test_agent_routing` (16), `test_computer_use_*` (18), `test_llm_router` (4)
- Yeni feature → önce test yaz, sonra implement et.

---

## BÖLÜM 8: PRESERVATION-FIRST İLKESİ

> Çalışan kodu kırma. Yeniye ekle, eskiyi sar.

1. **Mevcut `_init_adapters()` mantığını BOZMA** — sadece token resolution ve logging ekle
2. **`core/agent.py`'ye DOKUNMA** — agent mantığı çalışıyor
3. **`core/gateway/server.py`'ye minimal değişiklik** — sadece targeted fix
4. **Yeni dosyalar oluştur**, mevcut dosyaları büyük çapta değiştirme
5. **Feature flag olmadan planner/router değişikliği YASAK**

---

## BÖLÜM 9: COMMIT STİLİ

```bash
git add <sadece değiştirilen dosyalar>
git commit -m "$(cat <<'EOF'
fix(daemon): PID yönetimi ve crash recovery düzeltmesi

- PID dosyası düzgün yazılıyor
- Startup health check eklendi
- launchd plist environment variables düzeltildi

Closes: #daemon-stability
EOF
)"
```

- Her güvenlik düzeltmesi ayrı commit
- Her bileşen ayrı commit
- Büyük olmayan bug fix'ler gruplandırılabilir

---

## BÖLÜM 10: MEVCUT ÖZELLİKLER (BUNLAR VAR — YENİDEN YAZMA)

| Özellik | Konum | Durum |
|---------|-------|-------|
| Learning loop | `core/agent.py` → `_finalize_turn()` | ✓ Çalışıyor |
| Terminal CLI (72+ komut) | `cli/main.py` + `cli/commands/` | ✓ Çalışıyor |
| Gateway HTTP server | `core/gateway/server.py` | ✓ Çalışıyor |
| Telegram adapter | `core/gateway/adapters/telegram.py` | ⚠️ Kısmi |
| WhatsApp adapter | `core/gateway/adapters/whatsapp.py` | ⚠️ Kısmi |
| iMessage adapter | `core/gateway/adapters/imessage_adapter.py` | ❌ WebSocket kapalı |
| Discord adapter | `core/gateway/adapters/discord.py` | ⚠️ Kısmi |
| Multi-LLM (11 provider) | `core/model_orchestrator.py` | ✓ Çalışıyor |
| Config sistemi | `config/elyan_config.py` + `~/.elyan/elyan.json` | ✓ Çalışıyor |
| Adapter registry | `core/gateway/adapters/__init__.py` (11 adapter) | ✓ Çalışıyor |
| Channel CLI | `cli/commands/channels.py` | ✓ Çalışıyor |
| Gateway CLI | `cli/commands/gateway.py` | ✓ Çalışıyor |
| Daemon manager | `cli/daemon.py` (launchd) | ⚠️ Kısmi |
| Setup wizard | `main.py:setup()` | ✓ Çalışıyor |
| Doğal dil zamanlama | `core/nl_cron.py` | ✓ Çalışıyor |
| Decision Fabric | `core/decision_fabric.py` | ✓ Çalışıyor |
| Feature Flags | `core/feature_flags.py` | ✓ Çalışıyor |
| Iyzico billing | `core/billing/iyzico_provider.py` | ✓ Çalışıyor |
| Security (CSRF, rate limit) | Gateway seviyesinde | ✓ Çalışıyor |

---

## BÖLÜM 11: MİMARİ KARARLAR (ADR)

1. **ADR-001**: Elyan Operator Runtime'dır, chatbot değil
2. **ADR-002**: Üç katmanlı intent routing (Kural → Fuzzy → LLM)
3. **ADR-003**: Core sistemler singleton pattern
4. **ADR-004**: Operator aksiyonları için evidence zorunlu
5. **ADR-005**: Approval seviyeleri (AUTO, CONFIRM, SCREEN, TWO_FA)
6. **ADR-006**: Karmaşık projeler INTAKE→PLAN→EXECUTE→VERIFY→DELIVER
7. **ADR-007**: Bilgisayar görüşü tamamen local
8. **ADR-008**: Inter-agent mesaj bus (AgentMessageBus singleton)
9. **ADR-023**: Multi-channel gateway — tek pipeline, çoklu giriş noktası

---

## BÖLÜM 12: KALİTE KAPSISI

Bir değişikliği commit etmeden:

- [ ] Daemon başlıyor ve 60 saniye boyunca çalışıyor mu?
- [ ] Healthz endpoint doğru yanıt veriyor mu?
- [ ] En az bir kanal adapter'ı bağlanıyor mu?
- [ ] Mesaj alıp yanıt veriyor mu?
- [ ] Session isolation bozuluyor mu?
- [ ] Log olmadan side effect oluyor mu?
- [ ] Pre-existing testler bozuldu mu?
- [ ] Silent catch var mı?

---

## SONUÇ: ÖNCELİK SIRASI

```
sen = Codex Agent. Aşağıdaki sırayla ilerle:

 1. Faz 0: Self-Diagnostic — mevcut durumu ölç
 2. Faz 1: CLI birleştir, daemon plist düzelt
 3. Faz 2: Adapter connect güçlendir (supervisor, retry, reconnect)
 4. Faz 3: Background service stabilize et (PID, health check, watchdog)
 5. Faz 4: Channel auto-connect (token resolution, startup logging)
 6. Faz 5: Güvenlik düzeltmeleri (SEC-1..4)
 7. Faz 6: Desktop düzelt veya devre dışı bırak
 8. Faz 7: Computer control tool'ları wire et
 9. Faz 8: End-to-end test
10. Commit ve tag

Her faz sonunda Faz 8'deki testleri çalıştır.
Gateway daemon olarak 60 saniye kesintisiz çalışmıyorsa bir sonraki faza GEÇME.
```

**Elyan tıpkı OpenClaw gibi çalışmalı:**
1. `bash install.sh` → kurulum tamamlandı
2. `elyan setup` → model seç, API key gir, kanal ekle
3. `elyan start --daemon` → arka planda çalışmaya başladı
4. Telegram/WhatsApp/iMessage'dan mesaj at → yanıt al
5. "Bilgisayarımda şunu yap" → agent yapar, onay isterse kanaldan onay al

Emin değilsen:
**Daha basit** → **Daha güvenli** → **Daha gözlemlenebilir** → **Daha kolay genişletilebilir**
