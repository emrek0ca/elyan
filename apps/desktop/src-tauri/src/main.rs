#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use serde_json::Value;
use std::{
    collections::VecDeque,
    env,
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

const DEFAULT_PORT: u16 = 18789;
const MAX_LOG_LINES: usize = 240;
const EXPECTED_PROTOCOL_VERSION: &str = "elyan-cowork-v1";

#[derive(Default)]
struct RuntimeProbeResult {
    reachable: bool,
    launch_ready: Option<bool>,
    runtime_ready: Option<bool>,
    model_lane_ready: Option<bool>,
    runtime_version: Option<String>,
    runtime_protocol_version: Option<String>,
    health_status: Option<String>,
    launch_blockers: Vec<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct SidecarHealth {
    status: String,
    managed: bool,
    port: u16,
    runtime_url: String,
    admin_token: Option<String>,
    pid: Option<u32>,
    project_dir: Option<String>,
    retries: u32,
    last_error: Option<String>,
    last_started_at: Option<String>,
    last_ready_at: Option<String>,
    desktop_version: String,
    expected_protocol_version: String,
    runtime_version: Option<String>,
    runtime_protocol_version: Option<String>,
    compatible: bool,
    compatibility_reason: Option<String>,
    runtime_ready: Option<bool>,
    model_lane_ready: Option<bool>,
    launch_ready: Option<bool>,
    launch_blockers: Vec<String>,
    health_status: Option<String>,
    last_logs_export_path: Option<String>,
}

impl Default for SidecarHealth {
    fn default() -> Self {
        Self {
            status: "offline".to_string(),
            managed: false,
            port: DEFAULT_PORT,
            runtime_url: runtime_url(DEFAULT_PORT),
            admin_token: None,
            pid: None,
            project_dir: None,
            retries: 0,
            last_error: None,
            last_started_at: None,
            last_ready_at: None,
            desktop_version: env!("CARGO_PKG_VERSION").to_string(),
            expected_protocol_version: EXPECTED_PROTOCOL_VERSION.to_string(),
            runtime_version: None,
            runtime_protocol_version: None,
            compatible: false,
            compatibility_reason: Some("runtime_offline".to_string()),
            runtime_ready: None,
            model_lane_ready: None,
            launch_ready: None,
            launch_blockers: Vec::new(),
            health_status: None,
            last_logs_export_path: None,
        }
    }
}

#[derive(Clone, Default)]
struct SidecarSupervisor {
    child: Arc<Mutex<Option<Child>>>,
    logs: Arc<Mutex<VecDeque<String>>>,
    health: Arc<Mutex<SidecarHealth>>,
}

impl SidecarSupervisor {
    fn boot(&self) -> Result<SidecarHealth, String> {
        self.reconcile_child_state();

        if self.probe_runtime(DEFAULT_PORT).reachable {
            return Ok(self.refresh_health_snapshot());
        }

        {
            let child = self.child.lock().expect("sidecar child lock poisoned");
            if child.is_some() {
                return Ok(self.health_snapshot());
            }
        }

        let project_dir = resolve_project_dir()
            .ok_or_else(|| "Elyan project root could not be resolved for the managed runtime".to_string())?;
        let admin_token = self
            .health_snapshot()
            .admin_token
            .unwrap_or_else(generate_admin_token);
        let mut child = spawn_runtime_process(&project_dir, DEFAULT_PORT, &admin_token)?;
        let pid = child.id();
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();

        if let Some(reader) = stdout {
            spawn_log_reader(self.logs.clone(), "stdout", reader);
        }
        if let Some(reader) = stderr {
            spawn_log_reader(self.logs.clone(), "stderr", reader);
        }

        {
            let mut slot = self.child.lock().expect("sidecar child lock poisoned");
            *slot = Some(child);
        }

        self.push_log_line("supervisor", format!("managed runtime launched on port {}", DEFAULT_PORT));

        let project_dir_str = project_dir.to_string_lossy().to_string();
        self.set_health(|health| {
            health.status = "starting".to_string();
            health.managed = true;
            health.port = DEFAULT_PORT;
            health.admin_token = Some(admin_token.clone());
            health.pid = Some(pid);
            health.project_dir = Some(project_dir_str.clone());
            health.runtime_url = runtime_url(DEFAULT_PORT);
            health.last_started_at = Some(now_stamp());
            health.last_error = None;
            health.clone()
        });

        for _ in 0..60 {
            thread::sleep(Duration::from_millis(250));
            self.reconcile_child_state();
            if self.probe_runtime(DEFAULT_PORT).reachable {
                return Ok(self.refresh_health_snapshot());
            }
        }

        Ok(self.set_health(|health| {
            health.status = "degraded".to_string();
            health.last_error = Some("Runtime launch timed out before readiness probe passed".to_string());
            health.clone()
        }))
    }

    fn stop(&self) -> Result<SidecarHealth, String> {
        self.reconcile_child_state();
        let mut child_slot = self.child.lock().expect("sidecar child lock poisoned");
        if let Some(child) = child_slot.as_mut() {
            child.kill().map_err(|err| err.to_string())?;
            let _ = child.wait();
            self.push_log_line("supervisor", "managed runtime stopped".to_string());
        }
        *child_slot = None;
        drop(child_slot);

        if self.probe_runtime(DEFAULT_PORT).reachable {
            return Ok(self.refresh_health_snapshot());
        }

        Ok(self.set_health(|health| {
            health.status = "stopped".to_string();
            health.managed = false;
            health.pid = None;
            health.clone()
        }))
    }

    fn restart(&self) -> Result<SidecarHealth, String> {
        self.stop()?;
        self.set_health(|health| {
            health.retries = health.retries.saturating_add(1);
            health.clone()
        });
        self.boot()
    }

    fn get_health(&self) -> SidecarHealth {
        self.reconcile_child_state();
        if self.probe_runtime(DEFAULT_PORT).reachable {
            return self.refresh_health_snapshot();
        }
        self.health_snapshot()
    }

    fn get_logs(&self) -> Vec<String> {
        let logs = self.logs.lock().expect("sidecar logs lock poisoned");
        logs.iter().cloned().collect()
    }

    fn export_logs(&self, path: Option<String>) -> Result<String, String> {
        let output_path = resolve_logs_export_path(path)?;
        if let Some(parent) = output_path.parent() {
            std::fs::create_dir_all(parent).map_err(|err| err.to_string())?;
        }
        std::fs::write(&output_path, self.get_logs().join("\n")).map_err(|err| err.to_string())?;
        let exported = output_path.to_string_lossy().to_string();
        self.set_health(|health| {
            health.last_logs_export_path = Some(exported.clone());
            health.clone()
        });
        self.push_log_line("supervisor", format!("sidecar logs exported to {}", exported));
        Ok(exported)
    }

    fn reconcile_child_state(&self) {
        let mut child_slot = self.child.lock().expect("sidecar child lock poisoned");
        let mut exit_message = None;

        if let Some(child) = child_slot.as_mut() {
            match child.try_wait() {
                Ok(Some(status)) => {
                    exit_message = Some(format!(
                        "managed runtime exited with code {}",
                        status.code().unwrap_or(-1)
                    ));
                }
                Ok(None) => {}
                Err(err) => {
                    exit_message = Some(format!("managed runtime status check failed: {err}"));
                }
            }
        }

        if let Some(message) = exit_message {
            *child_slot = None;
            drop(child_slot);
            self.push_log_line("supervisor", message.clone());
            self.set_health(|health| {
                health.status = "error".to_string();
                health.managed = false;
                health.pid = None;
                health.last_error = Some(message.clone());
                health.clone()
            });
        }
    }

    fn refresh_health_snapshot(&self) -> SidecarHealth {
        let probe = self.probe_runtime(DEFAULT_PORT);
        self.set_health(|health| {
            let compatible = probe.runtime_protocol_version.as_deref() == Some(EXPECTED_PROTOCOL_VERSION);
            let launch_ready = probe.launch_ready.unwrap_or(probe.reachable);
            let runtime_ready = probe.runtime_ready.unwrap_or(launch_ready);
            health.runtime_url = runtime_url(DEFAULT_PORT);
            health.runtime_version = probe.runtime_version.clone();
            health.runtime_protocol_version = probe.runtime_protocol_version.clone();
            health.compatible = compatible;
            health.compatibility_reason = if compatible {
                if launch_ready {
                    None
                } else {
                    Some("launch_blocked".to_string())
                }
            } else if probe.runtime_protocol_version.is_none() {
                Some("runtime_protocol_missing".to_string())
            } else {
                Some("runtime_protocol_mismatch".to_string())
            };
            if health.pid.is_none() {
                health.managed = false;
            }
            health.runtime_ready = Some(runtime_ready);
            health.model_lane_ready = probe.model_lane_ready;
            health.launch_ready = Some(launch_ready);
            health.launch_blockers = probe.launch_blockers.clone();
            health.health_status = probe.health_status.clone();
            health.status = if compatible && launch_ready { "healthy".to_string() } else { "degraded".to_string() };
            health.last_error = if compatible && launch_ready {
                None
            } else if !probe.launch_blockers.is_empty() {
                Some(probe.launch_blockers.join("; "))
            } else {
                Some("Runtime launch gate not satisfied".to_string())
            };
            if compatible && launch_ready {
                health.last_ready_at = Some(now_stamp());
            }
            health.clone()
        })
    }

    fn probe_runtime(&self, port: u16) -> RuntimeProbeResult {
        let addr = format!("127.0.0.1:{port}");
        let Ok(mut stream) = TcpStream::connect_timeout(
            &addr.parse().unwrap_or_else(|_| "127.0.0.1:18789".parse().expect("valid default addr")),
            Duration::from_millis(300),
        ) else {
            return RuntimeProbeResult::default();
        };

        let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
        let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
        if stream
            .write_all(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            .is_err()
        {
            return RuntimeProbeResult::default();
        }

        let mut buffer = Vec::new();
        match stream.read_to_end(&mut buffer) {
            Ok(bytes) if bytes > 0 => {
                let response = String::from_utf8_lossy(&buffer[..bytes]).to_string();
                let mut result = RuntimeProbeResult {
                    reachable: response.contains("200 OK") || response.starts_with("HTTP/1.1 200"),
                    ..RuntimeProbeResult::default()
                };
                if let Some((_, body)) = response.split_once("\r\n\r\n") {
                    if let Ok(json) = serde_json::from_str::<Value>(body) {
                        result.launch_ready = json
                            .get("ok")
                            .and_then(Value::as_bool)
                            .or_else(|| {
                                json.get("readiness")
                                    .and_then(|readiness| readiness.get("launch_ready"))
                                    .and_then(Value::as_bool)
                            });
                        result.runtime_ready = json
                            .get("readiness")
                            .and_then(|readiness| readiness.get("elyan_ready"))
                            .and_then(Value::as_bool);
                        result.model_lane_ready = json
                            .get("readiness")
                            .and_then(|readiness| readiness.get("model_lane_ready"))
                            .and_then(Value::as_bool);
                        result.runtime_version = json
                            .get("version")
                            .and_then(Value::as_str)
                            .map(|item| item.to_string());
                        result.runtime_protocol_version = json
                            .get("protocol_version")
                            .and_then(Value::as_str)
                            .map(|item| item.to_string())
                            .or_else(|| {
                                json.get("runtime")
                                    .and_then(|runtime| runtime.get("protocol_version"))
                                    .and_then(Value::as_str)
                                    .map(|item| item.to_string())
                            });
                        result.health_status = json
                            .get("health_status")
                            .and_then(Value::as_str)
                            .map(|item| item.to_string())
                            .or_else(|| {
                                json.get("runtime")
                                    .and_then(|runtime| runtime.get("health_status"))
                                    .and_then(Value::as_str)
                                    .map(|item| item.to_string())
                            });
                        result.launch_blockers = json
                            .get("readiness")
                            .and_then(|readiness| readiness.get("launch_blockers"))
                            .and_then(Value::as_array)
                            .map(|items| {
                                items
                                    .iter()
                                    .filter_map(Value::as_str)
                                    .map(|item| item.trim().to_string())
                                    .filter(|item| !item.is_empty())
                                    .collect::<Vec<String>>()
                            })
                            .unwrap_or_default();
                    }
                }
                result
            }
            _ => RuntimeProbeResult::default(),
        }
    }

    fn health_snapshot(&self) -> SidecarHealth {
        self.health.lock().expect("sidecar health lock poisoned").clone()
    }

    fn set_health(&self, mutate: impl FnOnce(&mut SidecarHealth) -> SidecarHealth) -> SidecarHealth {
        let mut health = self.health.lock().expect("sidecar health lock poisoned");
        mutate(&mut health)
    }

    fn push_log_line(&self, prefix: &str, line: String) {
        let mut logs = self.logs.lock().expect("sidecar logs lock poisoned");
        while logs.len() >= MAX_LOG_LINES {
            logs.pop_front();
        }
        logs.push_back(format!("[{}] {}", prefix, line.trim_end()));
    }
}

fn spawn_log_reader<R: Read + Send + 'static>(logs: Arc<Mutex<VecDeque<String>>>, prefix: &'static str, reader: R) {
    thread::spawn(move || {
        let lines = BufReader::new(reader).lines();
        for line in lines {
            let Ok(line) = line else {
                break;
            };
            let mut locked = logs.lock().expect("sidecar logs lock poisoned");
            while locked.len() >= MAX_LOG_LINES {
                locked.pop_front();
            }
            locked.push_back(format!("[{}] {}", prefix, line.trim_end()));
        }
    });
}

fn resolve_project_dir() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(path) = env::var("ELYAN_PROJECT_DIR") {
        candidates.push(PathBuf::from(path));
    }

    if let Ok(path) = env::current_dir() {
        candidates.push(path);
    }

    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")));

    if let Ok(path) = env::current_exe() {
        if let Some(parent) = path.parent() {
            candidates.push(parent.to_path_buf());
        }
    }

    for candidate in candidates {
        for ancestor in candidate.ancestors() {
            if is_project_root(ancestor) {
                return Some(ancestor.to_path_buf());
            }
        }
    }

    None
}

fn is_project_root(path: &Path) -> bool {
    path.join("elyan_entrypoint.py").exists() && path.join("main.py").exists()
}

fn spawn_runtime_process(project_dir: &Path, port: u16, admin_token: &str) -> Result<Child, String> {
    let project_dir_str = project_dir.to_string_lossy().to_string();
    let python_inline = format!(
        "import sys; sys.path.insert(0, {project_dir:?}); from main import _run_gateway; _run_gateway({port})",
        project_dir = project_dir_str,
        port = port,
    );

    let mut attempts: Vec<(String, Vec<String>)> = Vec::new();
    if let Ok(python) = env::var("ELYAN_PYTHON") {
        attempts.push((
            python,
            vec![
                "-c".to_string(),
                python_inline.clone(),
            ],
        ));
    }

    if cfg!(target_os = "windows") {
        attempts.push((
            "py".to_string(),
            vec![
                "-3".to_string(),
                "-c".to_string(),
                python_inline.clone(),
            ],
        ));
        attempts.push((
            "python".to_string(),
            vec![
                "-c".to_string(),
                python_inline.clone(),
            ],
        ));
    } else {
        attempts.push((
            "python3".to_string(),
            vec![
                "-c".to_string(),
                python_inline.clone(),
            ],
        ));
        attempts.push((
            "python".to_string(),
            vec![
                "-c".to_string(),
                python_inline.clone(),
            ],
        ));
    }

    let mut last_error = String::from("No Python launcher candidate succeeded");

    for (program, args) in attempts {
        let mut command = Command::new(&program);
        command
            .args(args)
            .current_dir(project_dir)
            .env("ELYAN_PROJECT_DIR", project_dir)
            .env("ELYAN_ADMIN_TOKEN", admin_token)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        match command.spawn() {
            Ok(child) => return Ok(child),
            Err(err) => {
                last_error = format!("{program}: {err}");
            }
        }
    }

    Err(last_error)
}

fn runtime_url(port: u16) -> String {
    format!("http://127.0.0.1:{port}")
}

fn resolve_logs_export_path(path: Option<String>) -> Result<PathBuf, String> {
    if let Some(raw) = path {
        let candidate = PathBuf::from(raw);
        if candidate.as_os_str().is_empty() {
            return Err("logs export path is empty".to_string());
        }
        return Ok(candidate);
    }
    let base = resolve_project_dir().unwrap_or_else(env::temp_dir);
    Ok(base
        .join(".elyan")
        .join("exports")
        .join(format!("sidecar-logs-{}.log", now_stamp())))
}

fn now_stamp() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
        .to_string()
}

fn generate_admin_token() -> String {
    let epoch_nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("elyan-desktop-{}-{}", std::process::id(), epoch_nanos)
}

fn open_path(path: &str) -> bool {
    let path = PathBuf::from(path);
    if !path.exists() {
        return false;
    }

    let status = if cfg!(target_os = "macos") {
        Command::new("open").arg(&path).status()
    } else if cfg!(target_os = "windows") {
        Command::new("cmd")
            .args(["/C", "start", "", path.to_string_lossy().as_ref()])
            .status()
    } else {
        Command::new("xdg-open").arg(&path).status()
    };

    status.map(|value| value.success()).unwrap_or(false)
}

fn open_external(target: &str) -> bool {
    let url = target.trim();
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return false;
    }

    let status = if cfg!(target_os = "macos") {
        Command::new("open").arg(url).status()
    } else if cfg!(target_os = "windows") {
        Command::new("cmd").args(["/C", "start", "", url]).status()
    } else {
        Command::new("xdg-open").arg(url).status()
    };

    status.map(|value| value.success()).unwrap_or(false)
}

fn reveal_path(path: &str) -> bool {
    let path = PathBuf::from(path);
    if !path.exists() {
        return false;
    }

    let status = if cfg!(target_os = "macos") {
        Command::new("open").args(["-R", path.to_string_lossy().as_ref()]).status()
    } else if cfg!(target_os = "windows") {
        Command::new("explorer")
            .arg(format!("/select,{}", path.to_string_lossy()))
            .status()
    } else {
        let folder = path.parent().unwrap_or_else(|| Path::new("/"));
        Command::new("xdg-open").arg(folder).status()
    };

    status.map(|value| value.success()).unwrap_or(false)
}

#[tauri::command]
fn boot_runtime(supervisor: tauri::State<'_, SidecarSupervisor>) -> Result<SidecarHealth, String> {
    supervisor.boot()
}

#[tauri::command]
fn stop_runtime(supervisor: tauri::State<'_, SidecarSupervisor>) -> Result<SidecarHealth, String> {
    supervisor.stop()
}

#[tauri::command]
fn restart_runtime(supervisor: tauri::State<'_, SidecarSupervisor>) -> Result<SidecarHealth, String> {
    supervisor.restart()
}

#[tauri::command]
fn get_runtime_health(supervisor: tauri::State<'_, SidecarSupervisor>) -> SidecarHealth {
    supervisor.get_health()
}

#[tauri::command]
fn get_runtime_logs(supervisor: tauri::State<'_, SidecarSupervisor>) -> Vec<String> {
    supervisor.get_logs()
}

#[tauri::command]
fn export_runtime_logs(supervisor: tauri::State<'_, SidecarSupervisor>, path: Option<String>) -> Result<String, String> {
    supervisor.export_logs(path)
}

#[tauri::command]
fn open_artifact(path: String) -> bool {
    open_path(&path)
}

#[tauri::command]
fn reveal_in_folder(path: String) -> bool {
    reveal_path(&path)
}

#[tauri::command]
fn open_external_url(url: String) -> bool {
    open_external(&url)
}

fn main() {
    tauri::Builder::default()
        .manage(SidecarSupervisor::default())
        .invoke_handler(tauri::generate_handler![
            boot_runtime,
            stop_runtime,
            restart_runtime,
            get_runtime_health,
            get_runtime_logs,
            export_runtime_logs,
            open_artifact,
            reveal_in_folder,
            open_external_url
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Elyan desktop shell");
}
