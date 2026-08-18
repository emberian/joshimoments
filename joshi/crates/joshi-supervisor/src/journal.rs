use crate::{
    AUTHORITY_CEILING, JournalEvent, JournalRecord, Result, SUPERVISOR_CONTRACT_VERSION,
    SupervisorError,
};
use joshi_domain::UtcTimestamp;
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::Write as _,
    path::{Path, PathBuf},
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum FaultPoint {
    AfterJournalTemporarySync,
    AfterJournalRename,
    AfterLocalSpoolAppend,
    AfterHealthTemporarySync,
}

pub trait FaultInjector: Send + Sync {
    /// Fail a named deterministic durability transition.
    ///
    /// # Errors
    ///
    /// Test injectors return [`SupervisorError::Injected`].
    fn check(&self, point: FaultPoint) -> Result<()>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct NoFaults;

impl FaultInjector for NoFaults {
    fn check(&self, _point: FaultPoint) -> Result<()> {
        Ok(())
    }
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct InstallationIdentity {
    contract: String,
    installation_id: String,
    authority: String,
}

pub(crate) struct DurableJournal {
    root: PathBuf,
    installation_id: String,
    records: Vec<JournalRecord>,
    next_ordinal: u64,
    faults: Arc<dyn FaultInjector>,
    _lock: File,
}

impl DurableJournal {
    pub(crate) fn open(collector_root: &Path, faults: Arc<dyn FaultInjector>) -> Result<Self> {
        let identity_root = collector_root.join("identity");
        let events_root = collector_root.join("journal").join("events");
        let health_root = collector_root.join("health");
        create_dir_durable(collector_root)?;
        create_dir_durable(&identity_root)?;
        create_dir_durable(&events_root)?;
        create_dir_durable(&health_root)?;

        let lock_path = identity_root.join("supervisor.lock");
        let lock = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .truncate(false)
            .open(&lock_path)
            .map_err(|source| SupervisorError::io(&lock_path, source))?;
        lock.try_lock()
            .map_err(|_| SupervisorError::AlreadyRunning(lock_path.clone()))?;

        let installation_id = load_or_create_installation(&identity_root)?;
        recover_pending(&events_root)?;
        let records = load_records(&events_root)?;
        let next_ordinal = records
            .last()
            .map_or(1, |record| record.ordinal.saturating_add(1));
        Ok(Self {
            root: collector_root.to_path_buf(),
            installation_id,
            records,
            next_ordinal,
            faults,
            _lock: lock,
        })
    }

    pub(crate) fn installation_id(&self) -> &str {
        &self.installation_id
    }

    pub(crate) fn records(&self) -> &[JournalRecord] {
        &self.records
    }

    pub(crate) const fn next_ordinal(&self) -> u64 {
        self.next_ordinal
    }

    pub(crate) fn append(
        &mut self,
        recorded_at: UtcTimestamp,
        event: JournalEvent,
    ) -> Result<JournalRecord> {
        let record = JournalRecord {
            contract: SUPERVISOR_CONTRACT_VERSION.into(),
            ordinal: self.next_ordinal,
            recorded_at,
            event,
            authority: AUTHORITY_CEILING.into(),
        };
        let bytes = serde_json::to_vec(&record)?;
        let events = self.root.join("journal").join("events");
        let final_path = events.join(format!("{:020}.json", record.ordinal));
        let temporary = events.join(format!(".{:020}.json.pending", record.ordinal));
        write_new(&temporary, &bytes)?;
        self.faults.check(FaultPoint::AfterJournalTemporarySync)?;
        fs::rename(&temporary, &final_path)
            .map_err(|source| SupervisorError::io(&final_path, source))?;
        self.faults.check(FaultPoint::AfterJournalRename)?;
        sync_directory(&events)?;
        self.records.push(record.clone());
        self.next_ordinal = self.next_ordinal.saturating_add(1);
        Ok(record)
    }

    pub(crate) fn write_health(&self, bytes: &[u8]) -> Result<()> {
        let root = self.root.join("health");
        let final_path = root.join("snapshot.json");
        let temporary = root.join(".snapshot.json.pending");
        if temporary.exists() {
            fs::remove_file(&temporary)
                .map_err(|source| SupervisorError::io(&temporary, source))?;
        }
        write_new(&temporary, bytes)?;
        self.faults.check(FaultPoint::AfterHealthTemporarySync)?;
        fs::rename(&temporary, &final_path)
            .map_err(|source| SupervisorError::io(&final_path, source))?;
        sync_directory(&root)
    }
}

fn create_dir_durable(path: &Path) -> Result<()> {
    fs::create_dir_all(path).map_err(|source| SupervisorError::io(path, source))?;
    sync_directory(path)
}

fn load_or_create_installation(root: &Path) -> Result<String> {
    let path = root.join("installation.json");
    if path.exists() {
        return read_installation(&path);
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| SupervisorError::InvalidState("system clock precedes Unix epoch".into()))?
        .as_nanos();
    let mut hasher = Sha256::new();
    hasher.update(b"joshi.supervisor.installation.v1\0");
    hasher.update(root.as_os_str().as_encoded_bytes());
    hasher.update(b"\0");
    hasher.update(std::process::id().to_be_bytes());
    hasher.update(now.to_be_bytes());
    let digest = format!("{:x}", hasher.finalize());
    let identity = InstallationIdentity {
        contract: "joshi.supervisor.installation.v1".into(),
        installation_id: format!("inst-{}", &digest[..32]),
        authority: AUTHORITY_CEILING.into(),
    };
    let bytes = serde_json::to_vec(&identity)?;
    let temporary = root.join(".installation.json.pending");
    match write_new(&temporary, &bytes) {
        Ok(()) => {
            fs::rename(&temporary, &path).map_err(|source| SupervisorError::io(&path, source))?;
            sync_directory(root)?;
            Ok(identity.installation_id)
        }
        Err(SupervisorError::Io { source, .. })
            if source.kind() == std::io::ErrorKind::AlreadyExists =>
        {
            if path.exists() {
                read_installation(&path)
            } else {
                Err(SupervisorError::AlreadyRunning(temporary))
            }
        }
        Err(error) => Err(error),
    }
}

fn read_installation(path: &Path) -> Result<String> {
    let bytes = fs::read(path).map_err(|source| SupervisorError::io(path, source))?;
    let identity: InstallationIdentity = serde_json::from_slice(&bytes)?;
    let valid_id = identity.installation_id.len() == 37
        && identity.installation_id.starts_with("inst-")
        && identity.installation_id[5..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase());
    if identity.contract != "joshi.supervisor.installation.v1"
        || identity.authority != AUTHORITY_CEILING
        || !valid_id
    {
        return Err(SupervisorError::CorruptJournal(
            "installation identity contract is invalid".into(),
        ));
    }
    Ok(identity.installation_id)
}

fn recover_pending(events: &Path) -> Result<()> {
    for path in list_files(events)? {
        let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
            return Err(SupervisorError::CorruptJournal(
                "journal filename is not UTF-8".into(),
            ));
        };
        let Some(final_name) = name
            .strip_prefix('.')
            .and_then(|value| value.strip_suffix(".pending"))
        else {
            continue;
        };
        let bytes = fs::read(&path).map_err(|source| SupervisorError::io(&path, source))?;
        let _: JournalRecord = serde_json::from_slice(&bytes)?;
        let final_path = events.join(final_name);
        if final_path.exists() {
            let final_bytes =
                fs::read(&final_path).map_err(|source| SupervisorError::io(&final_path, source))?;
            if final_bytes != bytes {
                return Err(SupervisorError::CorruptJournal(
                    "pending and ready journal records conflict".into(),
                ));
            }
            fs::remove_file(&path).map_err(|source| SupervisorError::io(&path, source))?;
        } else {
            fs::rename(&path, &final_path)
                .map_err(|source| SupervisorError::io(&final_path, source))?;
        }
        sync_directory(events)?;
    }
    Ok(())
}

fn load_records(events: &Path) -> Result<Vec<JournalRecord>> {
    let mut records = Vec::new();
    for path in list_files(events)? {
        let is_visible = path
            .file_name()
            .and_then(|value| value.to_str())
            .is_some_and(|name| !name.starts_with('.'));
        let is_canonical_json = path
            .extension()
            .is_some_and(|extension| extension == "json");
        if !is_visible || !is_canonical_json {
            continue;
        }
        let bytes = fs::read(&path).map_err(|source| SupervisorError::io(&path, source))?;
        let record: JournalRecord = serde_json::from_slice(&bytes)?;
        if record.contract != SUPERVISOR_CONTRACT_VERSION || record.authority != AUTHORITY_CEILING {
            return Err(SupervisorError::CorruptJournal(format!(
                "journal record {} has the wrong contract or authority",
                path.display()
            )));
        }
        records.push(record);
    }
    records.sort_by_key(|record| record.ordinal);
    for (index, record) in records.iter().enumerate() {
        let expected = u64::try_from(index).unwrap_or(u64::MAX).saturating_add(1);
        if record.ordinal != expected {
            return Err(SupervisorError::CorruptJournal(format!(
                "journal ordinal {} followed {}",
                record.ordinal,
                expected.saturating_sub(1)
            )));
        }
    }
    Ok(records)
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|source| SupervisorError::io(path, source))?;
    file.write_all(bytes)
        .map_err(|source| SupervisorError::io(path, source))?;
    file.sync_all()
        .map_err(|source| SupervisorError::io(path, source))
}

fn sync_directory(path: &Path) -> Result<()> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|source| SupervisorError::io(path, source))
}

fn list_files(path: &Path) -> Result<Vec<PathBuf>> {
    let mut files = fs::read_dir(path)
        .map_err(|source| SupervisorError::io(path, source))?
        .map(|entry| entry.map(|value| value.path()))
        .collect::<std::io::Result<Vec<_>>>()
        .map_err(|source| SupervisorError::io(path, source))?;
    files.retain(|path| path.is_file());
    files.sort();
    Ok(files)
}
