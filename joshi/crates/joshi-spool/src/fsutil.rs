use crate::{Result, SpoolError};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};

/// Named durability transitions used by deterministic crash tests.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum FaultPoint {
    AfterTemporarySync,
    AfterReadyRename,
    AfterDirectorySync,
    AfterPartialSync,
    AfterReplicaReadyRename,
    AfterAckTemporarySync,
}

/// Injectable failpoint seam. Production uses [`NoFaults`].
pub trait FaultInjector: Send + Sync {
    /// Returns an injected error at a named transition when configured to do so.
    ///
    /// # Errors
    ///
    /// Implementations return the intended deterministic failure.
    fn check(&self, point: FaultPoint) -> Result<()>;
}

/// Production fault injector.
#[derive(Clone, Copy, Debug, Default)]
pub struct NoFaults;

impl FaultInjector for NoFaults {
    fn check(&self, _point: FaultPoint) -> Result<()> {
        Ok(())
    }
}

pub(crate) fn create_layout(root: &Path, directories: &[&str]) -> Result<()> {
    fs::create_dir_all(root).map_err(|error| SpoolError::io(root, error))?;
    for directory in directories {
        let path = root.join(directory);
        fs::create_dir_all(&path).map_err(|error| SpoolError::io(&path, error))?;
        sync_directory(&path)?;
    }
    sync_directory(root)
}

pub(crate) fn atomic_write(
    final_path: &Path,
    bytes: &[u8],
    injector: &dyn FaultInjector,
    after_temp: FaultPoint,
    after_rename: FaultPoint,
) -> Result<()> {
    let parent = final_path
        .parent()
        .ok_or_else(|| SpoolError::Invalid("durable path has no parent".into()))?;
    let name = final_path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| SpoolError::Invalid("durable filename is not UTF-8".into()))?;
    let temporary = parent.join(format!(".{name}.pending"));
    if temporary.exists() {
        if read(&temporary)? != bytes {
            return Err(SpoolError::Integrity(format!(
                "pending durable write conflicts with {}",
                final_path.display()
            )));
        }
        fs::rename(&temporary, final_path).map_err(|error| SpoolError::io(final_path, error))?;
        injector.check(after_rename)?;
        sync_directory(parent)?;
        return injector.check(FaultPoint::AfterDirectorySync);
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|error| SpoolError::io(&temporary, error))?;
    file.write_all(bytes)
        .map_err(|error| SpoolError::io(&temporary, error))?;
    file.sync_all()
        .map_err(|error| SpoolError::io(&temporary, error))?;
    injector.check(after_temp)?;
    fs::rename(&temporary, final_path).map_err(|error| SpoolError::io(final_path, error))?;
    injector.check(after_rename)?;
    sync_directory(parent)?;
    injector.check(FaultPoint::AfterDirectorySync)
}

pub(crate) fn append_and_sync(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|error| SpoolError::io(path, error))?;
    file.write_all(bytes)
        .map_err(|error| SpoolError::io(path, error))?;
    file.sync_all().map_err(|error| SpoolError::io(path, error))
}

pub(crate) fn read(path: &Path) -> Result<Vec<u8>> {
    fs::read(path).map_err(|error| SpoolError::io(path, error))
}

pub(crate) fn sync_directory(path: &Path) -> Result<()> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|error| SpoolError::io(path, error))
}

pub(crate) fn list_files(path: &Path) -> Result<Vec<PathBuf>> {
    let mut files = fs::read_dir(path)
        .map_err(|error| SpoolError::io(path, error))?
        .map(|entry| entry.map(|value| value.path()))
        .collect::<std::io::Result<Vec<_>>>()
        .map_err(|error| SpoolError::io(path, error))?;
    files.retain(|value| value.is_file());
    files.sort();
    Ok(files)
}
