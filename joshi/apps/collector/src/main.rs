mod census;
mod keeper;
mod live;

use census::{CensusOptions, PUMP_PROGRAM, PUMPSWAP_PROGRAM, census_readback, run_census};
use clap::{Parser, Subcommand};
use joshi_domain::UtcTimestamp;
use joshi_spool::{
    KeyMaterial, LocalSpool, ProtectionMetadata, SegmentProtector, SpoolConfig, inspect_segment,
};
use joshi_supervisor::{
    CollectorRuntime, FakeProviderHarness, FakeProviderSchedule, MAX_PROVIDER_RUN_PLAN_BYTES,
    ProviderRunner, QueueLimits, RetryPolicy, RuntimeDocumentSet, Supervisor, SupervisorConfig,
    SupervisorHealthV1, SyntheticRuntimeOutcomeAdapter, parse_provider_run_plan_exact,
    replay_spool, synthetic_c0_json_runner,
};
use keeper::{KeeperOptions, run_keeper};
use live::{DEFAULT_HELIUS_KEY_PATH, LiveIngestOptions, ingest_live, store_readback};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File},
    io::Read as _,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use zeroize::Zeroize as _;

const MAX_RUNTIME_DOCUMENT_BYTES: u64 = 4 * 1024 * 1024;
const MAX_C0_FIXTURE_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Debug, Parser)]
#[command(name = "joshi-collector")]
#[command(about = "Bounded collector runtime, continuity, replay, and fake-provider harness")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Run one exact registered, no-network C0 fixture occurrence into the local spool.
    Run {
        #[arg(long)]
        root: PathBuf,
        #[arg(long)]
        registration: PathBuf,
        #[arg(long)]
        build: PathBuf,
        #[arg(long = "source-tree")]
        source_tree: PathBuf,
        #[arg(long)]
        config: PathBuf,
        #[arg(long)]
        budget: PathBuf,
        #[arg(long)]
        privacy: PathBuf,
        #[arg(long = "surface-profile")]
        surface_profile: PathBuf,
        #[arg(long)]
        plan: PathBuf,
        /// Exact JSON body emitted once by the sealed synthetic source.
        #[arg(long)]
        fixture: PathBuf,
    },
    /// Verify retained local spool bytes without opening a network connection.
    Replay {
        #[arg(long)]
        root: PathBuf,
        /// Optional owner-only raw 32-byte key file for one private key ID present in the spool.
        #[arg(long)]
        private_key_file: Option<PathBuf>,
    },
    /// Run the deterministic no-network fake source for an accelerated or wall-clock duration.
    FakeProvider {
        #[arg(long)]
        root: PathBuf,
        #[arg(long)]
        fixture: PathBuf,
        #[arg(long)]
        hours: u64,
        #[arg(long)]
        realtime: bool,
    },
    /// Print the last durable local health snapshot; this opens no listener.
    Health {
        #[arg(long)]
        root: PathBuf,
    },
    /// Perform bounded authenticated Solana reads and durably commit the exact provider frames.
    IngestLive {
        /// Catalog directory; created and migrated when absent.
        #[arg(long)]
        root: PathBuf,
        /// Base58 Solana address whose recent signatures are read.
        #[arg(long)]
        wallet: String,
        /// Signature page size requested from the provider.
        #[arg(long, default_value_t = 10)]
        limit: u32,
        /// Hard ceiling on provider requests for the whole occurrence.
        #[arg(long = "max-requests", default_value_t = 25)]
        max_requests: u32,
        /// Maximum transactions fetched from the head of the signature page.
        #[arg(long, default_value_t = 3)]
        transactions: u32,
        /// Owner-only credential file, read once at adapter startup and never rendered.
        #[arg(long = "key-file", default_value = DEFAULT_HELIUS_KEY_PATH)]
        key_file: PathBuf,
    },
    /// Reopen a catalog read-only and print what one retained observation payload actually holds.
    StoreReadback {
        #[arg(long)]
        root: PathBuf,
    },
    /// Take one bounded Pump/PumpSwap census and durably retain its observations, coverage
    /// window and every gap the bounded reads created.
    Census {
        /// Catalog directory; created and migrated when absent.
        #[arg(long)]
        root: PathBuf,
        /// Program address to census. Repeatable; defaults to Pump and `PumpSwap`.
        #[arg(long = "program", default_values_t = [PUMP_PROGRAM.to_owned(), PUMPSWAP_PROGRAM.to_owned()])]
        programs: Vec<String>,
        /// Signature page size requested per program.
        #[arg(long = "signature-limit", default_value_t = 25)]
        signature_limit: u32,
        /// Maximum transactions hydrated from the head of each program's page.
        #[arg(long = "transactions-per-program", default_value_t = 8)]
        transactions_per_program: u32,
        /// Hard ceiling on provider requests for the whole occurrence.
        #[arg(long = "max-requests", default_value_t = 40)]
        max_requests: u32,
        /// Owner-only credential file, read once at adapter startup and never rendered.
        #[arg(long = "key-file", default_value = DEFAULT_HELIUS_KEY_PATH)]
        key_file: PathBuf,
    },
    /// Reopen a census catalog read-only and re-derive its mints, windows and gaps from the store.
    CensusReadback {
        #[arg(long)]
        root: PathBuf,
    },
    /// Run the long-lived keeper: bounded acquisition cycles on a cadence, forever, into one
    /// durable catalog, with hard request budgets, rate-limit backoff, and a heartbeat file.
    Keeper {
        /// Keeper configuration file; see ops/keeper.toml for the starter watch set.
        #[arg(long)]
        config: PathBuf,
        /// Stop cleanly after this many acquisition cycles (for bounded proof runs).
        #[arg(long = "max-cycles")]
        max_cycles: Option<u64>,
    },
}

fn main() {
    if let Err(error) = run(Cli::parse()) {
        eprintln!("collector command failed: {error}");
        std::process::exit(1);
    }
}

// One dispatch arm per subcommand; splitting it would only hide the surface.
#[allow(clippy::too_many_lines)]
fn run(cli: Cli) -> Result<(), Box<dyn std::error::Error>> {
    match cli.command {
        Command::Run {
            root,
            registration,
            build,
            source_tree,
            config,
            budget,
            privacy,
            surface_profile,
            plan,
            fixture,
        } => run_c0_occurrence(C0Occurrence {
            root,
            registration,
            build,
            source_tree,
            config,
            budget,
            privacy,
            surface_profile,
            plan,
            fixture,
        })?,
        Command::Replay {
            root,
            private_key_file,
        } => {
            require_existing_root(&root)?;
            let spool = LocalSpool::open(spool_config(&root))?;
            let protectors = load_replay_protectors(&spool, private_key_file.as_deref())?;
            let manifest = replay_spool(&spool, &protectors)?;
            println!("{}", serde_json::to_string_pretty(&manifest)?);
        }
        Command::FakeProvider {
            root,
            fixture,
            hours,
            realtime,
        } => {
            if hours == 0 || hours > 24 {
                return Err("--hours must be between 1 and 24 for the W4-01 canary".into());
            }
            let bytes = read_bounded(
                &fixture,
                MAX_RUNTIME_DOCUMENT_BYTES,
                "fake-provider schedule",
            )?;
            let mut schedule: FakeProviderSchedule = serde_json::from_slice(&bytes)?;
            schedule.duration_seconds = hours.saturating_mul(3_600);
            schedule.realtime = realtime;
            let mut supervisor = Supervisor::open(supervisor_config(root))?;
            let started_at = UtcTimestamp::new(time::OffsetDateTime::now_utc())?;
            supervisor.reconcile_startup(started_at)?;
            let report = FakeProviderHarness::new(schedule)?.run(&mut supervisor, started_at)?;
            println!("{}", serde_json::to_string_pretty(&report)?);
        }
        Command::Health { root } => {
            require_existing_root(&root)?;
            let path = root.join("health").join("snapshot.json");
            let bytes = read_bounded(&path, MAX_RUNTIME_DOCUMENT_BYTES, "health snapshot")?;
            let health: SupervisorHealthV1 = serde_json::from_slice(&bytes)?;
            println!("{}", serde_json::to_string_pretty(&health)?);
        }
        Command::IngestLive {
            root,
            wallet,
            limit,
            max_requests,
            transactions,
            key_file,
        } => {
            println!(
                "{}",
                ingest_live(&LiveIngestOptions {
                    root,
                    wallet,
                    limit,
                    max_requests,
                    transactions,
                    key_file,
                })?
            );
        }
        Command::StoreReadback { root } => {
            require_existing_root(&root)?;
            println!("{}", store_readback(&root)?);
        }
        Command::Census {
            root,
            programs,
            signature_limit,
            transactions_per_program,
            max_requests,
            key_file,
        } => {
            println!(
                "{}",
                run_census(&CensusOptions {
                    root,
                    programs,
                    signature_limit,
                    transactions_per_program,
                    max_requests,
                    key_file,
                })?
            );
        }
        Command::CensusReadback { root } => {
            require_existing_root(&root)?;
            println!("{}", census_readback(&root)?);
        }
        Command::Keeper { config, max_cycles } => {
            println!("{}", run_keeper(&KeeperOptions { config, max_cycles })?);
        }
    }
    Ok(())
}

/// Every exact document path of one registered no-network C0 occurrence.
struct C0Occurrence {
    root: PathBuf,
    registration: PathBuf,
    build: PathBuf,
    source_tree: PathBuf,
    config: PathBuf,
    budget: PathBuf,
    privacy: PathBuf,
    surface_profile: PathBuf,
    plan: PathBuf,
    fixture: PathBuf,
}

fn run_c0_occurrence(paths: C0Occurrence) -> Result<(), Box<dyn std::error::Error>> {
    require_existing_root(&paths.root)?;
    let exact_registration = read_bounded(
        &paths.registration,
        MAX_RUNTIME_DOCUMENT_BYTES,
        "registration",
    )?;
    let exact_build = read_bounded(&paths.build, MAX_RUNTIME_DOCUMENT_BYTES, "build")?;
    let exact_source_tree = read_bounded(
        &paths.source_tree,
        MAX_RUNTIME_DOCUMENT_BYTES,
        "source tree",
    )?;
    let exact_configuration =
        read_bounded(&paths.config, MAX_RUNTIME_DOCUMENT_BYTES, "configuration")?;
    let exact_budget = read_bounded(&paths.budget, MAX_RUNTIME_DOCUMENT_BYTES, "budget")?;
    let exact_privacy = read_bounded(&paths.privacy, MAX_RUNTIME_DOCUMENT_BYTES, "privacy")?;
    let exact_surface = read_bounded(
        &paths.surface_profile,
        MAX_RUNTIME_DOCUMENT_BYTES,
        "daily-use surface profile",
    )?;
    let plan_maximum = u64::try_from(MAX_PROVIDER_RUN_PLAN_BYTES)?;
    let plan_bytes = read_bounded(&paths.plan, plan_maximum, "provider plan")?;
    let fixture_body = read_bounded(&paths.fixture, MAX_C0_FIXTURE_BYTES, "C0 fixture")?;

    let plan = parse_provider_run_plan_exact(&plan_bytes)?;
    let started_at = UtcTimestamp::new(time::OffsetDateTime::now_utc())?;
    let mut runner = synthetic_c0_json_runner(plan, fixture_body, started_at)?;
    let supervisor = Supervisor::open(supervisor_config(paths.root))?;
    let mut runtime = CollectorRuntime::open(
        RuntimeDocumentSet {
            exact_registration: &exact_registration,
            exact_build: &exact_build,
            exact_source_tree: &exact_source_tree,
            exact_configuration: &exact_configuration,
            exact_budget: &exact_budget,
            exact_privacy: &exact_privacy,
            exact_daily_use_surface_profile: &exact_surface,
        },
        supervisor,
        runner.validated_plan(),
        started_at,
        0,
    )?;
    let mut adapter = SyntheticRuntimeOutcomeAdapter::new();
    let report = runtime.run_to_completion(&mut runner, &mut adapter, started_at, 0)?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}

fn supervisor_config(root: PathBuf) -> SupervisorConfig {
    SupervisorConfig {
        spool: spool_config(&root),
        root,
        queue: QueueLimits::default(),
        retry: RetryPolicy::default(),
        shutdown_deadline: Duration::from_secs(30),
        maximum_spool_bytes_per_utc_day: 1024 * 1024 * 1024,
    }
}

fn spool_config(root: &Path) -> SpoolConfig {
    SpoolConfig {
        root: root.join("spool"),
        max_segment_bytes: 32 * 1024 * 1024,
        max_entries_per_segment: 256,
        max_total_bytes: 8 * 1024 * 1024 * 1024,
        control_reserve_bytes: 64 * 1024 * 1024,
        max_transfer_chunk_bytes: 1024 * 1024,
    }
}

fn require_existing_root(root: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if !root.is_dir() {
        return Err(format!(
            "collector root {} is not an existing directory",
            root.display()
        )
        .into());
    }
    Ok(())
}

fn read_bounded(
    path: &Path,
    maximum_bytes: u64,
    label: &str,
) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut file = File::open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(format!("{label} path {} is not a regular file", path.display()).into());
    }
    if metadata.len() > maximum_bytes {
        return Err(format!(
            "{label} file {} exceeds the {}-byte local bound",
            path.display(),
            maximum_bytes
        )
        .into());
    }
    let read_limit = maximum_bytes
        .checked_add(1)
        .ok_or("bounded file read limit overflow")?;
    let mut bytes = Vec::new();
    file.by_ref().take(read_limit).read_to_end(&mut bytes)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes {
        return Err(format!(
            "{label} file {} grew beyond the {}-byte local bound while reading",
            path.display(),
            maximum_bytes
        )
        .into());
    }
    Ok(bytes)
}

fn load_replay_protectors(
    spool: &LocalSpool,
    key_path: Option<&Path>,
) -> Result<BTreeMap<String, Arc<SegmentProtector>>, Box<dyn std::error::Error>> {
    let mut key_ids = BTreeSet::new();
    for closure in spool.list_segments()? {
        let bytes = spool.read_segment(&closure)?;
        if let ProtectionMetadata::AuthenticatedPrivate { key_id, .. } =
            inspect_segment(&bytes)?.header.protection
        {
            key_ids.insert(key_id);
        }
    }
    let Some(key_path) = key_path else {
        return Ok(BTreeMap::new());
    };
    if key_ids.len() != 1 {
        return Err("--private-key-file requires exactly one private key ID in the spool".into());
    }
    require_owner_only_regular_file(key_path)?;
    let mut bytes = fs::read(key_path)?;
    if bytes.len() != 32 {
        bytes.zeroize();
        return Err("private replay key file must contain exactly 32 raw bytes".into());
    }
    let mut key = [0_u8; 32];
    key.copy_from_slice(&bytes);
    bytes.zeroize();
    let key_id = key_ids.into_iter().next().expect("one key ID checked");
    let protector = SegmentProtector::new(KeyMaterial::new(key_id.clone(), key)?)?;
    key.zeroize();
    Ok(BTreeMap::from([(key_id, Arc::new(protector))]))
}

#[cfg(unix)]
fn require_owner_only_regular_file(path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    use std::os::unix::fs::MetadataExt as _;

    let metadata = fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file() || metadata.mode() & 0o077 != 0 {
        return Err("private key file must be regular and deny all group/other permissions".into());
    }
    Ok(())
}

#[cfg(not(unix))]
fn require_owner_only_regular_file(_path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    Err("private replay keys are unsupported without Unix permission checks".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_surface_requires_every_exact_document_and_fixture() {
        let parsed = Cli::try_parse_from([
            "joshi-collector",
            "run",
            "--root",
            "/collector",
            "--registration",
            "registration.json",
            "--build",
            "build.json",
            "--source-tree",
            "source-tree.json",
            "--config",
            "config.json",
            "--budget",
            "budget.json",
            "--privacy",
            "privacy.json",
            "--surface-profile",
            "surface.json",
            "--plan",
            "plan.json",
            "--fixture",
            "fixture.json",
        ])
        .expect("complete C0 invocation parses");
        assert!(matches!(parsed.command, Command::Run { .. }));

        let missing_privacy = Cli::try_parse_from([
            "joshi-collector",
            "run",
            "--root",
            "/collector",
            "--registration",
            "registration.json",
            "--build",
            "build.json",
            "--source-tree",
            "source-tree.json",
            "--config",
            "config.json",
            "--budget",
            "budget.json",
            "--surface-profile",
            "surface.json",
            "--plan",
            "plan.json",
            "--fixture",
            "fixture.json",
        ]);
        assert!(missing_privacy.is_err());
    }
}
