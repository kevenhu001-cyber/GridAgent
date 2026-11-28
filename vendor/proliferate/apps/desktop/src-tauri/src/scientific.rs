//! Desktop-owned persistent IPC to the GridAgent scientific core.
//! The default lane is read-only. Mutations require explicit debug-host opt-in.
//! No model or renderer supplies an executable or root.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{collections::HashMap, path::PathBuf, process::Stdio, time::{Duration, Instant}};
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
pub struct ScientificState(Mutex<HashMap<PathBuf, ScientificProcess>>);

struct ScientificProcess {
    _child: Child,
    root: PathBuf,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
    last_used: Instant,
}

fn configured_path(key: &str, file: bool) -> Result<PathBuf, String> {
    let path = std::env::var_os(key).map(PathBuf::from)
        .ok_or_else(|| format!("Scientific development configuration missing: {key}"))?;
    if !path.is_absolute() || (if file { !path.is_file() } else { !path.is_dir() }) {
        return Err(format!("Invalid scientific development configuration: {key}"));
    }
    // Keep the selected interpreter path: resolving a venv Python symlink can
    // bypass the virtual environment. Canonicalize the workspace only.
    if file { Ok(path) } else {
        path.canonicalize().map_err(|_| "Cannot resolve scientific configuration".to_string())
    }
}

fn python_parent() -> Result<PathBuf, String> {
    configured_path("GRIDAGENT_NATIVE_PYTHON", true)?
        .parent().map(PathBuf::from).ok_or("Invalid interpreter directory".into())
}

fn developer_tasks_enabled() -> bool {
    cfg!(debug_assertions) && std::env::var("GRIDAGENT_NATIVE_TASKS").as_deref() == Ok("1")
}

impl ScientificProcess {
    fn start(root: PathBuf) -> Result<Self, String> {
        // Development-only host configuration. Packaged runtime discovery and
        // user-authorized workspace selection replace this in the next phase.
        let python = configured_path("GRIDAGENT_NATIVE_PYTHON", true)?;
        let mut command = Command::new(python);
        command.args(["-I", "-X", "utf8", "-m", "gridagent.native_service"])
            .arg(&root).current_dir(python_parent()?)
            .env_clear().env("PYTHONNOUSERSITE", "1")
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null())
            .kill_on_drop(true);
        for (key, value) in std::env::vars_os() {
            let name = key.to_string_lossy().to_ascii_uppercase();
            if matches!(name.as_str(), "PATH" | "HOME" | "USERPROFILE" | "SYSTEMROOT" |
                "WINDIR" | "TEMP" | "TMP" | "LOCALAPPDATA" | "APPDATA" | "LANG" |
                "LC_ALL" | "LD_LIBRARY_PATH" | "COMSPEC" | "PATHEXT" |
                "GRIDAGENT_SANDBOX_RUNTIME" | "GRIDAGENT_PLUGIN_ROOT") {
                command.env(key, value);
            }
        }
        if developer_tasks_enabled() {
            command.arg("--tasks");
        }
        let mut child = command.spawn().map_err(|_| "Cannot start scientific service".to_string())?;
        let input = child.stdin.take().ok_or("Scientific stdin unavailable")?;
        let output = BufReader::new(child.stdout.take().ok_or("Scientific stdout unavailable")?);
        Ok(Self { _child: child, root, input, output, last_used: Instant::now() })
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
        "scientific.artifact" | "solver.backends" | "solver.table" | "workspace.files" |
        "workspace.read" | "workspace.tree" | "workspace.search" | "workspace.inspect" |
        "job.status" | "job.latest") {
        return Err("Unknown or non-read scientific operation".into());
    }
    exchange(&state, &method, params).await
}

#[tauri::command]
pub async fn scientific_task(
    state: State<'_, ScientificState>, method: String, params: Value,
) -> Result<Value, String> {
    if !developer_tasks_enabled() {
        return Err("Scientific task control is disabled outside explicit development opt-in".into());
    }
    if !matches!(method.as_str(), "workspace.write" | "job.submit" | "job.cancel") {
        return Err("Unknown scientific task operation".into());
    }
    exchange(&state, &method, params).await
}

async fn exchange(state: &ScientificState, method: &str, params: Value) -> Result<Value, String> {
    let root = configured_path("GRIDAGENT_NATIVE_WORKSPACE", false)?;
    exchange_at(state, &root, method, params).await
}

async fn exchange_at(state: &ScientificState, root: &std::path::Path, method: &str, params: Value) -> Result<Value, String> {
    const MAX_IDLE_PROJECT_SERVICES: usize = 4;
    let mut guard = state.0.lock().await;
    // Requests are serialized. A worker removed from the map is the only one
    // in flight; idle services are safely evicted by least-recent use.
    let mut process = match guard.remove(root) {
        Some(process) => process,
        None => {
            if guard.len() >= MAX_IDLE_PROJECT_SERVICES {
                if let Some(oldest) = guard.iter().min_by_key(|(_, worker)| worker.last_used)
                    .map(|(path, _)| path.clone()) {
                    guard.remove(&oldest);
                }
            }
            ScientificProcess::start(root.to_path_buf())?
        }
    };
    match timeout(Duration::from_secs(30), process.request(method, params)).await {
        Ok(Ok(response)) => {
            process.last_used = Instant::now();
            guard.insert(root.to_path_buf(), process);
            Ok(response)
        }
        Ok(Err(error)) => Err(error),
        Err(_) => Err("Scientific request timed out; connection discarded".into()),
    }
}


// Native project IDs deliberately do not collide with repository/AnyHarness
// workspace IDs. Relative paths address scientific-project, not its parent.
fn project_id(root: &std::path::Path) -> String {
    crate::scientific_projects::id_for_path(root)
}

fn bound_project(root: &std::path::Path, id: &str) -> Result<(), String> {
    if id != project_id(root) {
        return Err("Scientific project identity mismatch".into());
    }
    Ok(())
}

fn project_root(id: &str) -> Result<PathBuf, String> {
    if !crate::pi_bridge::pi_enabled() {
        return Err("Native project development mode is disabled".into());
    }
    let root = crate::scientific_projects::resolve_id(id)?;
    if project_id(&root) != id { return Err("Scientific project identity mismatch".into()); }
    Ok(root)
}

#[tauri::command]
pub fn scientific_project_list() -> Result<Vec<crate::scientific_projects::ProjectIdentity>, String> {
    if !crate::pi_bridge::pi_enabled() {
        return Err("Native project development mode is disabled".into());
    }
    crate::scientific_projects::list()
}

#[tauri::command]
pub async fn scientific_project_add_from_picker() -> Result<Option<crate::scientific_projects::ProjectIdentity>, String> {
    if !crate::pi_bridge::pi_enabled() {
        return Err("Native project development mode is disabled".into());
    }
    let selected = tokio::task::spawn_blocking(|| {
        rfd::FileDialog::new().set_title("Open GridAgent Project").pick_folder()
    }).await.map_err(|_| "Project folder picker failed")?;
    match selected {
        Some(path) => crate::scientific_projects::register(path).map(Some),
        None => Ok(None),
    }
}

#[tauri::command]
pub async fn scientific_project_read(
    state: State<'_, ScientificState>, project_id: String, method: String, params: Value,
) -> Result<Value, String> {
    let root = project_root(&project_id)?;
    bound_project(&root, &project_id)?;
    if !matches!(method.as_str(), "workspace.tree" | "workspace.search" |
        "workspace.inspect" | "workspace.read") {
        return Err("Unknown native project read operation".into());
    }
    exchange_at(&state, &root, &method, params).await
}

#[tauri::command]
pub async fn scientific_project_write(
    state: State<'_, ScientificState>, project_id: String, path: String,
    text: String, expected_sha256: String,
) -> Result<Value, String> {
    let root = project_root(&project_id)?;
    bound_project(&root, &project_id)?;
    if !developer_tasks_enabled() {
        return Err("Scientific project writing requires explicit development opt-in".into());
    }
    if expected_sha256.len() != 64 ||
        !expected_sha256.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
        return Err("A valid observed file revision is required".into());
    }
    exchange_at(&state, &root, "workspace.write",
        json!({"path":path,"text":text,"expected_sha256":expected_sha256})).await
}

#[tauri::command]
pub async fn scientific_project_mutate(
    state: State<'_, ScientificState>, project_id: String, method: String, params: Value,
) -> Result<Value, String> {
    let root = project_root(&project_id)?;
    bound_project(&root, &project_id)?;
    if !developer_tasks_enabled() {
        return Err("Scientific project mutation requires explicit development opt-in".into());
    }
    if !matches!(method.as_str(), "workspace.create" | "workspace.rename" | "workspace.delete") {
        return Err("Unknown native project mutation".into());
    }
    exchange_at(&state, &root, &method, params).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_project_identity_is_stable_and_bound_to_root() {
        let first = PathBuf::from("workspace-a");
        let second = PathBuf::from("workspace-b");
        let id = project_id(&first);
        assert!(id.starts_with("gridagent-scientific:"));
        assert_eq!(id, project_id(&first));
        assert_ne!(id, project_id(&second));
        assert!(bound_project(&first, &id).is_ok());
        assert!(bound_project(&second, &id).is_err());
        assert!(bound_project(&first, "legacy-workspace-id").is_err());
    }
}
