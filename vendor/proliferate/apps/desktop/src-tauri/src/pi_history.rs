//! Private, versioned Pi transport journal. The renderer rebuilds the existing
//! transcript from public events. No worker context or delivery queue lives here.
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    io::{ErrorKind, Read},
    path::{Path, PathBuf},
};
use tokio::{fs::OpenOptions, io::AsyncWriteExt};

const VERSION: u32 = 1;
const MAX_JOURNAL_BYTES: usize = 1024 * 1024;
const MAX_RECENT_SESSIONS: usize = 12;
const MAX_CONTEXT_BYTES: usize = 48 * 1024;
pub const MAX_TURN_EVENT_BYTES: usize = 256 * 1024;

#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Record {
    Header {
        version: u32,
        model_id: String,
        #[serde(default)]
        provider: Option<String>,
    },
    Submitted {
        id: String,
        text: String,
        timestamp: chrono::DateTime<chrono::Utc>,
    },
    Settled {
        id: String,
        events: Vec<Value>,
        cancellation_requested: bool,
        #[serde(default)]
        context_safe: bool,
    },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Turn {
    id: String,
    text: String,
    timestamp: chrono::DateTime<chrono::Utc>,
    events: Vec<Value>,
    cancellation_requested: bool,
    #[serde(skip)]
    context_safe: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Session {
    id: String,
    pub model_id: String,
    pub provider: Option<String>,
    #[serde(skip)]
    complete: bool,
    resume_revision: Option<String>,
    turns: Vec<Turn>,
}

#[derive(Default, Serialize)]
pub struct History {
    sessions: Vec<Session>,
    skipped: usize,
}

pub struct Journal {
    file: Option<tokio::fs::File>,
    _lock: Option<std::fs::File>,
    path: PathBuf,
    model_id: String,
    provider: Option<String>,
    bytes: usize,
}

// Resolve app-owned storage separately from the granted workspace, so the
// scientific/coding tools cannot read or modify the journal through that grant.
pub fn directory(app: &Path, workspace: &Path) -> Result<PathBuf, String> {
    let key = format!(
        "{:x}",
        Sha256::digest(workspace.as_os_str().as_encoded_bytes())
    );
    let dir = app.join("gridagent-pi-history-v1").join(key);
    if !app.is_absolute()
        || dir
            .ancestors()
            .find_map(|part| part.canonicalize().ok())
            .is_some_and(|part| part.starts_with(workspace))
    {
        return Err("Pi history must be outside the authorized workspace".into());
    }
    std::fs::create_dir_all(&dir).map_err(|_| "Cannot create Pi history directory")?;
    let resolved = dir
        .canonicalize()
        .map_err(|_| "Cannot resolve Pi history directory")?;
    if resolved.starts_with(workspace) {
        return Err("Pi history must be outside the authorized workspace".into());
    }
    Ok(resolved)
}

pub fn redact_events(events: &mut Vec<Value>, key: &str) -> bool {
    let text: String = events
        .iter()
        .filter_map(|event| event["delta"].as_str())
        .collect();
    let redact_text = text.contains(key);
    if redact_text {
        let mut first = true;
        for event in events.iter_mut().filter(|event| event["kind"] == "text") {
            event["delta"] = Value::String(if std::mem::take(&mut first) {
                "[redacted]".into()
            } else {
                String::new()
            });
        }
    }
    let count = events.len();
    events.retain(|event| {
        !(["tool_id", "name"].iter().any(|field| {
            event[*field]
                .as_str()
                .is_some_and(|value| value.contains(key))
        }))
    });
    redact_text || count != events.len()
}

fn lock(path: &Path) -> Result<std::fs::File, String> {
    let mut options = std::fs::OpenOptions::new();
    options.create(true).truncate(false).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options
        .open(path.with_extension("lock"))
        .map_err(|_| "Cannot open Pi journal lock")?;
    FileExt::try_lock_exclusive(&file).map_err(|_| "Pi session is already open")?;
    Ok(file)
}

impl Session {
    fn text_context(&self) -> Option<Value> {
        if !self.complete || self.provider.is_none() || self.turns.is_empty() {
            return None;
        }
        let turns = self
            .turns
            .iter()
            .map(|turn| {
                if !turn.context_safe || turn.cancellation_requested {
                    return None;
                }
                let assistant: String = turn
                    .events
                    .iter()
                    .filter_map(|event| event["delta"].as_str())
                    .collect();
                if assistant.trim().is_empty() {
                    return None;
                }
                Some(serde_json::json!({
                    "user": turn.text, "assistant": assistant,
                    "timestamp": turn.timestamp.timestamp_millis(),
                }))
            })
            .collect::<Option<Vec<_>>>()?;
        let frame = serde_json::json!({"method": "restore_text", "version": 1, "turns": turns});
        (serde_json::to_vec(&frame).ok()?.len() <= MAX_CONTEXT_BYTES).then_some(frame)
    }
}

// Only the host opens an existing journal, with a matching directory revision
// and an exclusive writer held for the lifetime of the worker.
pub fn resume(dir: &Path, id: &str, revision: &str) -> Result<(Session, Journal, Value), String> {
    if !crate::pi_bridge::valid_id(id) {
        return Err("Invalid Pi session ID".into());
    }
    let path = dir.join(format!("{id}.jsonl"));
    let info = path
        .symlink_metadata()
        .map_err(|_| "Pi session history unavailable")?;
    if !info.is_file() {
        return Err("Pi session history unavailable".into());
    }
    let writer = lock(&path)?;
    if dismissed_path(dir, id).exists() {
        return Err("Pi session was dismissed".into());
    }
    let session =
        read_session(&path, id.to_owned()).map_err(|_| "Pi session history unreadable")?;
    if session.turns.last().is_none_or(|turn| turn.id != revision) {
        return Err("Pi history changed; reopen the workspace".into());
    }
    let frame = session
        .text_context()
        .ok_or("Pi session has no verified text context")?;
    let file = std::fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .map_err(|_| "Cannot reopen Pi history")?;
    let bytes = file
        .metadata()
        .map_err(|_| "Cannot inspect Pi history")?
        .len() as usize;
    let journal = Journal {
        path,
        file: Some(tokio::fs::File::from_std(file)),
        _lock: Some(writer),
        model_id: session.model_id.clone(),
        provider: session.provider.clone(),
        bytes,
    };
    Ok((session, journal, frame))
}

impl Journal {
    pub fn new(dir: &Path, id: &str, model_id: &str, provider: &str) -> Self {
        Self {
            file: None,
            _lock: None,
            path: dir.join(format!("{id}.jsonl")),
            model_id: model_id.into(),
            provider: Some(provider.into()),
            bytes: 0,
        }
    }

    pub async fn append(&mut self, record: Record) -> Result<(), String> {
        let mut bytes = Vec::new();
        if self.file.is_none() {
            let header = Record::Header {
                version: VERSION,
                model_id: self.model_id.clone(),
                provider: self.provider.clone(),
            };
            serde_json::to_writer(&mut bytes, &header).map_err(|_| "Invalid Pi history header")?;
            bytes.push(b'\n');
        }
        serde_json::to_writer(&mut bytes, &record).map_err(|_| "Invalid Pi history record")?;
        bytes.push(b'\n');
        // Reserve space to record a full settlement before admitting a turn.
        let reserve = if matches!(record, Record::Submitted { .. }) {
            MAX_TURN_EVENT_BYTES + 256
        } else {
            0
        };
        if self.bytes + bytes.len() + reserve > MAX_JOURNAL_BYTES {
            return Err("Pi session history limit reached; start a new session".into());
        }
        if self.file.is_none() {
            let mut options = OpenOptions::new();
            self._lock = Some(lock(&self.path)?);
            options.create_new(true).write(true);
            #[cfg(unix)]
            options.mode(0o600);
            self.file = Some(
                options
                    .open(&self.path)
                    .await
                    .map_err(|_| "Cannot open Pi history")?,
            );
        }
        let file = self.file.as_mut().ok_or("Pi history unavailable")?;
        file.write_all(&bytes)
            .await
            .map_err(|_| "Cannot write Pi history")?;
        file.sync_data()
            .await
            .map_err(|_| "Cannot commit Pi history")?;
        self.bytes += bytes.len();
        Ok(())
    }
}

fn read_session(path: &Path, id: String) -> Result<Session, &'static str> {
    let file = std::fs::File::open(path).map_err(|_| "open failed")?;
    let mut bytes = Vec::new();
    file.take((MAX_JOURNAL_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| "read failed")?;
    if bytes.len() > MAX_JOURNAL_BYTES {
        return Err("oversized journal");
    }
    let complete = bytes.last() == Some(&b'\n');
    // Only newline-terminated records are committed. A torn last record
    // leaves its preceding submission visible with an unknown outcome.
    let mut rows = bytes
        .split_inclusive(|&byte| byte == b'\n')
        .take_while(|line| line.last() == Some(&b'\n'))
        .map(|line| serde_json::from_slice::<Record>(line).map_err(|_| "invalid record"));
    let Some(Ok(Record::Header {
        version: VERSION,
        model_id,
        provider,
    })) = rows.next()
    else {
        return Err("invalid history header");
    };
    let mut turns = Vec::<Turn>::new();
    let mut seen = HashSet::new();
    for row in rows {
        match row? {
            Record::Submitted {
                id,
                text,
                timestamp,
            } => {
                if !crate::pi_bridge::valid_id(&id)
                    || text.trim().is_empty()
                    || !seen.insert(id.clone())
                {
                    return Err("invalid submission");
                }
                turns.push(Turn {
                    id,
                    text,
                    timestamp,
                    events: Vec::new(),
                    cancellation_requested: false,
                    context_safe: false,
                });
            }
            Record::Settled {
                id,
                events,
                cancellation_requested,
                context_safe,
            } => {
                let turn = turns
                    .last_mut()
                    .filter(|turn| turn.id == id && turn.events.is_empty())
                    .ok_or("unmatched settlement")?;
                if events.last().is_none_or(|event| event["kind"] != "settled") {
                    return Err("missing settlement event");
                }
                turn.events = events
                    .into_iter()
                    .map(|event| {
                        let sanitized =
                            crate::pi_bridge::public_event(event).ok_or("invalid event")?;
                        if sanitized["id"].as_str() != Some(&id) {
                            return Err("unmatched event");
                        }
                        Ok(sanitized)
                    })
                    .collect::<Result<_, _>>()?;
                turn.cancellation_requested = cancellation_requested;
                turn.context_safe = context_safe
                    && turn.events.iter().all(|event| {
                        matches!(
                            event["kind"].as_str(),
                            Some("started" | "text" | "finished" | "settled")
                        )
                    });
            }
            Record::Header { .. } => return Err("unexpected header"),
        }
    }
    Ok(Session {
        id,
        model_id,
        provider,
        complete,
        resume_revision: None,
        turns,
    })
}

fn dismissed_path(dir: &Path, id: &str) -> PathBuf {
    dir.join(format!("{id}.dismissed"))
}

pub async fn dismiss(dir: PathBuf, id: String) -> Result<(), String> {
    if !crate::pi_bridge::valid_id(&id) {
        return Err("Invalid Pi session ID".into());
    }
    // Some sessions are closed without ever admitting a prompt.
    if !tokio::fs::try_exists(dir.join(format!("{id}.jsonl")))
        .await
        .map_err(|_| "Cannot read Pi history")?
    {
        return Ok(());
    }
    let _writer = lock(&dir.join(format!("{id}.jsonl")))?;
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    options.mode(0o600);
    match options.open(dismissed_path(&dir, &id)).await {
        Ok(file) => file
            .sync_all()
            .await
            .map_err(|_| "Cannot commit Pi dismissal".into()),
        Err(err) if err.kind() == ErrorKind::AlreadyExists => Ok(()),
        Err(_) => Err("Cannot dismiss Pi history".into()),
    }
}

pub fn recent(dir: &Path) -> Result<History, String> {
    let mut files = Vec::new();
    for entry in std::fs::read_dir(dir).map_err(|_| "Cannot list Pi history")? {
        let entry = entry.map_err(|_| "Cannot inspect Pi history")?;
        let path = entry.path();
        let Some(id) = path.file_stem().and_then(|name| name.to_str()) else {
            continue;
        };
        if path.extension().and_then(|ext| ext.to_str()) != Some("jsonl")
            || !crate::pi_bridge::valid_id(id)
            || !entry
                .file_type()
                .map_err(|_| "Cannot inspect Pi history")?
                .is_file()
            || dismissed_path(dir, id).exists()
        {
            continue;
        }
        let modified = entry
            .metadata()
            .and_then(|meta| meta.modified())
            .map_err(|_| "Cannot inspect Pi history")?;
        files.push((modified, id.to_owned(), path));
        files.sort_unstable_by(|left, right| right.cmp(left));
        files.truncate(MAX_RECENT_SESSIONS);
    }
    let mut result = History::default();
    for (_, id, path) in files {
        match read_session(&path, id) {
            Ok(mut session) if !session.turns.is_empty() => {
                if session.text_context().is_some() {
                    session.resume_revision = session.turns.last().map(|turn| turn.id.clone());
                }
                result.sessions.push(session);
            }
            Ok(_) => {}
            Err(_) => result.skipped += 1,
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    struct TestDir(PathBuf);

    impl TestDir {
        fn new() -> Self {
            let path =
                std::env::temp_dir().join(format!("gridagent-pi-history-{}", uuid::Uuid::new_v4()));
            std::fs::create_dir(&path).unwrap();
            Self(path.canonicalize().unwrap())
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn prompt(id: &str) -> Record {
        Record::Submitted {
            id: id.into(),
            text: "Analyze the voltage drop.".into(),
            timestamp: chrono::Utc::now(),
        }
    }

    #[tokio::test]
    async fn restart_loads_completed_and_uncertain_turns_without_crossing_workspaces() {
        use std::io::Write;
        let root = TestDir::new();
        let app = root.0.join("app");
        let workspace = root.0.join("project");
        let other_workspace = root.0.join("other");
        std::fs::create_dir(&workspace).unwrap();
        std::fs::create_dir(&other_workspace).unwrap();
        assert!(directory(&workspace.join("app"), &workspace).is_err());
        assert!(!workspace.join("app").exists());

        let dir = directory(&app, &workspace).unwrap();
        let other = directory(&app, &other_workspace).unwrap();
        let session_id = "b".repeat(32);
        let completed = "c".repeat(32);
        let interrupted = "d".repeat(32);
        let mut journal = Journal::new(&dir, &session_id, "test-model", "openai");
        journal.append(prompt(&completed)).await.unwrap();
        let mut events = vec![
            json!({"kind": "text", "id": completed, "delta": "echo provider-"}),
            json!({"kind": "text", "id": completed, "delta": "credential"}),
            json!({"kind": "settled", "id": completed}),
        ];
        redact_events(&mut events, "provider-credential");
        journal
            .append(Record::Settled {
                id: completed.clone(),
                events,
                cancellation_requested: false,
                context_safe: false,
            })
            .await
            .unwrap();
        journal.append(prompt(&interrupted)).await.unwrap();
        let path = journal.path.clone();
        drop(journal);

        // A partially written terminal record must not imply success.
        std::fs::OpenOptions::new()
            .append(true)
            .open(&path)
            .unwrap()
            .write_all(b"{\"kind\":\"settled\",")
            .unwrap();
        let text = std::fs::read_to_string(&path).unwrap();
        assert!(!text.contains("provider-"));
        assert!(!text.contains("credential"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
        let restored = recent(&dir).unwrap();
        let replay = &restored.sessions[0];
        assert_eq!(replay.id, session_id);
        assert_eq!(replay.turns[0].id, completed);
        assert_eq!(replay.turns[0].events[0]["delta"], "[redacted]");
        assert_eq!(replay.turns[1].id, interrupted);
        assert!(replay.turns[1].events.is_empty());
        assert!(recent(&other).unwrap().sessions.is_empty());

        dismiss(dir.clone(), session_id).await.unwrap();
        assert!(recent(&dir).unwrap().sessions.is_empty());
        assert!(path.is_file());
    }

    #[tokio::test]
    async fn resume_requires_a_verified_revision_and_one_writer() {
        let root = TestDir::new();
        let id = "a".repeat(32);
        let first = "b".repeat(32);
        let second = "c".repeat(32);
        let mut journal = Journal::new(&root.0, &id, "test-model", "openai");
        journal.append(prompt(&first)).await.unwrap();
        assert!(recent(&root.0).unwrap().sessions[0]
            .resume_revision
            .is_none());
        journal
            .append(Record::Settled {
                id: first.clone(),
                events: vec![
                    json!({"kind": "text", "id": first, "delta": "Verified answer"}),
                    json!({"kind": "settled", "id": first, "context_ok": true}),
                ],
                cancellation_requested: false,
                context_safe: true,
            })
            .await
            .unwrap();
        assert!(resume(&root.0, &id, &first).is_err());
        drop(journal);
        assert!(resume(&root.0, &id, &second).is_err());
        assert_eq!(
            recent(&root.0).unwrap().sessions[0]
                .resume_revision
                .as_deref(),
            Some(first.as_str())
        );
        let (_, mut reopened, context) = resume(&root.0, &id, &first).unwrap();
        assert_eq!(context["turns"][0]["assistant"], "Verified answer");
        assert!(resume(&root.0, &id, &first).is_err());
        reopened.append(prompt(&second)).await.unwrap();
        drop(reopened);
        let saved = recent(&root.0).unwrap();
        assert_eq!(saved.sessions[0].turns.len(), 2);
        assert!(saved.sessions[0].resume_revision.is_none());
        assert!(resume(&root.0, &id, &second).is_err());
    }

    #[test]
    fn skips_corrupt_and_unknown_version_journals() {
        let root = TestDir::new();
        std::fs::write(root.0.join(format!("{}.jsonl", "a".repeat(32))), "bad\n").unwrap();
        std::fs::write(
            root.0.join(format!("{}.jsonl", "b".repeat(32))),
            "{\"kind\":\"header\",\"version\":2,\"model_id\":\"test\"}\n",
        )
        .unwrap();
        let result = recent(&root.0).unwrap();
        assert!(result.sessions.is_empty());
        assert_eq!(result.skipped, 2);
    }
}
