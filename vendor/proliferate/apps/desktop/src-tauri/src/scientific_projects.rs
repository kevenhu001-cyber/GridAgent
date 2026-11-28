//! Host-owned registry of explicitly selected local scientific project roots.
//! The renderer can list projects and ask the OS picker to add one, but cannot
//! register an arbitrary path by invoking a generic filesystem API.
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};

const MAX_PROJECTS: usize = 32;
const MAX_RECORD_BYTES: u64 = 4096;
const REGISTRY_NAME: &str = "gridagent-scientific-workspaces-v1";

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectIdentity {
    pub id: String,
    pub workspace_path: String,
    pub project_path: String,
    pub available: bool,
    pub created_at: String,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Record {
    version: u32,
    workspace_path: String,
    created_at: String,
}

pub fn id_for_path(path: &Path) -> String {
    format!("gridagent-scientific:{:x}", Sha256::digest(path.as_os_str().as_encoded_bytes()))
}

fn record_path(directory: &Path, id: &str) -> Result<PathBuf, String> {
    let hash = id.strip_prefix("gridagent-scientific:")
        .ok_or("Invalid scientific project ID")?;
    if hash.len() != 64 || !hash.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
        return Err("Invalid scientific project ID".into());
    }
    Ok(directory.join(format!("{hash}.json")))
}

fn registry_directory() -> Result<PathBuf, String> {
    let app = crate::app_config::app_dir_path()?;
    fs::create_dir_all(&app).map_err(|_| "Cannot create GridAgent application data directory")?;
    let directory = app.join(REGISTRY_NAME);
    fs::create_dir_all(&directory).map_err(|_| "Cannot create scientific project registry")?;
    directory.canonicalize().map_err(|_| "Cannot resolve scientific project registry".to_string())
}

fn lock_registry(directory: &Path, exclusive: bool) -> Result<std::fs::File, String> {
    let lock = OpenOptions::new().read(true).write(true).create(true).truncate(false)
        .open(directory.join(".lock")).map_err(|_| "Cannot open scientific project registry lock")?;
    if exclusive { lock.lock_exclusive() } else { lock.lock_shared() }
        .map_err(|_| "Cannot lock scientific project registry")?;
    Ok(lock)
}

fn read_record(directory: &Path, id: &str) -> Result<Record, String> {
    let path = record_path(directory, id)?;
    let metadata = fs::metadata(&path).map_err(|_| "Scientific project is not registered")?;
    if !metadata.is_file() || metadata.len() > MAX_RECORD_BYTES {
        return Err("Invalid scientific project registry record".into());
    }
    let bytes = fs::read(path).map_err(|_| "Cannot read scientific project registry")?;
    let record: Record = serde_json::from_slice(&bytes)
        .map_err(|_| "Invalid scientific project registry record")?;
    let root = PathBuf::from(&record.workspace_path);
    if record.version != 1 || !root.is_absolute() || id_for_path(&root) != id {
        return Err("Scientific project registry identity mismatch".into());
    }
    Ok(record)
}

fn identity(path: &Path, created_at: String, available: bool) -> Result<ProjectIdentity, String> {
    let workspace_path = path.to_str().ok_or("Project path is not valid UTF-8")?.to_owned();
    let project_path = path.join("scientific-project").to_str()
        .ok_or("Project path is not valid UTF-8")?.to_owned();
    Ok(ProjectIdentity { id: id_for_path(path), workspace_path, project_path, available, created_at })
}

fn list_in(directory: &Path) -> Result<Vec<ProjectIdentity>, String> {
    if !directory.exists() { return Ok(Vec::new()); }
    let mut rows = Vec::new();
    for entry in fs::read_dir(directory).map_err(|_| "Cannot read scientific project registry")? {
        let entry = entry.map_err(|_| "Cannot read scientific project registry entry")?;
        if entry.path().extension().and_then(|s| s.to_str()) != Some("json") { continue; }
        let entry_path = entry.path();
        let hash = entry_path.file_stem().and_then(|s| s.to_str())
            .ok_or("Invalid scientific project registry filename")?;
        let id = format!("gridagent-scientific:{hash}");
        let record = read_record(directory, &id)?;
        let root = PathBuf::from(&record.workspace_path);
        let available = root.is_dir() && root.canonicalize().is_ok_and(|resolved| resolved == root);
        rows.push(identity(&root, record.created_at, available)?);
        if rows.len() > MAX_PROJECTS { return Err("Scientific project registry limit exceeded".into()); }
    }
    for (index, row) in rows.iter().enumerate() {
        let root = PathBuf::from(&row.workspace_path);
        for other in rows.iter().skip(index + 1) {
            let other_root = PathBuf::from(&other.workspace_path);
            if root.starts_with(&other_root) || other_root.starts_with(&root) {
                return Err("Overlapping scientific project roots are not supported".into());
            }
        }
    }
    rows.sort_by(|a, b| a.workspace_path.to_lowercase().cmp(&b.workspace_path.to_lowercase()));
    Ok(rows)
}

fn register_in(directory: &Path, selected: &Path) -> Result<ProjectIdentity, String> {
    let root = selected.canonicalize().map_err(|_| "Selected project folder is unavailable")?;
    if !root.is_dir() { return Err("Select an existing project folder".into()); }
    let workspace_path = root.to_str().ok_or("Project path is not valid UTF-8")?.to_owned();
    let id = id_for_path(&root);
    let existing = list_in(directory)?;
    if existing.iter().any(|row| {
        let other = PathBuf::from(&row.workspace_path);
        row.id != id && (root.starts_with(&other) || other.starts_with(&root))
    }) {
        return Err("Overlapping scientific project roots are not supported".into());
    }
    let file_path = record_path(directory, &id)?;
    if file_path.exists() {
        let record = read_record(directory, &id)?;
        if record.workspace_path != workspace_path { return Err("Scientific project identity collision".into()); }
        return identity(&root, record.created_at, true);
    }
    if existing.len() >= MAX_PROJECTS {
        return Err("The local scientific project limit has been reached".into());
    }
    let record = Record { version: 1, workspace_path: workspace_path.clone(), created_at: chrono::Utc::now().to_rfc3339() };
    let bytes = serde_json::to_vec(&record).map_err(|_| "Cannot encode project registration")?;
    let mut file = match OpenOptions::new().write(true).create_new(true).open(&file_path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            let existing = read_record(directory, &id)?;
            if existing.workspace_path != workspace_path { return Err("Scientific project identity collision".into()); }
            return identity(&root, existing.created_at, true);
        }
        Err(_) => return Err("Cannot register scientific project".into()),
    };
    if file.write_all(&bytes).and_then(|_| file.sync_all()).is_err() {
        let _ = fs::remove_file(&file_path);
        return Err("Cannot persist scientific project registration".into());
    }
    identity(&root, record.created_at, true)
}

fn resolve_in(directory: &Path, id: &str) -> Result<PathBuf, String> {
    let record = read_record(directory, id)?;
    let root = PathBuf::from(record.workspace_path);
    if !root.is_dir() { return Err("Registered project folder is missing".into()); }
    let canonical = root.canonicalize().map_err(|_| "Registered project folder is unavailable")?;
    if canonical != root || id_for_path(&canonical) != id {
        return Err("Registered project folder identity changed".into());
    }
    Ok(canonical)
}

fn configured_legacy_path() -> Option<PathBuf> {
    if !cfg!(debug_assertions) || std::env::var("GRIDAGENT_PI_DEV").ok().as_deref() != Some("1") { return None; }
    let path = PathBuf::from(std::env::var_os("GRIDAGENT_NATIVE_WORKSPACE")?);
    if !path.is_absolute() { return None; }
    let canonical = path.canonicalize().ok()?;
    if !canonical.is_dir() { return None; }
    let app = crate::app_config::app_dir_path().ok()?.canonicalize().ok()?;
    if app.starts_with(&canonical) || canonical.starts_with(&app) { return None; }
    Some(canonical)
}

pub fn list() -> Result<Vec<ProjectIdentity>, String> {
    let directory = registry_directory()?;
    let lock = lock_registry(&directory, false)?;
    let mut rows = list_in(&directory)?;
    drop(lock);
    if let Some(root) = configured_legacy_path() {
        let id = id_for_path(&root);
        if !rows.iter().any(|row| row.id == id) {
            rows.push(identity(&root, "1970-01-01T00:00:00Z".into(), true)?);
        }
    }
    for (index, row) in rows.iter().enumerate() {
        let root = PathBuf::from(&row.workspace_path);
        for other in rows.iter().skip(index + 1) {
            let other_root = PathBuf::from(&other.workspace_path);
            if root.starts_with(&other_root) || other_root.starts_with(&root) {
                return Err("Overlapping scientific project roots are not supported".into());
            }
        }
    }
    rows.sort_by(|a, b| a.workspace_path.to_lowercase().cmp(&b.workspace_path.to_lowercase()));
    if rows.len() > MAX_PROJECTS { return Err("Scientific project registry limit exceeded".into()); }
    Ok(rows)
}

/// Register only a path returned by the native OS folder picker.
pub fn register(selected: PathBuf) -> Result<ProjectIdentity, String> {
    let directory = registry_directory()?;
    let root = selected.canonicalize().map_err(|_| "Selected project folder is unavailable")?;
    let app = crate::app_config::app_dir_path()?.canonicalize()
        .map_err(|_| "Cannot resolve GridAgent application data directory")?;
    if app.starts_with(&root) || root.starts_with(&app) {
        return Err("Choose a project folder that does not contain GridAgent application data".into());
    }
    let existing = list_in(&directory)?;
    let id = id_for_path(&root);
    let legacy_extra = configured_legacy_path().is_some_and(|legacy| {
        id_for_path(&legacy) != id && !existing.iter().any(|row| row.id == id_for_path(&legacy))
    });
    let legacy_count = if legacy_extra { 1 } else { 0 };
    if !existing.iter().any(|row| row.id == id) && existing.len() + legacy_count >= MAX_PROJECTS {
        return Err("The local scientific project limit has been reached".into());
    }
    if let Some(legacy) = configured_legacy_path() {
        if legacy != root && (legacy.starts_with(&root) || root.starts_with(&legacy)) {
            return Err("Overlapping scientific project roots are not supported".into());
        }
    }
    let lock = lock_registry(&directory, true)?;
    let result = register_in(&directory, &root);
    drop(lock);
    result
}

pub fn resolve_id(id: &str) -> Result<PathBuf, String> {
    let project = list()?.into_iter().find(|project| project.id == id && project.available)
        .ok_or("Scientific project is not registered or its folder is missing")?;
    let root = PathBuf::from(project.workspace_path);
    let canonical = root.canonicalize().map_err(|_| "Scientific project folder is unavailable")?;
    if canonical != root || id_for_path(&canonical) != id {
        return Err("Scientific project identity changed".into());
    }
    Ok(canonical)
}

pub fn resolve_path(path: &str) -> Option<PathBuf> {
    let selected = PathBuf::from(path);
    if !selected.is_absolute() { return None; }
    let canonical = selected.canonicalize().ok()?;
    let root = resolve_id(&id_for_path(&canonical)).ok()?;
    (root == canonical).then_some(root)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> PathBuf {
        let root = std::env::temp_dir().join(format!("gridagent-project-registry-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        root
    }

    #[test]
    fn persists_multiple_canonical_roots_and_resolves_only_registered_ids() {
        let base = fixture();
        let registry = base.join("registry");
        let first = base.join("first");
        let second = base.join("second");
        fs::create_dir(&registry).unwrap();
        fs::create_dir(&first).unwrap();
        fs::create_dir(&second).unwrap();
        let a = register_in(&registry, &first).unwrap();
        let b = register_in(&registry, &second).unwrap();
        assert_ne!(a.id, b.id);
        assert_eq!(list_in(&registry).unwrap().len(), 2);
        assert_eq!(resolve_in(&registry, &a.id).unwrap(), first.canonicalize().unwrap());
        assert_eq!(register_in(&registry, &first).unwrap().id, a.id);
        let nested = first.join("nested");
        fs::create_dir(&nested).unwrap();
        assert!(register_in(&registry, &nested).is_err());
        assert!(resolve_in(&registry, "gridagent-scientific:legacy").is_err());
        fs::remove_dir_all(&first).unwrap();
        assert!(resolve_in(&registry, &a.id).is_err());
        assert!(list_in(&registry).unwrap().iter().any(|row| row.id == a.id && !row.available));
        fs::remove_dir_all(base).unwrap();
    }
}
