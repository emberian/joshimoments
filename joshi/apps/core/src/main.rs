use clap::{Args, Parser, Subcommand};
use joshi_core::{
    EMBEDDED_FIXTURE, MAX_FIXTURE_DOCUMENT_BYTES,
    g0_inspector_smoke::G0InspectorSmokeError,
    pairing::OrdinaryPairingError,
    query_json,
    readiness::{WALKING_MATERIAL, run_offline_readiness},
    run_fixture,
    service::{CoreService, PairingCapability},
};
use joshi_domain::{StableString, UtcTimestamp};
use joshi_evidence::IngestLimits;
use joshi_pairing::{PairingConfig, PairingError, PairingOrigin, PairingScope};
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
    /// Run the narrow offline G0 source-fact and immutable-publication component witness.
    Wave5G0SourcePublication {
        #[arg(long)]
        state: PathBuf,
    },
    /// Run the one-shot paired Cockpit V2 fixture route and restart smoke witness.
    Wave5G0InspectorSmoke {
        #[arg(long)]
        state: PathBuf,
    },
    /// Join the partial G0 component and paired route into one 18-role evidence bundle.
    Wave5G0RootEvidence {
        #[arg(long)]
        state: PathBuf,
    },
    /// Persist and reopen the exact fixture-only Wave 6 N00 registration.
    Wave6ProgramRegistration {
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
    /// Serve the exact offline G0 fixture through durable ordinary pairing for local inspection.
    Wave5G0Inspect {
        #[arg(long, default_value = "127.0.0.1:43119")]
        listen: SocketAddr,
        #[arg(long, default_value = "http://127.0.0.1:4173")]
        glass_origin: String,
        #[arg(long)]
        state: PathBuf,
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
        Some(Command::Wave5G0SourcePublication { state }) => {
            let report = joshi_core::wave5_g0::run_wave5_g0_source_publication(&state)?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave5G0InspectorSmoke { state }) => {
            let report = joshi_core::g0_inspector_smoke::run_g0_inspector_smoke(&state).await?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave5G0RootEvidence { state }) => {
            let report =
                joshi_core::wave5_g0_root_evidence::run_wave5_g0_root_evidence(&state).await?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave6ProgramRegistration { state }) => {
            let report = joshi_core::wave6_registration::run_wave6_program_registration(&state)?;
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
        Some(Command::Wave5G0Inspect {
            listen,
            glass_origin,
            state,
        }) => {
            if !listen.ip().is_loopback() {
                return Err(CliError::NonLoopback(listen));
            }
            let report = joshi_core::wave5_g0::run_wave5_g0_source_publication(&state)?;
            if report.status != "useful_partial"
                || report.catalog_schema != "joshi.sqlite.v10"
                || !report.source_semantics_closed
                || !report.publication_prepare_body_head_closed
                || !report.partial_memory_chain_closed
                || !report.nonempty_v10_export_closed
                || !report.v10_export_recovery_closed
                || !report.partial_backup_restore_closed
                || !report.restart_reverified
                || report.full_offline_fault_walk
                || report.provider_io
                || report.product_qualified
                || report.live_qualified
            {
                return Err(CliError::FixtureInspectorQualification);
            }
            let store = SqliteStore::open(
                joshi_core::wave5_g0::offline_fixture_store_config(&state)?,
                StoreMode::SingleWriter,
            )?;
            let pairing = PairingCapability::generate_os_random()?;
            let origin = PairingOrigin::new(glass_origin)?;
            let (core, launcher) = CoreService::with_sqlite_pairing(
                store,
                None,
                pairing,
                origin,
                PairingConfig::default(),
            )?;
            let listener = tokio::net::TcpListener::bind(listen).await?;
            let issued = launcher.issue_code(vec![PairingScope::CockpitRead])?;
            eprintln!(
                "offline-fixture one-time pairing code (Cockpit read only): {}",
                issued.code.as_str()
            );
            axum::serve(listener, core.router()).await?;
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
    Wave5G0SourcePublication(#[from] joshi_core::wave5_g0::Wave5G0SourcePublicationError),
    #[error(transparent)]
    G0InspectorSmoke(#[from] G0InspectorSmokeError),
    #[error(transparent)]
    Wave5G0RootEvidence(#[from] joshi_core::wave5_g0_root_evidence::Wave5G0RootEvidenceError),
    #[error(transparent)]
    Wave6Registration(#[from] joshi_core::wave6_registration::Wave6RegistrationError),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Service(#[from] joshi_core::service::ServiceError),
    #[error(transparent)]
    Pairing(#[from] joshi_core::service::PairingCapabilityError),
    #[error(transparent)]
    PairingGeneration(#[from] joshi_core::service::PairingCapabilityGenerationError),
    #[error(transparent)]
    OrdinaryPairing(#[from] OrdinaryPairingError),
    #[error(transparent)]
    PairingProtocol(#[from] PairingError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error("system clock is unavailable")]
    Clock,
    #[error("pairing token file must be a regular, non-symlink, owner-only file of bounded size")]
    UnsafePairingFile,
    #[error("fixture inspector must bind an explicit loopback address, got {0}")]
    NonLoopback(SocketAddr),
    #[error("offline fixture inspector encountered an impossible positive qualification bit")]
    FixtureInspectorQualification,
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
