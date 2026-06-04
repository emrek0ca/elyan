use serde::{Deserialize, Serialize};
use sha1::{Digest, Sha1};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use walkdir::WalkDir;

const CACHE_VERSION: u32 = 1;

#[derive(Debug, Deserialize)]
struct RootInput {
    path: String,
    label: String,
}

#[derive(Debug, Deserialize)]
struct ScanRequest {
    command: String,
    roots: Vec<RootInput>,
    #[serde(rename = "cachePath")]
    cache_path: String,
    #[serde(rename = "maxFiles")]
    max_files: Option<usize>,
    #[serde(rename = "allowedExtensions")]
    allowed_extensions: Option<Vec<String>>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct CacheFile {
    id: String,
    path: String,
    name: String,
    #[serde(rename = "rootPath")]
    root_path: String,
    #[serde(rename = "rootLabel")]
    root_label: String,
    size: u64,
    #[serde(rename = "modifiedMs")]
    modified_ms: u128,
    extension: String,
    #[serde(rename = "contentType")]
    content_type: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct CachePayload {
    version: u32,
    #[serde(rename = "scannedAtMs")]
    scanned_at_ms: u128,
    files: Vec<CacheFile>,
}

#[derive(Debug, Serialize)]
struct ScanFile {
    id: String,
    path: String,
    name: String,
    #[serde(rename = "rootPath")]
    root_path: String,
    #[serde(rename = "rootLabel")]
    root_label: String,
    size: u64,
    #[serde(rename = "modifiedMs")]
    modified_ms: u128,
    extension: String,
    #[serde(rename = "contentType")]
    content_type: String,
    changed: bool,
}

#[derive(Debug, Serialize)]
struct ScanStats {
    #[serde(rename = "rootCount")]
    root_count: usize,
    #[serde(rename = "indexedFileCount")]
    indexed_file_count: usize,
}

#[derive(Debug, Serialize)]
struct ScanResponse {
    ok: bool,
    version: &'static str,
    #[serde(rename = "scannedAtMs")]
    scanned_at_ms: u128,
    stats: ScanStats,
    files: Vec<ScanFile>,
    #[serde(rename = "removedPaths")]
    removed_paths: Vec<String>,
    error: Option<String>,
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0)
}

fn normalize_extension(value: &str) -> String {
    let trimmed = value.trim().to_ascii_lowercase();
    if trimmed.is_empty() {
        return String::new();
    }
    if trimmed.starts_with('.') {
        trimmed
    } else {
        format!(".{trimmed}")
    }
}

fn content_type_for(extension: &str) -> &'static str {
    match extension {
        ".txt" | ".md" | ".markdown" => "text/plain",
        ".json" => "application/json",
        ".csv" => "text/csv",
        ".pdf" => "application/pdf",
        ".docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _ => "application/octet-stream",
    }
}

fn stable_file_id(path: &Path, modified_ms: u128, size: u64) -> String {
    let mut hasher = Sha1::new();
    hasher.update(path.to_string_lossy().as_bytes());
    hasher.update(modified_ms.to_string().as_bytes());
    hasher.update(size.to_string().as_bytes());
    format!("{:x}", hasher.finalize())
}

fn load_cache(path: &Path) -> BTreeMap<String, CacheFile> {
    let raw = match fs::read_to_string(path) {
        Ok(value) => value,
        Err(_) => return BTreeMap::new(),
    };
    let payload: CachePayload = match serde_json::from_str(&raw) {
        Ok(value) => value,
        Err(_) => return BTreeMap::new(),
    };
    if payload.version != CACHE_VERSION {
        return BTreeMap::new();
    }
    payload
        .files
        .into_iter()
        .map(|file| (file.path.clone(), file))
        .collect()
}

fn save_cache(path: &Path, scanned_at_ms: u128, files: &[CacheFile]) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let payload = CachePayload {
        version: CACHE_VERSION,
        scanned_at_ms,
        files: files.to_vec(),
    };
    let encoded = serde_json::to_string_pretty(&payload)?;
    fs::write(path, encoded)
}

fn canonicalize_directory(path: &str) -> Option<PathBuf> {
    let candidate = PathBuf::from(path);
    let canonical = candidate.canonicalize().ok()?;
    if canonical.is_dir() {
        Some(canonical)
    } else {
        None
    }
}

fn scan(request: ScanRequest) -> Result<ScanResponse, String> {
    if request.command.trim() != "scan" {
        return Err("unsupported_command".to_string());
    }

    let allowed_extensions: BTreeSet<String> = request
        .allowed_extensions
        .unwrap_or_default()
        .into_iter()
        .map(|value| normalize_extension(&value))
        .filter(|value| !value.is_empty())
        .collect();
    let max_files = request.max_files.unwrap_or(5000);
    let cache_path = PathBuf::from(request.cache_path);
    let previous = load_cache(&cache_path);
    let mut files: Vec<CacheFile> = Vec::new();
    let mut seen_paths: BTreeSet<String> = BTreeSet::new();
    let root_count = request.roots.len();

    'roots: for root in request.roots {
        let Some(root_path) = canonicalize_directory(&root.path) else {
            continue;
        };
        for entry in WalkDir::new(&root_path)
            .follow_links(false)
            .into_iter()
            .filter_map(Result::ok)
        {
            if !entry.file_type().is_file() {
                continue;
            }
            let path = entry.path().to_path_buf();
            let extension = path
                .extension()
                .map(|value| normalize_extension(&value.to_string_lossy()))
                .unwrap_or_default();
            if !allowed_extensions.is_empty() && !allowed_extensions.contains(&extension) {
                continue;
            }
            let metadata = match entry.metadata() {
                Ok(value) => value,
                Err(_) => continue,
            };
            let modified_ms = metadata
                .modified()
                .ok()
                .and_then(|value| value.duration_since(UNIX_EPOCH).ok())
                .map(|value| value.as_millis())
                .unwrap_or(0);
            let size = metadata.len();
            let canonical = match path.canonicalize() {
                Ok(value) => value,
                Err(_) => continue,
            };
            let path_text = canonical.to_string_lossy().to_string();
            if seen_paths.contains(&path_text) {
                continue;
            }
            seen_paths.insert(path_text.clone());
            files.push(CacheFile {
                id: stable_file_id(&canonical, modified_ms, size),
                path: path_text,
                name: canonical
                    .file_name()
                    .map(|value| value.to_string_lossy().to_string())
                    .unwrap_or_else(|| "file".to_string()),
                root_path: root_path.to_string_lossy().to_string(),
                root_label: root.label.clone(),
                size,
                modified_ms,
                extension: extension.clone(),
                content_type: content_type_for(&extension).to_string(),
            });
            if files.len() >= max_files {
                break 'roots;
            }
        }
    }

    files.sort_by(|left, right| left.path.cmp(&right.path));
    let scanned_at_ms = now_ms();
    save_cache(&cache_path, scanned_at_ms, &files).map_err(|error| error.to_string())?;

    let removed_paths = previous
        .keys()
        .filter(|path| !seen_paths.contains(*path))
        .cloned()
        .collect::<Vec<String>>();

    let scan_files = files
        .iter()
        .map(|file| {
            let changed = previous
                .get(&file.path)
                .map(|previous_file| {
                    previous_file.modified_ms != file.modified_ms || previous_file.size != file.size
                })
                .unwrap_or(true);
            ScanFile {
                id: file.id.clone(),
                path: file.path.clone(),
                name: file.name.clone(),
                root_path: file.root_path.clone(),
                root_label: file.root_label.clone(),
                size: file.size,
                modified_ms: file.modified_ms,
                extension: file.extension.clone(),
                content_type: file.content_type.clone(),
                changed,
            }
        })
        .collect::<Vec<ScanFile>>();

    Ok(ScanResponse {
        ok: true,
        version: env!("CARGO_PKG_VERSION"),
        scanned_at_ms,
        stats: ScanStats {
            root_count,
            indexed_file_count: scan_files.len(),
        },
        files: scan_files,
        removed_paths,
        error: None,
    })
}

fn main() {
    let mut input = String::new();
    if io::stdin().read_to_string(&mut input).is_err() {
        let _ = writeln!(
            io::stdout(),
            "{}",
            serde_json::to_string(&ScanResponse {
                ok: false,
                version: env!("CARGO_PKG_VERSION"),
                scanned_at_ms: now_ms(),
                stats: ScanStats {
                    root_count: 0,
                    indexed_file_count: 0,
                },
                files: vec![],
                removed_paths: vec![],
                error: Some("stdin_read_failed".to_string()),
            })
            .unwrap_or_else(|_| "{\"ok\":false}".to_string())
        );
        return;
    }

    let request: ScanRequest = match serde_json::from_str(&input) {
        Ok(value) => value,
        Err(_) => {
            let _ = writeln!(
                io::stdout(),
                "{}",
                serde_json::to_string(&ScanResponse {
                    ok: false,
                    version: env!("CARGO_PKG_VERSION"),
                    scanned_at_ms: now_ms(),
                    stats: ScanStats {
                        root_count: 0,
                        indexed_file_count: 0,
                    },
                    files: vec![],
                    removed_paths: vec![],
                    error: Some("invalid_request".to_string()),
                })
                .unwrap_or_else(|_| "{\"ok\":false}".to_string())
            );
            return;
        }
    };

    let response = match scan(request) {
        Ok(value) => value,
        Err(error) => ScanResponse {
            ok: false,
            version: env!("CARGO_PKG_VERSION"),
            scanned_at_ms: now_ms(),
            stats: ScanStats {
                root_count: 0,
                indexed_file_count: 0,
            },
            files: vec![],
            removed_paths: vec![],
            error: Some(error),
        },
    };
    let _ = writeln!(
        io::stdout(),
        "{}",
        serde_json::to_string(&response).unwrap_or_else(|_| "{\"ok\":false}".to_string())
    );
}
