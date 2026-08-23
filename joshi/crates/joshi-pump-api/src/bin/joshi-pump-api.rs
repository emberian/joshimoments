use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::str::FromStr as _;
use std::sync::Arc;

use clap::{Parser, Subcommand};
use joshi_pump_api::catalog::RouteSpec;
use joshi_pump_api::normalize::{reject_duplicate_keys, schema_fingerprint};
use joshi_pump_api::{
    AccessClass, Acquisition, ClientConfig, CredentialFileSession, FetchOutcome, IdentityStore,
    LogicalRequest, NoSession, ParityInput, PumpApiClient, RequestParameters, RouteId,
    RowProjectionReviewV1, SchemaRegistry, SessionProvider, SiwsSession, SiwsSessionProvider,
    SuppliedReview, WalletSigner, compare, decide_row_projection_trust, normalize,
};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;

#[derive(Debug, Parser)]
#[command(name = "joshi-pump-api")]
#[command(about = "Bounded read-only Pump source-edge client")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Print the pinned route/access catalog. Performs no network I/O.
    Catalog,
    /// Compute a structural fingerprint for a reviewed JSON fixture.
    Schema { input: PathBuf },
    /// Normalize one saved acquisition using an explicit schema registry.
    Normalize {
        input: PathBuf,
        registry: PathBuf,
        output: PathBuf,
    },
    /// Audit one retained acquisition or fetch outcome for the known source-level failure
    /// families. No network I/O.
    ///
    /// The input is sniffed by its `contract` line: a `joshi.pump_api.fetch_outcome.v1` audits
    /// every attempt plus the outcome-level absence accounting; a bare
    /// `joshi.pump_api.acquisition.v1` audits that one acquisition. Reviews of either kind may
    /// be supplied repeatedly; each attempt selects the review matching its route, preferring
    /// the kind measured to govern that route. A check that cannot decide reports UNDECIDABLE
    /// with its reason — it never passes by default.
    Audit {
        input: PathBuf,
        #[arg(long = "review")]
        reviews: Vec<PathBuf>,
    },
    /// Re-run the row-projection gate offline over one saved fetch outcome. No network I/O.
    ///
    /// This exists so that an amended row-projection review can be applied to bytes that were
    /// already retained, instead of spending another provider request on a population that has
    /// moved. The original decision made at acquisition time stays in the store; this prints a
    /// fresh decision against the review given here, stamped with its own decision instant.
    RowGate { outcome: PathBuf, review: PathBuf },
    /// Compare companion and direct exact response bodies under strict parity preconditions.
    Parity {
        companion: PathBuf,
        direct: PathBuf,
        output: PathBuf,
        #[arg(long, default_value_t = 100)]
        max_differences: usize,
    },
    /// Perform one explicitly enabled GET and write a mode-0600 acquisition envelope.
    Fetch {
        request: PathBuf,
        state_dir: PathBuf,
        output: PathBuf,
        #[arg(long)]
        session_file: Option<PathBuf>,
        /// Wallet key file for a Sign-In-With-Solana session. The wallet signs ONLY the login
        /// timestamp; the resulting read-only session is used for authenticated routes. Mutually
        /// exclusive with --session-file.
        #[arg(long)]
        wallet_file: Option<PathBuf>,
        #[arg(long)]
        enable_observed_product_route: bool,
        #[arg(long)]
        enable_authenticated_route: bool,
    },
    /// Sign the SIWS login challenge with a wallet file and report the session's identity and
    /// expiry. Prints NO token. Proves the login works without retaining anything.
    AuthProbe {
        #[arg(long)]
        wallet_file: PathBuf,
    },
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RequestFile {
    contract: String,
    route_id: String,
    #[serde(default)]
    path: BTreeMap<String, String>,
    #[serde(default)]
    query: BTreeMap<String, String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct CatalogRow {
    route_id: String,
    origin: String,
    path_template: String,
    access_class: String,
    stability: String,
    transport: String,
    pagination: String,
    ordering: String,
    default_enabled: bool,
}

#[tokio::main]
async fn main() {
    if let Err(error) = run(Cli::parse()).await {
        eprintln!("joshi-pump-api: {error}");
        std::process::exit(2);
    }
}

#[allow(clippy::too_many_lines)] // CLI dispatch keeps each command's mutation boundary explicit.
async fn run(cli: Cli) -> Result<(), Box<dyn std::error::Error>> {
    match cli.command {
        Command::Catalog => {
            let rows = RouteId::ALL
                .into_iter()
                .map(RouteSpec::for_id)
                .map(|spec| CatalogRow {
                    route_id: spec.id.to_string(),
                    origin: spec.origin.to_owned(),
                    path_template: spec.path_template.to_owned(),
                    access_class: spec.access.to_string(),
                    stability: spec.stability.to_string(),
                    transport: spec.transport.to_string(),
                    pagination: format!("{:?}", spec.pagination).to_ascii_lowercase(),
                    ordering: spec.ordering.to_owned(),
                    default_enabled: spec.collection_enabled,
                })
                .collect::<Vec<_>>();
            println!("{}", serde_json::to_string_pretty(&rows)?);
        }
        Command::Schema { input } => {
            let bytes = fs::read(input)?;
            reject_duplicate_keys(&bytes)?;
            let raw: Box<RawValue> = serde_json::from_slice(&bytes)?;
            println!("{}", schema_fingerprint(&raw)?);
        }
        Command::Audit { input, reviews } => {
            #[derive(Debug, Deserialize)]
            struct ContractOnly {
                contract: String,
            }
            let bytes = fs::read(&input)?;
            reject_duplicate_keys(&bytes)?;
            let supplied = reviews
                .iter()
                .map(|path| {
                    let review_bytes = fs::read(path)?;
                    SuppliedReview::from_slice(&review_bytes)
                        .map_err(|error| format!("{}: {error}", path.display()).into())
                })
                .collect::<Result<Vec<_>, Box<dyn std::error::Error>>>()?;
            let head: ContractOnly = serde_json::from_slice(&bytes)?;
            let decided_at =
                time::OffsetDateTime::now_utc().format(time::macros::format_description!(
                    "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
                ))?;
            let (report, findings): (serde_json::Value, Vec<joshi_pump_api::AuditFinding>) =
                match head.contract.as_str() {
                    "joshi.pump_api.fetch_outcome.v1" => {
                        let outcome: FetchOutcome = serde_json::from_slice(&bytes)?;
                        let audit =
                            joshi_pump_api::audit_fetch_outcome(&outcome, &supplied, &decided_at)?;
                        let mut findings = audit.outcome_findings.clone();
                        for attempt in &audit.attempt_audits {
                            findings.extend(attempt.findings.iter().cloned());
                        }
                        (serde_json::to_value(&audit)?, findings)
                    }
                    "joshi.pump_api.acquisition.v1" => {
                        let acquisition: Acquisition = serde_json::from_slice(&bytes)?;
                        let review =
                            joshi_pump_api::select_review(&supplied, &acquisition.route_id);
                        let audit =
                            joshi_pump_api::audit_acquisition(&acquisition, review, &decided_at)?;
                        let findings = audit.findings.clone();
                        (serde_json::to_value(&audit)?, findings)
                    }
                    other => {
                        return Err(format!(
                            "unsupported input contract {other:?}; expected a fetch outcome or \
                             an acquisition"
                        )
                        .into());
                    }
                };
            println!("{}", serde_json::to_string_pretty(&report)?);
            let count = |severity: joshi_pump_api::AuditSeverity| {
                findings
                    .iter()
                    .filter(|finding| finding.severity == severity)
                    .count()
            };
            eprintln!(
                "audit: {} finding(s) — {} defect, {} gap, {} hazard, {} observation",
                findings.len(),
                count(joshi_pump_api::AuditSeverity::Defect),
                count(joshi_pump_api::AuditSeverity::Gap),
                count(joshi_pump_api::AuditSeverity::Hazard),
                count(joshi_pump_api::AuditSeverity::Observation),
            );
        }
        Command::RowGate { outcome, review } => {
            let outcome: FetchOutcome = strict_file(&outcome)?;
            let review_bytes = fs::read(review)?;
            reject_duplicate_keys(&review_bytes)?;
            let review = RowProjectionReviewV1::from_slice(&review_bytes)?;
            let acquisition = outcome
                .attempts
                .last()
                .ok_or("outcome carries no attempt to decide")?;
            let decided_at =
                time::OffsetDateTime::now_utc().format(time::macros::format_description!(
                    "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
                ))?;
            let decision = decide_row_projection_trust(acquisition, Some(&review), &decided_at)?;
            println!("{}", serde_json::to_string_pretty(&decision)?);
        }
        Command::Normalize {
            input,
            registry,
            output,
        } => {
            let acquisition: Acquisition = strict_file(&input)?;
            let registry = SchemaRegistry::from_slice(&fs::read(registry)?)?;
            write_private_new(
                &output,
                &serde_json::to_vec_pretty(&normalize(&acquisition, &registry))?,
            )?;
        }
        Command::Parity {
            companion,
            direct,
            output,
            max_differences,
        } => {
            let companion: ParityInput = strict_file(&companion)?;
            let direct: ParityInput = strict_file(&direct)?;
            let report = compare(&companion, &direct, max_differences);
            write_private_new(&output, &serde_json::to_vec_pretty(&report)?)?;
        }
        Command::AuthProbe { wallet_file } => {
            let signer = WalletSigner::from_file(&wallet_file)?;
            let session = SiwsSession::login(&signer).await?;
            let report = serde_json::json!({
                "contract": "joshi.pump_api.auth_probe.v1",
                "address": signer.address(),
                "sessionLive": session.is_live(),
                "expiresAt": session.expires_at().format(&time::format_description::well_known::Rfc3339)?,
                "note": "the wallet signed only the login timestamp; no token is printed or retained",
            });
            println!("{}", serde_json::to_string_pretty(&report)?);
        }
        Command::Fetch {
            request,
            state_dir,
            output,
            session_file,
            wallet_file,
            enable_observed_product_route,
            enable_authenticated_route,
        } => {
            let request_file: RequestFile = strict_file(&request)?;
            if request_file.contract != "joshi.pump_api.request.v1" {
                return Err("request contract/version must be joshi.pump_api.request.v1".into());
            }
            let route = RouteId::from_str(&request_file.route_id)?;
            let spec = RouteSpec::for_id(route);
            let mut config = ClientConfig::default();
            match spec.access {
                AccessClass::OfficiallyDescribedPublic => {}
                AccessClass::ObservedPublicProduct if enable_observed_product_route => {
                    config.enabled_routes.insert(route);
                }
                AccessClass::AuthenticatedUserSession if enable_authenticated_route => {
                    config.enabled_routes.insert(route);
                }
                AccessClass::ObservedPublicProduct => {
                    return Err(
                        "observed product route requires --enable-observed-product-route".into(),
                    );
                }
                AccessClass::AuthenticatedUserSession => {
                    return Err("authenticated route requires --enable-authenticated-route".into());
                }
                AccessClass::ReconnaissanceOnly => {
                    return Err("reconnaissance-only route has no direct collector".into());
                }
            }
            if session_file.is_some() && wallet_file.is_some() {
                return Err("--session-file and --wallet-file are mutually exclusive".into());
            }
            let sessions: Arc<dyn SessionProvider> = match (session_file, wallet_file) {
                (Some(path), _) => Arc::new(CredentialFileSession::new(path)),
                (None, Some(wallet)) => {
                    let signer = WalletSigner::from_file(&wallet)?;
                    let session = SiwsSession::login(&signer).await?;
                    Arc::new(SiwsSessionProvider::new(session))
                }
                (None, None) => Arc::new(NoSession),
            };
            let identity = IdentityStore::open(state_dir)?;
            let client = PumpApiClient::new(config, identity, sessions)?;
            let request = LogicalRequest {
                route,
                parameters: RequestParameters {
                    path: request_file.path,
                    query: request_file.query,
                },
            };
            let outcome: FetchOutcome = client.fetch(&request).await?;
            write_private_new(&output, &serde_json::to_vec_pretty(&outcome)?)?;
        }
    }
    Ok(())
}

fn strict_file<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, Box<dyn std::error::Error>> {
    let bytes = fs::read(path)?;
    reject_duplicate_keys(&bytes)?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn write_private_new(path: &Path, bytes: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
    let parent = path.parent().ok_or("output path has no parent")?;
    fs::create_dir_all(parent)?;
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(bytes)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    File::open(parent)?.sync_all()?;
    Ok(())
}
