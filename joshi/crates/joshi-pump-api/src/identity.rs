use std::fs::{self, File, OpenOptions};
use std::io::{Read as _, Write as _};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use thiserror::Error;

#[derive(Error, Debug)]
pub enum IdentityError {
    #[error("identity store I/O failed at {path}: {source}")]
    Io {
        path: PathBuf,
        source: std::io::Error,
    },
    #[error("installation identity is malformed")]
    MalformedInstallation,
    #[error("unable to allocate a collision-free acquisition identity")]
    CollisionBudgetExhausted,
    #[error("system clock precedes the Unix epoch")]
    Clock,
}

#[derive(Clone, Debug)]
pub struct IdentityStore {
    root: PathBuf,
    installation: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AcquisitionReservation {
    pub acquisition_id: String,
    pub reservation_path: PathBuf,
}

impl IdentityStore {
    /// Open or create a local installation namespace. Installation and each occurrence marker are
    /// synced before a request can leave the process.
    ///
    /// # Errors
    ///
    /// Returns an error when the directory cannot be durably created/read or an existing
    /// installation identity is malformed.
    pub fn open(root: impl Into<PathBuf>) -> Result<Self, IdentityError> {
        let root = root.into();
        fs::create_dir_all(root.join("reservations"))
            .map_err(|source| io(root.join("reservations"), source))?;
        fs::create_dir_all(root.join("committed"))
            .map_err(|source| io(root.join("committed"), source))?;
        let installation_path = root.join("installation-id");
        let installation = if installation_path.exists() {
            fs::read_to_string(&installation_path)
                .map_err(|source| io(installation_path.clone(), source))?
                .trim()
                .to_owned()
        } else {
            let candidate = random_hex(16)?;
            match OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&installation_path)
            {
                Ok(mut file) => {
                    file.write_all(candidate.as_bytes())
                        .and_then(|()| file.write_all(b"\n"))
                        .and_then(|()| file.sync_all())
                        .map_err(|source| io(installation_path.clone(), source))?;
                    sync_directory(&root)?;
                    candidate
                }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                    fs::read_to_string(&installation_path)
                        .map_err(|source| io(installation_path.clone(), source))?
                        .trim()
                        .to_owned()
                }
                Err(source) => return Err(io(installation_path, source)),
            }
        };
        if installation.len() != 32
            || !installation
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        {
            return Err(IdentityError::MalformedInstallation);
        }
        Ok(Self { root, installation })
    }

    #[must_use]
    pub fn installation(&self) -> &str {
        &self.installation
    }

    /// Allocate and durably reserve an opaque occurrence ID before network I/O. Randomness is not
    /// truth or replay order; the installation namespace and persisted marker prevent reuse after
    /// restart, while wall/monotonic clocks retain ordering evidence separately.
    ///
    /// # Errors
    ///
    /// Returns an error if entropy, clock, file creation, or durability synchronization fails.
    pub fn reserve(&self) -> Result<AcquisitionReservation, IdentityError> {
        let micros = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| IdentityError::Clock)?
            .as_micros();
        for _ in 0..16 {
            let nonce = random_hex(16)?;
            let occurrence = format!("{micros}-{nonce}");
            let path = self
                .root
                .join("reservations")
                .join(format!("{occurrence}.reserved"));
            match OpenOptions::new().write(true).create_new(true).open(&path) {
                Ok(mut file) => {
                    let id = format!("acq:pump-api:{}:{occurrence}", self.installation);
                    file.write_all(id.as_bytes())
                        .and_then(|()| file.write_all(b"\n"))
                        .and_then(|()| file.sync_all())
                        .map_err(|source| io(path.clone(), source))?;
                    sync_directory(&self.root.join("reservations"))?;
                    return Ok(AcquisitionReservation {
                        acquisition_id: id,
                        reservation_path: path,
                    });
                }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(source) => return Err(io(path, source)),
            }
        }
        Err(IdentityError::CollisionBudgetExhausted)
    }

    /// Mark an occurrence complete only after the caller has a durable sink receipt. Reserved
    /// markers intentionally survive crashes and ambiguous receipts.
    ///
    /// # Errors
    ///
    /// Returns an error if the reservation path is malformed or the durable rename/sync fails.
    pub fn acknowledge(&self, reservation: &AcquisitionReservation) -> Result<(), IdentityError> {
        let file_name = reservation
            .reservation_path
            .file_stem()
            .and_then(|value| value.to_str())
            .ok_or(IdentityError::MalformedInstallation)?;
        let destination = self
            .root
            .join("committed")
            .join(format!("{file_name}.committed"));
        fs::rename(&reservation.reservation_path, &destination)
            .map_err(|source| io(reservation.reservation_path.clone(), source))?;
        sync_directory(&self.root.join("committed"))?;
        Ok(())
    }

    /// Reconstruct a local reservation marker from an acquisition ID after a durable sink receipt
    /// and acknowledge it. The ID must belong to this installation; arbitrary paths are rejected.
    ///
    /// # Errors
    ///
    /// Returns an error for an alien/malformed ID or if the durable rename/sync fails.
    pub fn acknowledge_id(&self, acquisition_id: &str) -> Result<(), IdentityError> {
        let prefix = format!("acq:pump-api:{}:", self.installation);
        let occurrence = acquisition_id
            .strip_prefix(&prefix)
            .ok_or(IdentityError::MalformedInstallation)?;
        if occurrence.is_empty()
            || !occurrence
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte) || byte == b'-')
        {
            return Err(IdentityError::MalformedInstallation);
        }
        let reservation = AcquisitionReservation {
            acquisition_id: acquisition_id.to_owned(),
            reservation_path: self
                .root
                .join("reservations")
                .join(format!("{occurrence}.reserved")),
        };
        self.acknowledge(&reservation)
    }
}

fn random_hex(length: usize) -> Result<String, IdentityError> {
    let path = Path::new("/dev/urandom");
    let mut file = File::open(path).map_err(|source| io(path.to_path_buf(), source))?;
    let mut bytes = vec![0_u8; length];
    file.read_exact(&mut bytes)
        .map_err(|source| io(path.to_path_buf(), source))?;
    let mut output = String::with_capacity(length * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        write!(&mut output, "{byte:02x}").expect("writing to String cannot fail");
    }
    Ok(output)
}

fn sync_directory(path: &Path) -> Result<(), IdentityError> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|source| io(path.to_path_buf(), source))
}

fn io(path: PathBuf, source: std::io::Error) -> IdentityError {
    IdentityError::Io { path, source }
}
