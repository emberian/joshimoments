use clap::{Args, Parser, Subcommand};
use joshi_core::{
    EMBEDDED_FIXTURE, MAX_FIXTURE_DOCUMENT_BYTES,
    g0_inspector_smoke::G0InspectorSmokeError,
    pairing::OrdinaryPairingError,
    query_json,
    readiness::{WALKING_MATERIAL, run_offline_readiness},
    run_fixture,
    service::{CoreService, PairingCapability},
    venue_readout::{MountedVenueReadouts, VenueAccountsCapture, VenueReadoutPolicy},
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
    /// Execute all 37 frozen G0 rows using non-qualifying in-process fault injection.
    Wave5G0FaultLedger {
        #[arg(long)]
        state: PathBuf,
    },
    /// Kill one child at an exact G0 fault boundary and recover the same offline state.
    Wave5G0ProcessKillScenario {
        #[arg(long)]
        state: PathBuf,
        #[arg(long)]
        scenario_id: String,
    },
    /// Terminate a child at every mapped G0 boundary and account for each exact prefix.
    Wave5G0ProcessKillLedger {
        #[arg(long)]
        state: PathBuf,
    },
    /// Panic one child at an exact scheduled G0 panic boundary and recover the same state.
    Wave5G0PanicScenario {
        #[arg(long)]
        state: PathBuf,
        #[arg(long)]
        scenario_id: String,
    },
    /// Execute every frozen panic row with a real child panic and retain a partial ledger.
    Wave5G0PanicLedger {
        #[arg(long)]
        state: PathBuf,
    },
    /// Internal parked child used only by the parent process-kill scenario runner.
    #[command(hide = true)]
    Wave5G0FaultKillChild {
        #[arg(long)]
        state: PathBuf,
        #[arg(long)]
        scenario_id: String,
        #[arg(long)]
        marker: PathBuf,
    },
    /// Internal child used only by the parent literal-panic scenario runner.
    #[command(hide = true)]
    Wave5G0FaultPanicChild {
        #[arg(long)]
        state: PathBuf,
        #[arg(long)]
        scenario_id: String,
        #[arg(long)]
        marker: PathBuf,
    },
    /// Persist and reopen the exact fixture-only Wave 6 N00 registration.
    Wave6ProgramRegistration {
        #[arg(long)]
        state: PathBuf,
    },
    /// Join one genuine W5 source occurrence to W6 as an input census, not a market atlas.
    Wave6StoreInputCensus {
        #[arg(long)]
        state: PathBuf,
    },
    /// Join the exact gapped W5 act and later browser report as non-promoting W6 input.
    Wave6OperatorEvidenceInput {
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
        /// Opt in to durable ordinary browser pairing for this exact loopback origin.
        #[arg(long)]
        ordinary_pairing_origin: Option<String>,
        /// Add operator and presentation evidence-write scopes to the one-time code.
        #[arg(long, requires = "ordinary_pairing_origin")]
        ordinary_pairing_evidence_write: bool,
    },
    /// Serve one real catalog's derived Glass scene through durable ordinary pairing.
    LiveSurfaceInspect {
        #[arg(long, default_value = "127.0.0.1:43119")]
        listen: SocketAddr,
        #[arg(long, default_value = "http://127.0.0.1:4173")]
        glass_origin: String,
        /// Directory holding the real catalog (`catalog.sqlite`, `blobs/`, `exports/`).
        #[arg(long)]
        catalog: PathBuf,
        /// Directory for this process's writable overlay; the real catalog is never written.
        #[arg(long)]
        state: PathBuf,
        /// Registered source identity to derive the surface from.
        #[arg(long, default_value = "helius.http.solana.v1")]
        source_id: String,
        /// Mint you state a retained Pump `candles` window belongs to.
        ///
        /// A candles response is a bare OHLCV array and the retained acquisition keeps the
        /// `{mint}` path template plus a one-way request fingerprint, so the catalog itself
        /// cannot say which coin a window is for. Passing this attaches the bars to that mint and
        /// renders the binding as `attested` evidence beside the `observed` bars. Leaving it off
        /// leaves the window unattached and says so in the report.
        #[arg(long, value_name = "MINT")]
        candles_subject: Option<String>,
        /// Path to one `joshi.venue_accounts_capture.v1` file to mount pre-trade readouts from.
        ///
        /// The capture is one retained `getMultipleAccounts` response plus the three things that
        /// body cannot state about itself: the address list it was requested with, the commitment
        /// it was requested at, and when the bytes arrived. Every readout served from it carries
        /// that age, and this process never reads the network to refresh it. Leaving this off
        /// serves no readouts at all, and the cockpit says so rather than showing blanks.
        #[arg(long, value_name = "PATH")]
        venue_accounts: Option<PathBuf>,
    },
    /// Mark one real mint over a real catalog through the paired route and reopen after restart.
    LiveGestureWalk {
        #[arg(long)]
        catalog: PathBuf,
        #[arg(long)]
        state: PathBuf,
        #[arg(long, default_value = "helius.http.solana.v1")]
        source_id: String,
        #[arg(long, default_value = "http://127.0.0.1:4173")]
        glass_origin: String,
    },
    /// Journal real words over a real catalog through the paired route and read them back after
    /// restart through the operator readback route.
    LiveJournalWalk {
        #[arg(long)]
        catalog: PathBuf,
        #[arg(long)]
        state: PathBuf,
        #[arg(long, default_value = "helius.http.solana.v1")]
        source_id: String,
        #[arg(long, default_value = "http://127.0.0.1:4173")]
        glass_origin: String,
        /// The exact words of the entry, kept verbatim. Blank words are refused, never stored.
        #[arg(long)]
        words: String,
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
#[allow(clippy::too_many_lines)] // The CLI keeps each bounded offline subcommand visibly routed.
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
        Some(Command::Wave5G0FaultLedger { state }) => {
            let report =
                joshi_core::wave5_g0_fault_root::run_wave5_g0_executed_fault_ledger(&state).await?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave5G0ProcessKillScenario { state, scenario_id }) => {
            let report = joshi_core::wave5_g0_fault_root::run_wave5_g0_process_kill_scenario(
                &state,
                &scenario_id,
            )
            .await?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave5G0ProcessKillLedger { state }) => {
            let report =
                joshi_core::wave5_g0_fault_root::run_wave5_g0_process_kill_ledger(&state).await?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave5G0PanicScenario { state, scenario_id }) => {
            let report =
                joshi_core::wave5_g0_fault_root::run_wave5_g0_panic_scenario(&state, &scenario_id)
                    .await?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave5G0PanicLedger { state }) => {
            let report = joshi_core::wave5_g0_fault_root::run_wave5_g0_panic_ledger(&state).await?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave5G0FaultKillChild {
            state,
            scenario_id,
            marker,
        }) => {
            joshi_core::wave5_g0_fault_root::run_wave5_g0_process_kill_child(
                &state,
                &scenario_id,
                &marker,
            )
            .await?;
        }
        Some(Command::Wave5G0FaultPanicChild {
            state,
            scenario_id,
            marker,
        }) => {
            joshi_core::wave5_g0_fault_root::run_wave5_g0_panic_child(
                &state,
                &scenario_id,
                &marker,
            )
            .await?;
        }
        Some(Command::Wave6ProgramRegistration { state }) => {
            let report = joshi_core::wave6_registration::run_wave6_program_registration(&state)?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave6StoreInputCensus { state }) => {
            let report = joshi_core::wave6_store_input::run_wave6_store_input_census(&state)?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Wave6OperatorEvidenceInput { state }) => {
            let report =
                joshi_core::wave6_operator_input::run_wave6_operator_evidence_input(&state).await?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Serve {
            listen,
            state,
            companion_installation_id,
            pairing_token_file,
            ordinary_pairing_origin,
            ordinary_pairing_evidence_write,
        }) => {
            if !listen.ip().is_loopback() {
                return Err(CliError::NonLoopback(listen));
            }
            let mut store = SqliteStore::open(
                store_config(&state, "joshi-local-core")?,
                StoreMode::SingleWriter,
            )?;
            store.migrate(now()?)?;
            let pairing_token = read_pairing_token(&pairing_token_file)?;
            let pairing = PairingCapability::from_hex(&pairing_token)?;
            if let Some(origin) = ordinary_pairing_origin {
                let origin = loopback_pairing_origin(origin)?;
                let origin_label = origin.as_str().to_owned();
                let listener = tokio::net::TcpListener::bind(listen).await?;
                let (core, launcher) = CoreService::with_sqlite_pairing(
                    store,
                    Some(companion_installation_id),
                    pairing,
                    origin,
                    PairingConfig::default(),
                )?;
                let scopes = ordinary_pairing_scopes(ordinary_pairing_evidence_write);
                let scope_names = pairing_scope_names(&scopes);
                let issued = launcher.issue_code(scopes)?;
                eprintln!(
                    "ordinary pairing enabled for {}; one-time code (scopes: {}; no signing or execution): {}",
                    origin_label,
                    scope_names,
                    issued.code.as_str()
                );
                axum::serve(listener, core.router()).await?;
            } else {
                CoreService::new(store, Some(companion_installation_id), pairing)
                    .serve(listen)
                    .await?;
            }
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
            let store = joshi_core::wave5_g0::prepare_g0_browser_inspector_store(&state, &report)?;
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
            let issued = launcher.issue_code(vec![
                PairingScope::CockpitRead,
                PairingScope::PresentationEvidenceWrite,
            ])?;
            eprintln!(
                "offline-fixture one-time pairing code (Cockpit read + presentation evidence; no signing or execution): {}",
                issued.code.as_str()
            );
            axum::serve(listener, core.router()).await?;
        }
        Some(Command::LiveSurfaceInspect {
            listen,
            glass_origin,
            catalog,
            state,
            source_id,
            candles_subject,
            venue_accounts,
        }) => {
            if !listen.ip().is_loopback() {
                return Err(CliError::NonLoopback(listen));
            }
            let venues = venue_accounts
                .as_deref()
                .map(mount_venue_readouts)
                .transpose()?;
            let options = joshi_core::live_surface::LiveSurfaceOptions {
                attested_candle_subject: candles_subject,
            };
            let mounted = joshi_core::live_gesture::mount_live_surface_with(
                &catalog, &state, &source_id, &options,
            )?;
            let scene_id = mounted.surface.scene_id.clone();
            let surface = serde_json::to_string(&mounted.surface)?;
            // The binding of bars to a coin is the one thing on this screen the catalog cannot
            // check, so it is said out loud on the way past rather than left in a JSON field.
            if mounted.surface.candle_bars_rendered > 0 {
                eprintln!(
                    "candles: {} bar(s) attached by {}. The retained bytes name no coin; if that                      mint is wrong, every bar you are about to look at belongs to another market.",
                    mounted.surface.candle_bars_rendered, mounted.surface.candle_subject_binding,
                );
            } else if mounted.surface.candle_windows_unattributed > 0 {
                eprintln!(
                    "candles: {} retained window(s) hold bars that reached no candidate, because                      a Pump candles response names no coin. Re-run with --candles-subject <MINT>                      to state which coin they are.",
                    mounted.surface.candle_windows_unattributed,
                );
            }
            let origin = loopback_pairing_origin(glass_origin)?;
            if let Some(venues) = &venues {
                eprintln!(
                    "venue readouts mounted at slot {}: {}. These numbers are as old as that \
                     capture and this process never refreshes them.",
                    venues.context_slot(),
                    if venues.mints().is_empty() {
                        "no mint".to_owned()
                    } else {
                        venues.mints().join(", ")
                    }
                );
                for unassembled in venues.unassembled() {
                    eprintln!(
                        "venue readouts: {} was not assembled. {}",
                        unassembled.address, unassembled.reason
                    );
                }
            }
            let (core, launcher) = CoreService::with_sqlite_pairing_mounting_venues(
                mounted.store,
                None,
                PairingCapability::generate_os_random()?,
                origin,
                PairingConfig::default(),
                Some(mounted.view),
                venues,
            )?;
            let listener = tokio::net::TcpListener::bind(listen).await?;
            let issued = launcher.issue_code(vec![
                PairingScope::CockpitRead,
                PairingScope::OperatorEvidenceWrite,
            ])?;
            println!("{surface}");
            eprintln!(
                "live surface mounted from {}: scene {scene_id}\n\
                 Glass needs: VITE_JOSHI_CORE_URL=http://{listen} \
                 VITE_JOSHI_LAUNCH_SCENE_ID={scene_id}\n\
                 one-time pairing code (Cockpit read + operator evidence; no signing or \
                 execution): {}",
                catalog.display(),
                issued.code.as_str()
            );
            axum::serve(listener, core.router()).await?;
        }
        Some(Command::LiveGestureWalk {
            catalog,
            state,
            source_id,
            glass_origin,
        }) => {
            let report = joshi_core::live_gesture::run_live_gesture_walk(
                &catalog,
                &state,
                &source_id,
                &glass_origin,
            )
            .await?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::LiveJournalWalk {
            catalog,
            state,
            source_id,
            glass_origin,
            words,
        }) => {
            let report = joshi_core::live_journal::run_live_journal_walk(
                &catalog,
                &state,
                &source_id,
                &glass_origin,
                &words,
            )
            .await?;
            println!("{}", serde_json::to_string(&report)?);
        }
        Some(Command::Fixture(fixture)) => run_fixture_command(fixture).await?,
        None => run_fixture_command(arguments.fixture).await?,
    }
    Ok(())
}

/// Reads one venue account capture off disk and assembles every readout its bytes support.
///
/// Nothing about this touches the network. The capture is retained provider bytes and the
/// arithmetic over them is pure, which is exactly why the age it carries has to be shown: a
/// readout assembled from a capture taken minutes ago is a readout about minutes ago.
fn mount_venue_readouts(path: &std::path::Path) -> Result<MountedVenueReadouts, CliError> {
    let bytes = std::fs::read(path)?;
    let capture: VenueAccountsCapture = serde_json::from_slice(&bytes)
        .map_err(|error| CliError::VenueCapture(error.to_string()))?;
    MountedVenueReadouts::from_capture(&capture, &VenueReadoutPolicy::study_m0_defaults())
        .map_err(|error| CliError::VenueCapture(error.to_string()))
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

fn loopback_pairing_origin(value: String) -> Result<PairingOrigin, CliError> {
    let origin = PairingOrigin::new(value)?;
    if !origin.as_str().starts_with("http://") {
        return Err(CliError::NonLoopbackPairingOrigin);
    }
    let authority = origin
        .as_str()
        .split_once("://")
        .map(|(_, authority)| authority)
        .ok_or(CliError::NonLoopbackPairingOrigin)?;
    if is_exact_loopback_authority(authority) {
        Ok(origin)
    } else {
        Err(CliError::NonLoopbackPairingOrigin)
    }
}

fn is_exact_loopback_authority(authority: &str) -> bool {
    ["localhost", "127.0.0.1", "[::1]"].iter().any(|host| {
        authority == *host
            || authority
                .strip_prefix(&format!("{host}:"))
                .is_some_and(|port| port.parse::<u16>().is_ok_and(|port| port != 0))
    })
}

fn ordinary_pairing_scopes(evidence_write: bool) -> Vec<PairingScope> {
    if evidence_write {
        vec![
            PairingScope::CockpitRead,
            PairingScope::OperatorEvidenceWrite,
            PairingScope::PresentationEvidenceWrite,
            PairingScope::ReplayRead,
        ]
    } else {
        vec![PairingScope::CockpitRead, PairingScope::ReplayRead]
    }
}

fn pairing_scope_names(scopes: &[PairingScope]) -> String {
    scopes
        .iter()
        .map(|scope| match scope {
            PairingScope::CockpitRead => "cockpit_read",
            PairingScope::OperatorEvidenceWrite => "operator_evidence_write",
            PairingScope::PresentationEvidenceWrite => "presentation_evidence_write",
            PairingScope::ReplayRead => "replay_read",
        })
        .collect::<Vec<_>>()
        .join(",")
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
    Wave5G0FaultLedger(#[from] joshi_core::wave5_g0_fault_root::G0ExecutedFaultLedgerError),
    #[error(transparent)]
    Wave6Registration(#[from] joshi_core::wave6_registration::Wave6RegistrationError),
    #[error(transparent)]
    Wave6StoreInput(#[from] joshi_core::wave6_store_input::Wave6StoreInputCensusError),
    #[error(transparent)]
    Wave6OperatorInput(#[from] joshi_core::wave6_operator_input::Wave6OperatorEvidenceInputError),
    #[error(transparent)]
    LiveGesture(#[from] joshi_core::live_gesture::LiveGestureError),
    #[error(transparent)]
    LiveJournal(#[from] joshi_core::live_journal::LiveJournalError),
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
    #[error("local Core service must bind an explicit loopback address, got {0}")]
    NonLoopback(SocketAddr),
    #[error(
        "ordinary pairing origin must use plain HTTP and exact loopback host localhost, 127.0.0.1, or [::1]"
    )]
    NonLoopbackPairingOrigin,
    #[error("offline fixture inspector encountered an impossible positive qualification bit")]
    FixtureInspectorQualification,
    #[error("fixture exceeds {MAX_FIXTURE_DOCUMENT_BYTES} bytes: {0}")]
    FixtureTooLarge(usize),
    #[error("venue account capture could not be mounted: {0}")]
    VenueCapture(String),
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::{PermissionsExt as _, symlink};

    const TOKEN: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";

    #[test]
    fn g0_browser_inspector_uses_a_restartable_v21_overlay_without_mutating_v10_truth() {
        let root = tempfile::tempdir().expect("temporary G0 browser-inspector state");
        let report = joshi_core::wave5_g0::run_wave5_g0_source_publication(root.path())
            .expect("frozen V10 G0 component");
        let first = joshi_core::wave5_g0::prepare_g0_browser_inspector_store(root.path(), &report)
            .expect("first browser-inspector overlay");
        assert_eq!(first.catalog_schema().unwrap().as_str(), "joshi.sqlite.v22");
        drop(first);

        let second = joshi_core::wave5_g0::prepare_g0_browser_inspector_store(root.path(), &report)
            .expect("restart browser-inspector overlay");
        assert_eq!(
            second.catalog_schema().unwrap().as_str(),
            "joshi.sqlite.v22"
        );
        drop(second);

        let source = SqliteStore::open(
            joshi_core::wave5_g0::offline_fixture_store_config(root.path()).unwrap(),
            StoreMode::ReadOnly,
        )
        .expect("frozen source catalog");
        assert_eq!(
            source.catalog_schema().unwrap().as_str(),
            "joshi.sqlite.v10"
        );
    }

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

    #[test]
    fn serve_defaults_to_unmounted_ordinary_pairing() {
        let arguments = Arguments::try_parse_from([
            "joshi-core",
            "serve",
            "--state",
            "/tmp/joshi-state",
            "--companion-installation-id",
            "installation-1",
            "--pairing-token-file",
            "/tmp/joshi-token",
        ])
        .expect("default serve arguments");
        let Some(Command::Serve {
            ordinary_pairing_origin,
            ordinary_pairing_evidence_write,
            ..
        }) = arguments.command
        else {
            panic!("serve command");
        };
        assert!(ordinary_pairing_origin.is_none());
        assert!(!ordinary_pairing_evidence_write);
    }

    #[test]
    fn evidence_write_requires_explicit_ordinary_pairing_origin() {
        let parsed = Arguments::try_parse_from([
            "joshi-core",
            "serve",
            "--state",
            "/tmp/joshi-state",
            "--companion-installation-id",
            "installation-1",
            "--pairing-token-file",
            "/tmp/joshi-token",
            "--ordinary-pairing-evidence-write",
        ]);
        assert!(parsed.is_err());

        let arguments = Arguments::try_parse_from([
            "joshi-core",
            "serve",
            "--state",
            "/tmp/joshi-state",
            "--companion-installation-id",
            "installation-1",
            "--pairing-token-file",
            "/tmp/joshi-token",
            "--ordinary-pairing-origin",
            "http://127.0.0.1:4173",
            "--ordinary-pairing-evidence-write",
        ])
        .expect("explicit origin and evidence write");
        let Some(Command::Serve {
            ordinary_pairing_origin,
            ordinary_pairing_evidence_write,
            ..
        }) = arguments.command
        else {
            panic!("serve command");
        };
        assert_eq!(
            ordinary_pairing_origin.as_deref(),
            Some("http://127.0.0.1:4173")
        );
        assert!(ordinary_pairing_evidence_write);
    }

    #[test]
    fn ordinary_pairing_origin_is_exactly_loopback_and_scopes_are_bounded() {
        for value in [
            "http://localhost:4173",
            "http://127.0.0.1:8443",
            "http://[::1]:4173",
        ] {
            assert_eq!(
                loopback_pairing_origin(value.to_owned())
                    .expect("loopback origin")
                    .as_str(),
                value
            );
        }
        for value in [
            "https://127.0.0.1:8443",
            "https://example.com",
            "http://localhost.evil:4173",
            "http://127.0.0.2:4173",
            "http://localhost:0",
        ] {
            assert!(matches!(
                loopback_pairing_origin(value.to_owned()),
                Err(CliError::NonLoopbackPairingOrigin)
            ));
        }

        assert_eq!(
            ordinary_pairing_scopes(false),
            vec![PairingScope::CockpitRead, PairingScope::ReplayRead]
        );
        assert_eq!(
            ordinary_pairing_scopes(true),
            vec![
                PairingScope::CockpitRead,
                PairingScope::OperatorEvidenceWrite,
                PairingScope::PresentationEvidenceWrite,
                PairingScope::ReplayRead,
            ]
        );
    }
}
