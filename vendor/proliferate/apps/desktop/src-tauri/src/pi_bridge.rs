//! Development-only bridge to the embedded Pi worker. No external Agent fallback.
use serde_json::{json, Value};
use std::{path::PathBuf, process::Stdio, time::Duration};
use tauri::State;
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, Command},
    sync::{mpsc, Mutex},
    task::JoinHandle,
    time::timeout,
};

const MAX_FRAME: usize = 64 * 1024;

#[derive(Default)]
pub struct PiState(Mutex<Option<PiProcess>>);

struct PiProcess {
    _child: Child,
    input: ChildStdin,
    events: mpsc::Receiver<Value>,
    reader: JoinHandle<()>,
    ready: bool,
    session_id: String,
    active: Option<String>,
}

impl Drop for PiProcess {
    fn drop(&mut self) {
        self.reader.abort();
        // The Node child has kill_on_drop enabled. Durable scientific jobs
        // are not claimed cancelled by a worker disconnect.
    }
}

fn configured_path(key: &str, file: bool) -> Result<PathBuf, String> {
    let path = std::env::var_os(key).map(PathBuf::from)
        .ok_or_else(|| format!("Missing Pi development configuration: {key}"))?;
    if !path.is_absolute() || (if file { !path.is_file() } else { !path.is_dir() }) {
        return Err(format!("Invalid Pi development configuration: {key}"));
    }
    Ok(path)
}

fn allowed_env(name: &str) -> bool {
    matches!(name, "PATH" | "HOME" | "USERPROFILE" | "SYSTEMROOT" | "WINDIR" |
        "TEMP" | "TMP" | "LOCALAPPDATA" | "APPDATA" | "LANG" | "LC_ALL" |
        "LD_LIBRARY_PATH" | "COMSPEC" | "PATHEXT" | "GRIDAGENT_NATIVE_PYTHON" |
        "GRIDAGENT_NATIVE_WORKSPACE" | "GRIDAGENT_SANDBOX_RUNTIME" |
        "GRIDAGENT_PLUGIN_ROOT" | "GRIDAGENT_NATIVE_TASKS" |
        "GRIDAGENT_PI_PROVIDER" | "GRIDAGENT_PI_MODEL" | "GRIDAGENT_PI_API_KEY")
}

fn valid_id(id: &str) -> bool {
    id.len() == 32 && id.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}

// Reconstruct every public event. Never forward unknown fields or raw provider data.
fn public_event(value: Value) -> Option<Value> {
    let kind = value["kind"].as_str()?;
    if kind == "ready" {
        return (value["version"].as_u64() == Some(1)).then(|| json!({"kind": "ready", "version": 1}));
    }
    let id = value["id"].as_str()?;
    if !valid_id(id) { return None; }
    match kind {
        "started" | "finished" | "settled" | "rejected" => Some(json!({"kind": kind, "id": id})),
        "text" => Some(json!({"kind": kind, "id": id, "delta": value["delta"].as_str()?})),
        "error" => {
            let code = value["code"].as_str()?;
            if !matches!(code, "agent_failure" | "provider_error") { return None; }
            Some(json!({"kind": kind, "id": id, "code": code}))
        }
        "tool_started" | "tool_finished" => {
            let tool_id = value["tool_id"].as_str()?;
            let name = value["name"].as_str()?;
            if tool_id.is_empty() || tool_id.len() > 512 || name.is_empty() || name.len() > 128 {
                return None;
            }
            let mut event = json!({"kind": kind, "id": id, "tool_id": tool_id, "name": name});
            if kind == "tool_finished" { event["error"] = json!(value["error"].as_bool()?); }
            Some(event)
        }
        _ => None,
    }
}

impl PiProcess {
    fn start() -> Result<Self, String> {
        if !cfg!(debug_assertions) || std::env::var("GRIDAGENT_PI_DEV").as_deref() != Ok("1") {
            return Err("Embedded Pi bridge requires explicit development opt-in".into());
        }
        let node = configured_path("GRIDAGENT_PI_NODE", true)?;
        let worker = configured_path("GRIDAGENT_PI_WORKER", true)?;
        configured_path("GRIDAGENT_NATIVE_PYTHON", true)?;
        configured_path("GRIDAGENT_NATIVE_WORKSPACE", false)?;
        let cwd = worker.parent().ok_or("Invalid worker directory")?;
        let mut command = Command::new(node);
        command.arg(&worker).current_dir(cwd).env_clear()
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null())
            .kill_on_drop(true);
        for (key, value) in std::env::vars_os() {
            if allowed_env(&key.to_string_lossy().to_ascii_uppercase()) { command.env(key, value); }
        }
        let mut child = command.spawn().map_err(|_| "Cannot start embedded Pi worker")?;
        let input = child.stdin.take().ok_or("Pi stdin unavailable")?;
        let mut output = BufReader::new(child.stdout.take().ok_or("Pi stdout unavailable")?);
        let (send, events) = mpsc::channel(256);
        let reader = tokio::spawn(async move {
            loop {
                let mut line = Vec::new();
                let mut bounded = (&mut output).take(MAX_FRAME as u64 + 1);
                let result = bounded.read_until(b'\n', &mut line).await;
                if result.is_err() || line.last() != Some(&b'\n') || line.len() > MAX_FRAME {
                    break;
                }
                let Some(event) = serde_json::from_slice(&line).ok().and_then(public_event) else {
                    break;
                };
                if send.send(event).await.is_err() { break; }
            }
        });
        Ok(Self { _child: child, input, events, reader, ready: false, session_id: uuid::Uuid::new_v4().simple().to_string(), active: None })
    }

    async fn send(&mut self, frame: Value) -> Result<(), String> {
        let mut bytes = serde_json::to_vec(&frame).map_err(|_| "Invalid Pi request")?;
        bytes.push(b'\n');
        if bytes.len() > MAX_FRAME { return Err("Pi request exceeds limit".into()); }
        timeout(Duration::from_secs(5), async {
            self.input.write_all(&bytes).await?;
            self.input.flush().await
        }).await.map_err(|_| "Pi write timed out")?
            .map_err(|_| "Pi write failed".to_string())
    }
}

#[tauri::command]
pub async fn pi_open(state: State<'_, PiState>) -> Result<String, String> {
    let mut guard = state.0.lock().await;
    if guard.is_some() { return Err("Pi session already open".into()); }
    let process = PiProcess::start()?;
    let id = process.session_id.clone();
    *guard = Some(process);
    Ok(id)
}

#[tauri::command]
pub async fn pi_prompt(state: State<'_, PiState>, session_id: String, text: String) -> Result<String, String> {
    if text.trim().is_empty() || text.len() > MAX_FRAME / 8 {
        return Err("Pi prompt is empty or exceeds limit".into());
    }
    let mut guard = state.0.lock().await;
    if guard.as_ref().map(|p| p.session_id.as_str()) != Some(session_id.as_str()) {
        return Err("No matching Pi session".into());
    }
    let mut process = guard.take().ok_or("No open Pi session")?;
    if !process.ready || process.active.is_some() {
        *guard = Some(process);
        return Err("Pi session not ready or busy".into());
    }
    let id = uuid::Uuid::new_v4().simple().to_string();
    // On failed/uncertain send the process is discarded; never replay the prompt.
    process.send(json!({"method": "prompt", "id": id, "text": text})).await?;
    process.active = Some(id.clone());
    *guard = Some(process);
    Ok(id)
}

#[tauri::command]
pub async fn pi_abort(state: State<'_, PiState>, session_id: String, id: String) -> Result<(), String> {
    let mut guard = state.0.lock().await;
    if guard.as_ref().map(|p| p.session_id.as_str()) != Some(session_id.as_str()) {
        return Err("No matching Pi session".into());
    }
    let mut process = guard.take().ok_or("No open Pi session")?;
    if process.active.as_deref() != Some(id.as_str()) {
        *guard = Some(process);
        return Err("No matching active Pi prompt".into());
    }
    process.send(json!({"method": "abort", "id": id})).await?;
    *guard = Some(process);
    Ok(())
}

#[tauri::command]
pub async fn pi_poll(state: State<'_, PiState>, session_id: String) -> Result<Vec<Value>, String> {
    let mut guard = state.0.lock().await;
    if guard.as_ref().map(|p| p.session_id.as_str()) != Some(session_id.as_str()) {
        return Err("No matching Pi session".into());
    }
    let mut process = guard.take().ok_or("No open Pi session")?;
    let mut batch = Vec::new();
    // Polling is nonblocking so it cannot hold the lock while waiting for abort.
    for _ in 0..64 {
        match process.events.try_recv() {
            Ok(event) => {
                if event["kind"] == "ready" {
                    if process.ready { return Err("Duplicate Pi ready event".into()); }
                    process.ready = true;
                } else {
                    if event["id"].as_str() != process.active.as_deref() || !process.ready {
                        return Err("Pi event correlation failed; session discarded".into());
                    }
                    if event["kind"] == "settled" {
                        process.active = None;
                    }
                }
                batch.push(event);
            }
            Err(mpsc::error::TryRecvError::Empty) => break,
            Err(mpsc::error::TryRecvError::Disconnected) => {
                if batch.is_empty() { return Err("Pi worker disconnected; operation not replayed".into()); }
                break;
            }
        }
    }
    *guard = Some(process);
    Ok(batch)
}

#[tauri::command]
pub async fn pi_close(state: State<'_, PiState>, session_id: String) -> Result<(), String> {
    let mut guard = state.0.lock().await;
    if guard.as_ref().map(|p| p.session_id.as_str()) != Some(session_id.as_str()) {
        return Err("No matching Pi session".into());
    }
    if guard.as_ref().is_some_and(|p| p.active.is_some()) {
        return Err("Abort the active Pi prompt and wait for settlement before closing".into());
    }
    *guard = None;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_private_events_and_preserves_distinct_ids() {
        let id = "a".repeat(32);
        assert!(public_event(json!({"kind": "thinking", "id": id})).is_none());
        assert!(public_event(json!({"kind": "text", "id": "bad", "delta": "x"})).is_none());
        let value = public_event(json!({"kind": "tool_started", "id": id,
            "tool_id": "call-1", "name": "read", "args": {"secret": "x"}})).unwrap();
        assert_eq!(value, json!({"kind": "tool_started", "id": id, "tool_id": "call-1", "name": "read"}));
    }

    #[test]
    fn excludes_unrelated_credentials_and_execution_overrides() {
        assert!(!allowed_env("OPENAI_API_KEY"));
        assert!(!allowed_env("NODE_OPTIONS"));
        assert!(!allowed_env("PYTHONPATH"));
        assert!(allowed_env("GRIDAGENT_PI_API_KEY"));
    }
}
