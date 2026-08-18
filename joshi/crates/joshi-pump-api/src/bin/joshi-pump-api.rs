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
    SchemaRegistry, SessionProvider, compare, normalize,
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
        #[arg(long)]
        enable_observed_product_route: bool,
        #[arg(long)]
        enable_authenticated_route: bool,
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
        Command::Fetch {
            request,
            state_dir,
            output,
            session_file,
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
            let sessions: Arc<dyn SessionProvider> = match session_file {
                Some(path) => Arc::new(CredentialFileSession::new(path)),
                None => Arc::new(NoSession),
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
