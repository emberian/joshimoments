use crate::{Result, StoreError};
use joshi_domain::{BlobId, StableString, ValueDigest};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Component, Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

/// Bytes prepared in content-addressed storage before their catalog transaction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedBlob {
    /// Algorithm-qualified identity of the uncompressed exact bytes.
    pub blob_id: BlobId,
    /// Raw lowercase digest used by the SQL schema.
    pub(crate) raw_sha256: String,
    /// Exact source length.
    pub(crate) content_length: u64,
    /// Inline bytes, or `None` for an external artifact.
    pub(crate) inline_bytes: Option<Vec<u8>>,
    /// Safe path relative to the configured blob root.
    pub(crate) relative_path: Option<PathBuf>,
    /// Exact declared content type.
    pub(crate) content_type: StableString,
    /// Exact declared content encoding.
    pub(crate) content_encoding: Option<StableString>,
    /// SQL retention class.
    pub(crate) retention_class: StableString,
    /// V1 physical protection domain; currently equal to explicit retention class.
    pub(crate) storage_domain: StableString,
}

impl PreparedBlob {
    pub(crate) fn storage_mode(&self) -> &'static str {
        if self.inline_bytes.is_some() {
            "inline"
        } else {
            "external"
        }
    }
}

/// Immutable analytical export prepared before its catalog transaction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedExport {
    /// Safe path relative to the configured export root.
    pub relative_path: PathBuf,
    /// Algorithm-qualified exact file digest.
    pub digest: ValueDigest,
    /// Exact byte length.
    pub byte_length: u64,
}

/// Immutable content-addressed filesystem used by the single catalog writer.
#[derive(Clone, Debug)]
pub struct BlobStore {
    root: PathBuf,
    inline_max_bytes: u64,
}

impl BlobStore {
    /// Creates a blob store rooted at `root`.
    #[must_use]
    pub fn new(root: impl Into<PathBuf>, inline_max_bytes: u64) -> Self {
        Self {
            root: root.into(),
            inline_max_bytes,
        }
    }

    /// Returns the configured root.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Hashes and, when required, durably installs immutable bytes before SQL references them.
    ///
    /// # Errors
    ///
    /// Fails on unsupported retention, filesystem errors, or an existing corrupt artifact.
    pub fn prepare(
        &self,
        bytes: &[u8],
        content_type: StableString,
        content_encoding: Option<StableString>,
        retention_class: StableString,
        force_external: bool,
    ) -> Result<PreparedBlob> {
        validate_retention(retention_class.as_str())?;
        let raw_sha256 = sha256_hex(bytes);
        let blob_id = BlobId::new(format!("sha256:{raw_sha256}"))
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let content_length = u64::try_from(bytes.len()).map_err(|_| StoreError::IntegerRange {
            field: "blob content length",
            value: bytes.len().to_string(),
        })?;
        let private = matches!(
            retention_class.as_str(),
            "social_media" | "app_private" | "operator_private" | "disposable"
        );
        let external = force_external || private || content_length > self.inline_max_bytes;
        let (inline_bytes, relative_path) = if external {
            let relative = PathBuf::from(retention_class.as_str())
                .join("sha256")
                .join(&raw_sha256[0..2])
                .join(&raw_sha256[2..4])
                .join(format!("{raw_sha256}.blob"));
            install_immutable(&self.root, &relative, bytes, &raw_sha256)?;
            (None, Some(relative))
        } else {
            (Some(bytes.to_vec()), None)
        };
        Ok(PreparedBlob {
            blob_id,
            raw_sha256,
            content_length,
            inline_bytes,
            relative_path,
            content_type,
            content_encoding,
            storage_domain: retention_class.clone(),
            retention_class,
        })
    }

    pub(crate) fn verify(&self, blob: &PreparedBlob) -> Result<()> {
        if let Some(bytes) = &blob.inline_bytes {
            if sha256_hex(bytes) != blob.raw_sha256 {
                return Err(StoreError::ArtifactVerification {
                    path: self.root.clone(),
                    detail: "inline bytes no longer match their prepared digest".into(),
                });
            }
            return Ok(());
        }
        let relative = blob.relative_path.as_ref().ok_or_else(|| {
            StoreError::InvalidBatch("external prepared blob has no relative path".into())
        })?;
        verify_file(
            &self.root.join(relative),
            &blob.raw_sha256,
            blob.content_length,
        )
    }
}

pub(crate) fn prepare_export_file(
    root: &Path,
    relative_path: &Path,
    bytes: &[u8],
) -> Result<PreparedExport> {
    validate_relative_path(relative_path)?;
    let raw = sha256_hex(bytes);
    install_immutable(root, relative_path, bytes, &raw)?;
    Ok(PreparedExport {
        relative_path: relative_path.to_owned(),
        digest: ValueDigest::new(format!("sha256:{raw}"))
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
        byte_length: u64::try_from(bytes.len()).map_err(|_| StoreError::IntegerRange {
            field: "export byte length",
            value: bytes.len().to_string(),
        })?,
    })
}

pub(crate) fn verify_file(path: &Path, expected_sha256: &str, expected_len: u64) -> Result<()> {
    let mut file = File::open(path).map_err(|source| StoreError::io(path, source))?;
    let metadata = file
        .metadata()
        .map_err(|source| StoreError::io(path, source))?;
    if metadata.len() != expected_len {
        return Err(StoreError::ArtifactVerification {
            path: path.to_owned(),
            detail: format!("length {} != expected {expected_len}", metadata.len()),
        });
    }
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; 64 * 1024].into_boxed_slice();
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|source| StoreError::io(path, source))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    let actual = format!("{:x}", hasher.finalize());
    if actual != expected_sha256 {
        return Err(StoreError::ArtifactVerification {
            path: path.to_owned(),
            detail: format!("sha256 {actual} != expected {expected_sha256}"),
        });
    }
    Ok(())
}

pub(crate) fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

/// Raw lowercase SHA-256 of a file's exact bytes, read in fixed-size chunks.
///
/// Same digest as `sha256_hex` over the same bytes; the difference is that a catalog-sized
/// file never has to fit in one allocation to be hashed.
pub(crate) fn sha256_hex_file(path: &Path) -> Result<String> {
    let mut file = File::open(path).map_err(|source| StoreError::io(path, source))?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; 64 * 1024].into_boxed_slice();
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|source| StoreError::io(path, source))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn install_immutable(root: &Path, relative: &Path, bytes: &[u8], digest: &str) -> Result<()> {
    validate_relative_path(relative)?;
    let destination = root.join(relative);
    if destination.exists() {
        return verify_file(
            &destination,
            digest,
            u64::try_from(bytes.len()).unwrap_or(u64::MAX),
        );
    }
    let parent = destination.parent().ok_or_else(|| {
        StoreError::InvalidBatch("immutable artifact has no parent directory".into())
    })?;
    fs::create_dir_all(parent).map_err(|source| StoreError::io(parent, source))?;
    let temporary = parent.join(format!(
        ".{}.{}.{}.tmp",
        digest,
        std::process::id(),
        TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|source| StoreError::io(&temporary, source))?;
    if let Err(source) = file.write_all(bytes).and_then(|()| file.sync_all()) {
        let _ = fs::remove_file(&temporary);
        return Err(StoreError::io(&temporary, source));
    }
    drop(file);
    if let Err(source) = fs::rename(&temporary, &destination) {
        let _ = fs::remove_file(&temporary);
        return Err(StoreError::io(&destination, source));
    }
    sync_directory(parent)?;
    verify_file(
        &destination,
        digest,
        u64::try_from(bytes.len()).unwrap_or(u64::MAX),
    )
}

fn sync_directory(path: &Path) -> Result<()> {
    let directory = File::open(path).map_err(|source| StoreError::io(path, source))?;
    directory
        .sync_all()
        .map_err(|source| StoreError::io(path, source))
}

fn validate_relative_path(path: &Path) -> Result<()> {
    if path.as_os_str().is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(StoreError::InvalidBatch(format!(
            "unsafe relative artifact path {}",
            path.display()
        )));
    }
    Ok(())
}

fn validate_retention(value: &str) -> Result<()> {
    if matches!(
        value,
        "public_chain"
            | "public_source"
            | "social_media"
            | "app_private"
            | "operator_private"
            | "fixture"
            | "disposable"
    ) {
        Ok(())
    } else {
        Err(StoreError::InvalidBatch(format!(
            "unsupported retention class {value}"
        )))
    }
}
