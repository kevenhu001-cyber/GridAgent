//! Native provider credential slots. Reuse the existing serialized keyring worker.
//! Do not use the legacy env-secrets JSON file or return a secret to the renderer.
use crate::{commands::keychain, pi_bridge::pi_enabled};
use serde::Serialize;

const SERVICE: &str = "com.topodrive.gridagent.pi";
const PROVIDERS: [&str; 3] = ["openai", "anthropic", "google"];

pub(crate) fn validate_provider(provider: &str) -> Result<(), String> {
    if PROVIDERS.contains(&provider) { Ok(()) }
    else { Err("Unsupported Pi model provider".into()) }
}

fn secure_backend_available() -> bool {
    cfg!(any(target_os = "windows", target_os = "macos"))
}

fn require_secure_backend() -> Result<(), String> {
    if secure_backend_available() { Ok(()) }
    else { Err("Native credential storage is unavailable on this platform".into()) }
}

fn require_mode() -> Result<(), String> {
    if !pi_enabled() { return Err("Native Pi development mode is disabled".into()); }
    require_secure_backend()
}

pub(crate) fn read_provider_key(provider: &str) -> Result<Option<String>, String> {
    validate_provider(provider)?;
    // No mock keyring fallback on unsupported platforms.
    if !secure_backend_available() { return Ok(None); }
    keychain::read_password(SERVICE, provider).map_err(|_| "Cannot read native provider credential".into())
}

#[derive(Serialize)]
pub struct PiCredentialStatus {
    provider: String,
    configured: bool,
}

fn validate_key(value: &str) -> Result<(), String> {
    if value.trim() != value || value.is_empty() || value.len() > 2048 || value.chars().any(char::is_control) {
        return Err("Invalid provider credential".into());
    }
    Ok(())
}

#[tauri::command]
pub async fn pi_list_credentials() -> Result<Vec<PiCredentialStatus>, String> {
    require_mode()?;
    tauri::async_runtime::spawn_blocking(|| {
        PROVIDERS.iter().map(|provider| Ok(PiCredentialStatus {
            provider: provider.to_string(),
            configured: read_provider_key(provider)?.is_some(),
        })).collect::<Result<Vec<_>, String>>()
    }).await.map_err(|_| "Credential worker unavailable".to_string())?
}

#[tauri::command]
pub async fn pi_save_credential(provider: String, value: String) -> Result<(), String> {
    require_mode()?;
    validate_provider(&provider)?;
    validate_key(&value)?;
    tauri::async_runtime::spawn_blocking(move || {
        keychain::set_password(SERVICE, &provider, &value).map_err(|_| "Cannot save native provider credential".into())
    }).await.map_err(|_| "Credential worker unavailable".to_string())?
}

#[tauri::command]
pub async fn pi_delete_credential(provider: String) -> Result<(), String> {
    require_mode()?;
    validate_provider(&provider)?;
    tauri::async_runtime::spawn_blocking(move || {
        keychain::delete_password(SERVICE, &provider).map_err(|_| "Cannot delete native provider credential".into())
    }).await.map_err(|_| "Credential worker unavailable".to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_arbitrary_accounts_and_invalid_values() {
        assert!(validate_provider("openai").is_ok());
        assert!(validate_provider("anyharness_data_key").is_err());
        assert!(validate_key("dummy-test-key").is_ok());
        assert!(validate_key(" ").is_err());
        assert!(validate_key("line\nkey").is_err());
        assert!(validate_key(&"x".repeat(2049)).is_err());
    }
}
