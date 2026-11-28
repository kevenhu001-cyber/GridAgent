//! Host-owned installed runtime. Release builds never resolve interpreters from PATH.
use std::{path::{Path, PathBuf}, sync::OnceLock};
static ROOT: OnceLock<PathBuf> = OnceLock::new();

pub(crate) fn packaged_build() -> bool {
    cfg!(all(windows, not(debug_assertions))) && option_env!("GRIDAGENT_PACKAGED_BUILD") == Some("1")
}
pub(crate) fn developer_mode() -> bool {
    cfg!(debug_assertions) && std::env::var("GRIDAGENT_PI_DEV").as_deref() == Ok("1")
}
const REQUIRED: &[&str] = &[
    "node/node.exe", "pi/worker.mjs", "pi/model-catalog-cli.mjs",
    "pi/node_modules/@earendil-works/pi-agent-core/package.json",
    "python/python.exe", "python/python311._pth",
    "python/Lib/site-packages/gridagent/native_service.py",
];
fn validate(root: &Path) -> Result<(), String> {
    let canonical = root.canonicalize().map_err(|_| "Installed GridAgent runtime is missing")?;
    for relative in REQUIRED {
        let file = root.join(relative);
        if !file.is_file() || !file.canonicalize().is_ok_and(|p| p.starts_with(&canonical)) {
            return Err(format!("Installed GridAgent runtime is incomplete: {relative}"));
        }
    }
    Ok(())
}
pub(crate) fn initialize(resource_dir: &Path) -> Result<(), String> {
    if !packaged_build() { return Ok(()); }
    let root = resource_dir.join("gridagent-runtime");
    validate(&root)?;
    ROOT.set(root).map_err(|_| "Runtime already initialized".into())
}
pub(crate) fn ready() -> bool { ROOT.get().is_some() }
pub(crate) fn path(key: &str, file: bool) -> Result<PathBuf, String> {
    let path = if let Some(root) = ROOT.get() {
        let relative = match key {
            "GRIDAGENT_PI_NODE" => "node/node.exe",
            "GRIDAGENT_PI_WORKER" => "pi/worker.mjs",
            "GRIDAGENT_NATIVE_PYTHON" => "python/python.exe",
            _ => return Err("Unsupported installed runtime path".into()),
        };
        let path = root.join(relative);
        let canonical = root.canonicalize().map_err(|_| "Installed runtime is unavailable")?;
        if !path.canonicalize().is_ok_and(|p| p.starts_with(&canonical)) {
            return Err("Installed runtime path escaped resource directory".into());
        }
        path
    } else if cfg!(debug_assertions) {
        std::env::var_os(key).map(PathBuf::from)
            .ok_or_else(|| format!("Missing development configuration: {key}"))?
    } else { return Err("Installed GridAgent runtime is unavailable".into()); };
    if !path.is_absolute() || (if file { !path.is_file() } else { !path.is_dir() }) {
        return Err(format!("Invalid runtime configuration: {key}"));
    }
    Ok(path)
}
pub(crate) fn overlaps_installation(project: &Path) -> bool {
    ROOT.get().and_then(|root| root.parent())
        .and_then(|root| root.canonicalize().ok())
        .is_some_and(|root| project.starts_with(&root) || root.starts_with(project))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_incomplete_installed_runtime() {
        let root = std::env::temp_dir().join(format!("gridagent-runtime-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        assert!(validate(&root).is_err());
        for relative in REQUIRED {
            let p = root.join(relative);
            std::fs::create_dir_all(p.parent().unwrap()).unwrap();
            std::fs::write(p, b"fixture").unwrap();
        }
        assert!(validate(&root).is_ok());
        std::fs::remove_file(root.join("pi/worker.mjs")).unwrap();
        assert!(validate(&root).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
