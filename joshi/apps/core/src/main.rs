use clap::{Args, Parser, Subcommand};
use joshi_core::{
    EMBEDDED_FIXTURE, MAX_FIXTURE_DOCUMENT_BYTES, query_json,
    readiness::{WALKING_MATERIAL, run_offline_readiness},
    run_fixture,
    service::{CoreService, PairingCapability},
};
use joshi_domain::{StableString, UtcTimestamp};
use joshi_evidence::IngestLimits;
use joshi_store::{SqliteStore, StoreConfig, StoreMode};
use std::{
    fs,
    net::SocketAddr,
    path::{Path, PathBuf},
    time::Duration,
};
use thiserror::Error;
use zeroize::Zeroizing;

#[derive(Debug, Parser)]
#[command(version, about = "Local-first, no-execution JOSHI core")]
struct Arguments {
    #[command(subcommand)]
    command: Option<Command>,
    #[command(flatten)]
    fixture: FixtureArguments,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Run the common durable offline source-to-reopen path.
    OfflineReadiness {
        #[arg(long)]
        state: PathBuf,
        #[arg(long)]
        fixture: Option<PathBuf>,
    },
    /// Run the Wave 5 semantic run-registration/restart witness without provider I/O.
    Wave5IgnitionReadiness {
        #[arg(long)]
        state: PathBuf,
    },
    /// Serve bounded local admission and immutable query endpoints on loopback only.
    Serve {
        #[arg(long, default_value = "127.0.0.1:43119")]
        listen: SocketAddr,
        #[arg(long)]
        state: PathBuf,
        #[arg(long)]
        companion_installation_id: String,
        #[arg(long)]
        pairing_token_file: PathBuf,
    },
    /// Run the legacy deterministic in-memory fixture seam.
    Fixture(FixtureArguments),
}

#[derive(Clone, Debug, Args)]
struct FixtureArguments {
    #[arg(long)]
    fixture: Option<PathBuf>,
    #[arg(long, default_value_t = 16)]
    queue_capacity: usize,
    #[arg(long, default_value_t = 1_048_576)]
    max_payload_bytes: u64,
    #[arg(long)]
    pretty: bool,
}

#[tokio::main]
async fn main() -> Result<(), CliError> {
    let arguments = Arguments::parse();
    match arguments.command {
        Some(Command::OfflineReadiness { state, fixture }) => {
            let material = fixture
                .map(fs::read_to_string)
                .transpose()?
                .unwrap_or_else(|| WALKING_MATERIAL.to_owned());
            let report = run_offline_readiness(&state, &material)?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave5IgnitionReadiness { state }) => {
            let report = joshi_core::wave5_readiness::run_wave5_ignition_readiness(&state)?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Serve {
            listen,
            state,
            companion_installation_id,
            pairing_token_file,
        }) => {
            let mut store = SqliteStore::open(
                store_config(&state, "joshi-local-core")?,
                StoreMode::SingleWriter,
            )?;
            store.migrate(now()?)?;
            let pairing_token = read_pairing_token(&pairing_token_file)?;
            let pairing = PairingCapability::from_hex(&pairing_token)?;
            CoreService::new(store, Some(companion_installation_id), pairing)
                .serve(listen)
                .await?;
        }
        Some(Command::Fixture(fixture)) => run_fixture_command(fixture).await?,
        None => run_fixture_command(arguments.fixture).await?,
    }
    Ok(())
}

async fn run_fixture_command(arguments: FixtureArguments) -> Result<(), CliError> {
    let input = match arguments.fixture {
        Some(path) => {
            let bytes = fs::read(path)?;
            if bytes.len() > MAX_FIXTURE_DOCUMENT_BYTES {
                return Err(CliError::FixtureTooLarge(bytes.len()));
            }
            String::from_utf8(bytes)?
        }
        None => EMBEDDED_FIXTURE.to_owned(),
    };
    let limits = IngestLimits::new(arguments.queue_capacity, arguments.max_payload_bytes)?;
    let query = run_fixture(&input, limits).await?;
    println!("{}", query_json(&query, arguments.pretty)?);
    Ok(())
}

fn store_config(root: &Path, catalog: &str) -> Result<StoreConfig, CliError> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: StableString::new(catalog)?,
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}
fn now() -> Result<UtcTimestamp, CliError> {
    let nanos = time::OffsetDateTime::now_utc().unix_timestamp_nanos();
    let micros = nanos.div_euclid(1_000) * 1_000;
    UtcTimestamp::new(
        time::OffsetDateTime::from_unix_timestamp_nanos(micros).map_err(|_| CliError::Clock)?,
    )
    .map_err(|_| CliError::Clock)
}

fn read_pairing_token(path: &Path) -> Result<Zeroizing<String>, CliError> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() > 1024 {
        return Err(CliError::UnsafePairingFile);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt as _;
        if metadata.mode() & 0o077 != 0 {
            return Err(CliError::UnsafePairingFile);
        }
    }
    let token = fs::read_to_string(path)?;
    let token = token.strip_suffix('\n').unwrap_or(&token);
    if token.contains(['\r', '\n']) {
        return Err(CliError::UnsafePairingFile);
    }
    Ok(Zeroizing::new(token.to_owned()))
}

#[derive(Debug, Error)]
enum CliError {
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Utf8(#[from] std::string::FromUtf8Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Ingest(#[from] joshi_evidence::IngestError),
    #[error(transparent)]
    Core(#[from] joshi_core::CoreError),
    #[error(transparent)]
    Readiness(#[from] joshi_core::readiness::ReadinessError),
    #[error(transparent)]
    Wave5Readiness(#[from] joshi_core::wave5_readiness::Wave5ReadinessError),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Service(#[from] joshi_core::service::ServiceError),
    #[error(transparent)]
    Pairing(#[from] joshi_core::service::PairingCapabilityError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error("system clock is unavailable")]
    Clock,
    #[error("pairing token file must be a regular, non-symlink, owner-only file of bounded size")]
    UnsafePairingFile,
    #[error("fixture exceeds {MAX_FIXTURE_DOCUMENT_BYTES} bytes: {0}")]
    FixtureTooLarge(usize),
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::{PermissionsExt as _, symlink};

    const TOKEN: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";

    #[test]
    fn pairing_file_is_owner_only_regular_and_never_followed_through_a_final_symlink() {
        let root = tempfile::tempdir().expect("tempdir");
        let path = root.path().join("pairing-token");
        fs::write(&path, format!("{TOKEN}\n")).expect("write token");
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("permissions");
        let loaded = read_pairing_token(&path).expect("owner-only token");
        assert_eq!(loaded.as_str(), TOKEN);

        fs::set_permissions(&path, fs::Permissions::from_mode(0o640)).expect("permissions");
        assert!(matches!(
            read_pairing_token(&path),
            Err(CliError::UnsafePairingFile)
        ));
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("permissions");
        let link = root.path().join("pairing-link");
        symlink(&path, &link).expect("symlink");
        assert!(matches!(
            read_pairing_token(&link),
            Err(CliError::UnsafePairingFile)
        ));
    }
}
