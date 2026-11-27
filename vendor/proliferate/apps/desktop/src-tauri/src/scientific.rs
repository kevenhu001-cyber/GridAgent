//! Desktop-owned persistent IPC to the GridAgent scientific core.
//! The initial lane is read-only. No model or renderer supplies an executable or root.
use serde_json::{json, Value};
use std::{path::PathBuf, process::Stdio, time::Duration};
use tauri::State;
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command},
    sync::Mutex,
    time::timeout,
};

const MAX_REQUEST: usize = 64 * 1024;
const MAX_RESPONSE: u64 = 4 * 1024 * 1024 + 1;

#[derive(Default)]
pub struct ScientificState(Mutex<Option<ScientificProcess>>);

struct ScientificProcess {
    _child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
}

fn configured_path(key: &str, file: bool) -> Result<PathBuf, String> {
    let path = std::env::var_os(key).map(PathBuf::from)
        .ok_or_else(|| format!("Scientific development configuration missing: {key}"))?;
    if !path.is_absolute() || (if file { !path.is_file() } else { !path.is_dir() }) {
        return Err(format!("Invalid scientific development configuration: {key}"));
    }
    path.canonicalize().map_err(|_| "Cannot resolve scientific configuration".to_string())
}

impl ScientificProcess {
    fn start() -> Result<Self, String> {
        // Development-only host configuration. Packaged runtime discovery and
        // user-authorized workspace selection replace this in the next phase.
        let python = configured_path("GRIDAGENT_NATIVE_PYTHON", true)?;
        let root = configured_path("GRIDAGENT_NATIVE_WORKSPACE", false)?;
        let mut command = Command::new(python);
        command.args(["-X", "utf8", "-m", "gridagent.native_service"])
            .arg(&root).current_dir(&root)
            .env_clear().env("PYTHONNOUSERSITE", "1")
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null())
            .kill_on_drop(true);
        for (key, value) in std::env::vars_os() {
            let name = key.to_string_lossy().to_ascii_uppercase();
            if matches!(name.as_str(), "PATH" | "HOME" | "USERPROFILE" | "SYSTEMROOT" |
                "WINDIR" | "TEMP" | "TMP" | "LOCALAPPDATA" | "APPDATA" | "LANG" |
                "LC_ALL" | "LD_LIBRARY_PATH" | "COMSPEC" | "PATHEXT" |
                "GRIDAGENT_SANDBOX_RUNTIME") {
                command.env(key, value);
            }
        }
        let mut child = command.spawn().map_err(|_| "Cannot start scientific service".to_string())?;
        let input = child.stdin.take().ok_or("Scientific stdin unavailable")?;
        let output = BufReader::new(child.stdout.take().ok_or("Scientific stdout unavailable")?);
        Ok(Self { _child: child, input, output })
    }

    async fn request(&mut self, method: &str, params: Value) -> Result<Value, String> {
        let id = uuid::Uuid::new_v4().simple().to_string();
        let mut frame = serde_json::to_vec(&json!({
            "version": 1, "id": id, "method": method, "params": params,
        })).map_err(|_| "Invalid scientific request")?;
        frame.push(b'\n');
        if frame.len() > MAX_REQUEST {
            return Err("Scientific request exceeds limit".into());
        }
        self.input.write_all(&frame).await.map_err(|_| "Scientific write failed")?;
        self.input.flush().await.map_err(|_| "Scientific flush failed")?;
        let mut line = Vec::new();
        let mut bounded = (&mut self.output).take(MAX_RESPONSE);
        bounded.read_until(b'\n', &mut line).await.map_err(|_| "Scientific read failed")?;
        if line.last() != Some(&b'\n') || line.len() as u64 >= MAX_RESPONSE {
            return Err("Incomplete or oversized scientific response".into());
        }
        let response: Value = serde_json::from_slice(&line).map_err(|_| "Invalid scientific response")?;
        if response["version"].as_u64() != Some(1) || response["id"].as_str() != Some(id.as_str())
            || !response["ok"].is_boolean() {
            return Err("Scientific protocol mismatch".into());
        }
        Ok(response)
    }
}

#[tauri::command]
pub async fn scientific_read(
    state: State<'_, ScientificState>, method: String, params: Value,
) -> Result<Value, String> {
    if !matches!(method.as_str(), "hello" | "scientific.status" | "scientific.runs" |
        "scientific.artifact" | "solver.backends" | "solver.table" | "workspace.files") {
        return Err("Unknown or non-read scientific operation".into());
    }
    let mut guard = state.0.lock().await;
    // Own the child during the exchange: cancellation drops it rather than
    // leaving a stale response queued for the next request.
    let mut process = match guard.take() {
        Some(process) => process,
        None => ScientificProcess::start()?,
    };
    match timeout(Duration::from_secs(30), process.request(&method, params)).await {
        Ok(Ok(response)) => {
            *guard = Some(process);
            Ok(response)
        }
        Ok(Err(error)) => Err(error),
        Err(_) => Err("Scientific request timed out; connection discarded".into()),
    }
}
