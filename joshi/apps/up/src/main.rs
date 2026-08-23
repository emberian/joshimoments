//! joshi-up — the one command that brings a sitting-in-it JOSHI session up.
//!
//! Before this existed, an attended session took four commands across three terminals plus a
//! human ferrying a pairing code between two of them. This binary runs the same three programs
//! — the keeper (real acquisition into a durable catalog), the core follow surface (scenes
//! derived from that catalog, served with ordinary pairing), and the Glass cockpit — wires
//! their hand-offs, and prints the one thing left that is genuinely the human's: the one-time
//! pairing code.
//!
//! It orchestrates and refuses; it never substitutes. Every hand-off value (catalog path,
//! scene id, pairing code) comes from the producing process's own output, not from this
//! binary's assumptions, and every preflight refusal names its fix. If any child dies, the
//! others are taken down and the death is reported — a half-up session that looks up is worse
//! than no session.

use std::path::{Path, PathBuf};
use std::process::{ExitStatus, Stdio};
use std::time::Duration;

use clap::Parser;
use tokio::io::{AsyncBufReadExt, AsyncRead, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::watch;

#[derive(Parser)]
#[command(
    name = "joshi-up",
    about = "Bring up a full attended JOSHI session: keeper, follow surface, cockpit."
)]
struct Options {
    /// Keeper configuration file. Its `root` locates the durable catalog this session mounts.
    #[arg(long, default_value = "ops/keeper.toml")]
    config: PathBuf,
    /// Core follow-surface listen address (loopback only; core itself enforces this).
    #[arg(long, default_value = "127.0.0.1:43219")]
    listen: String,
    /// Port the Glass cockpit dev server binds. Also fixes the pairing origin, so the port is
    /// strict: a drifted port would break pairing silently, which is refused instead.
    #[arg(long, default_value_t = 4173)]
    glass_port: u16,
    /// Registered source identity the surface follows. The default is the price source; pass
    /// `helius.http.solana.v1` for wallet-activity scenes instead.
    #[arg(long, default_value = "pump.api.product.v1")]
    source_id: String,
    /// Writable state directory for the cockpit overlay and pairing store. Never inside the
    /// keeper's catalog directory. Defaults to `<keeper root>/cockpit-state`.
    #[arg(long)]
    state: Option<PathBuf>,
    /// Mount the cockpit over the existing catalog without starting the keeper. The catalog
    /// must already exist; nothing will advance it while you watch.
    #[arg(long)]
    no_keeper: bool,
    /// Seconds between the follow surface's source-catalog polls.
    #[arg(long, default_value_t = 20)]
    poll_seconds: u64,
    /// How long to wait for a first-run keeper to commit its first cycle before giving up.
    #[arg(long, default_value_t = 180)]
    keeper_wait_seconds: u64,
    /// How long to keep retrying the surface mount while the keeper warms a cold catalog. A
    /// quiet coin's candle windows can stay empty for a while; ten minutes covers one full
    /// candle cadence before giving up with the real refusal.
    #[arg(long, default_value_t = 600)]
    surface_wait_seconds: u64,
    /// Optional `joshi.venue_accounts_capture.v1` file, passed through to the follow surface
    /// so held coins show pre-trade readouts.
    #[arg(long)]
    venue_accounts: Option<PathBuf>,
    /// Optional mint attestation for coin-anonymous candle windows retained before the mint
    /// path segment was public; passed through to the follow surface.
    #[arg(long, value_name = "MINT")]
    candles_subject: Option<String>,
}

fn fail(message: &str) -> ! {
    eprintln!("joshi-up: {message}");
    std::process::exit(1);
}

/// The repo root, located by ascending from the executable and then from the working
/// directory until a directory holds both `Cargo.toml` and `apps/glass/package.json`.
fn locate_repo_root() -> PathBuf {
    let mut anchors: Vec<PathBuf> = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        anchors.push(exe);
    }
    if let Ok(cwd) = std::env::current_dir() {
        anchors.push(cwd);
    }
    for anchor in &anchors {
        let mut probe: &Path = anchor;
        while let Some(parent) = probe.parent() {
            if parent.join("Cargo.toml").is_file()
                && parent.join("apps/glass/package.json").is_file()
            {
                return parent.to_path_buf();
            }
            probe = parent;
        }
    }
    fail(
        "could not locate the repo root (a directory holding Cargo.toml and apps/glass/package.json) from the executable path or the working directory; run from inside ~/dev/joshi",
    );
}

/// The keeper's state root, read from the keeper's own config so this binary and the keeper
/// can never disagree about where the catalog lives. Relative paths resolve against the config
/// file's directory, exactly as the keeper resolves them.
fn keeper_root_from_config(config: &Path) -> PathBuf {
    let text = std::fs::read_to_string(config).unwrap_or_else(|error| {
        fail(&format!(
            "keeper config {} is unreadable ({error}); pass --config or create it from ops/keeper.toml",
            config.display()
        ))
    });
    let parsed: toml::Value = text.parse().unwrap_or_else(|error| {
        fail(&format!(
            "keeper config {} is not valid TOML ({error})",
            config.display()
        ))
    });
    let Some(root) = parsed.get("root").and_then(|value| value.as_str()) else {
        fail(&format!(
            "keeper config {} declares no top-level `root`; the keeper would refuse it too",
            config.display()
        ));
    };
    let root_path = PathBuf::from(root);
    if root_path.is_absolute() {
        root_path
    } else {
        config
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join(root_path)
    }
}

/// A sibling binary next to this executable, refused with the build command when absent. Its
/// build time is printed because a STALE sibling is this launcher's quietest failure mode: the
/// first cold start ran a keeper built nine hours before the mint-binding work landed, and the
/// only symptom was a catalog whose candle windows named no subject. This launcher cannot know
/// which commit a binary encodes, but it can make the build time visible next to the name.
fn sibling_binary(name: &str) -> PathBuf {
    let exe = std::env::current_exe()
        .unwrap_or_else(|error| fail(&format!("cannot locate own executable: {error}")));
    let dir = exe
        .parent()
        .unwrap_or_else(|| fail("own executable has no parent directory"));
    let candidate = dir.join(name);
    if !candidate.is_file() {
        fail(&format!(
            "{name} is not built beside this binary ({}); run: cargo build --offline -p joshi-collector -p joshi-core -p joshi-up",
            candidate.display()
        ));
    }
    match candidate.metadata().and_then(|meta| meta.modified()) {
        Ok(modified) => {
            let age = modified.elapsed().map_or_else(
                |_| "the future".to_owned(),
                |elapsed| {
                    format!(
                        "{}h {}m ago",
                        elapsed.as_secs() / 3600,
                        (elapsed.as_secs() % 3600) / 60
                    )
                },
            );
            eprintln!("joshi-up: using {name} built {age} — if work landed since, rebuild it");
        }
        Err(error) => eprintln!("joshi-up: using {name} (build time unreadable: {error})"),
    }
    candidate
}

/// Forward one output stream as prefixed lines, optionally publishing values a later stage
/// needs (the scene id the core prints for Glass).
fn forward_lines<R>(
    reader: R,
    prefix: &'static str,
    scene_tx: Option<watch::Sender<Option<String>>>,
) where
    R: AsyncRead + Unpin + Send + 'static,
{
    tokio::spawn(async move {
        let mut lines = BufReader::new(reader).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if let Some(tx) = &scene_tx
                && let Some(position) = line.find("VITE_JOSHI_LAUNCH_SCENE_ID=")
            {
                let value = line[position + "VITE_JOSHI_LAUNCH_SCENE_ID=".len()..]
                    .split_whitespace()
                    .next()
                    .unwrap_or("")
                    .to_owned();
                if !value.is_empty() {
                    let _ = tx.send(Some(value));
                }
            }
            eprintln!("{prefix} | {line}");
        }
    });
}

/// How long ago the keeper last rewrote its heartbeat file, from the file's own mtime.
fn heartbeat_age(root: &Path) -> Option<Duration> {
    root.join("heartbeat.json")
        .metadata()
        .and_then(|meta| meta.modified())
        .ok()
        .and_then(|modified| modified.elapsed().ok())
}

/// The heartbeat's own words, if the keeper has written any, for honest progress lines.
fn heartbeat_note(root: &Path) -> Option<String> {
    let bytes = std::fs::read(root.join("heartbeat.json")).ok()?;
    let value: serde_json::Value = serde_json::from_slice(&bytes).ok()?;
    let note = value.get("note")?.as_str()?;
    Some(note.to_owned())
}

/// SIGTERM to one child, by pid, through /bin/kill — this workspace forbids unsafe code, and
/// TERM (not KILL) is what lets the keeper record its own shutdown reason durably.
async fn term_child(child: &Child) {
    if let Some(pid) = child.id() {
        let _ = Command::new("/bin/kill")
            .args(["-TERM", &pid.to_string()])
            .status()
            .await;
    }
}

async fn shutdown_child(name: &str, child: &mut Option<Child>, grace: Duration) {
    let Some(mut process) = child.take() else {
        return;
    };
    term_child(&process).await;
    match tokio::time::timeout(grace, process.wait()).await {
        Ok(Ok(status)) => eprintln!("joshi-up: {name} exited: {}", describe_exit(status)),
        Ok(Err(error)) => eprintln!("joshi-up: {name} wait failed: {error}"),
        Err(_) => {
            eprintln!(
                "joshi-up: {name} did not exit within {}s; killing",
                grace.as_secs()
            );
            let _ = process.start_kill();
            let _ = process.wait().await;
        }
    }
}

fn describe_exit(status: ExitStatus) -> String {
    status.code().map_or_else(
        || format!("terminated by signal ({status})"),
        |code| format!("status {code}"),
    )
}

/// Wait on a child that may not exist without ever resolving for the absent one.
async fn wait_or_pending(child: Option<&mut Child>) -> std::io::Result<ExitStatus> {
    match child {
        Some(process) => process.wait().await,
        None => std::future::pending().await,
    }
}

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
#[allow(clippy::too_many_lines)] // The bring-up is one legible sequence; splitting it would
// scatter the ordering that is the whole point.
async fn main() {
    let options = Options::parse();
    let repo_root = locate_repo_root();

    let config = if options.config.is_absolute() {
        options.config.clone()
    } else {
        repo_root.join(&options.config)
    };
    let keeper_root = keeper_root_from_config(&config);
    let catalog_dir = keeper_root.join("catalog");
    let state_dir = options
        .state
        .clone()
        .unwrap_or_else(|| keeper_root.join("cockpit-state"));
    let glass_dir = repo_root.join("apps/glass");
    let glass_origin = format!("http://127.0.0.1:{}", options.glass_port);

    // Preflight, refusing early with the fix instead of failing three stages deep.
    let collector_bin = sibling_binary("joshi-collector");
    let core_bin = sibling_binary("joshi-core");
    if !glass_dir.join("node_modules").is_dir() {
        fail("apps/glass/node_modules is absent; run: cd apps/glass && pnpm install");
    }
    if options.no_keeper && !catalog_dir.join("catalog.sqlite").is_file() {
        fail(&format!(
            "--no-keeper was passed but no catalog exists at {}; run once without --no-keeper, or point --config at a keeper config whose root holds one",
            catalog_dir.display()
        ));
    }
    if !options.no_keeper {
        let key_file = std::fs::read_to_string(&config)
            .ok()
            .and_then(|text| text.parse::<toml::Value>().ok())
            .and_then(|value| value.get("key_file")?.as_str().map(PathBuf::from));
        if let Some(key) = key_file
            && !key.is_file()
        {
            fail(&format!(
                "the keeper's credential file {} does not exist; the keeper would refuse at startup",
                key.display()
            ));
        }
    }
    std::fs::create_dir_all(&state_dir).unwrap_or_else(|error| {
        fail(&format!(
            "cannot create state directory {}: {error}",
            state_dir.display()
        ))
    });

    // Stage 1: the keeper, unless the operator asked to watch a still catalog — or one is
    // already alive. The catalog is single-writer: a keeper running under launchd (or another
    // terminal) must be ADOPTED, never doubled. Liveness is read from the heartbeat file's
    // mtime — the keeper rewrites it every tick, so a heartbeat older than a few ticks means a
    // stopped keeper, and a fresh one means this launcher must not own that lifecycle.
    let mut keeper: Option<Child> = None;
    let external_keeper =
        heartbeat_age(&keeper_root).is_some_and(|age| age < Duration::from_secs(90));
    if external_keeper {
        eprintln!(
            "joshi-up: a keeper is already running (heartbeat {} is fresh); adopting it — it will not be started or stopped by this session",
            keeper_root.join("heartbeat.json").display()
        );
    } else if options.no_keeper {
        eprintln!(
            "joshi-up: --no-keeper: mounting over the existing catalog at {}; nothing will advance it",
            catalog_dir.display()
        );
    } else {
        eprintln!(
            "joshi-up: starting keeper (config {}, catalog {})",
            config.display(),
            catalog_dir.display()
        );
        let mut child = Command::new(&collector_bin)
            .args(["keeper", "--config"])
            .arg(&config)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .unwrap_or_else(|error| fail(&format!("could not start the keeper: {error}")));
        forward_lines(child.stdout.take().expect("piped"), "keeper", None);
        forward_lines(child.stderr.take().expect("piped"), "keeper", None);
        keeper = Some(child);
    }

    // Stage 2: wait until the catalog exists before mounting a surface over it. On a restart
    // it already does and this is instant; on first run the keeper's first committed cycle
    // creates it, and progress is reported in the keeper's own heartbeat words.
    if !catalog_dir.join("catalog.sqlite").is_file() {
        eprintln!(
            "joshi-up: waiting up to {}s for the keeper's first committed cycle to create {}",
            options.keeper_wait_seconds,
            catalog_dir.join("catalog.sqlite").display()
        );
        let deadline =
            tokio::time::Instant::now() + Duration::from_secs(options.keeper_wait_seconds);
        loop {
            if catalog_dir.join("catalog.sqlite").is_file() {
                break;
            }
            if tokio::time::Instant::now() >= deadline {
                shutdown_child("keeper", &mut keeper, Duration::from_secs(10)).await;
                fail(&format!(
                    "no catalog appeared within {}s; the keeper's own lines above say why (budget, credential, provider)",
                    options.keeper_wait_seconds
                ));
            }
            if let Some(process) = keeper.as_mut()
                && let Ok(Some(status)) = process.try_wait()
            {
                fail(&format!(
                    "the keeper exited before committing a catalog ({}); its lines above say why",
                    describe_exit(status)
                ));
            }
            if let Some(note) = heartbeat_note(&keeper_root) {
                eprintln!("joshi-up: keeper heartbeat: {note}");
            }
            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    }

    // Stage 3: the follow surface, retried while the keeper warms the catalog. A cold catalog
    // legitimately refuses to mount — a quiet coin's first candle taps can hold zero bars, and
    // a scene cannot exist before any window can name a subject — so a mount refusal while the
    // keeper is still advancing the catalog is "not yet", not "broken". The scene id and the
    // pairing code are read from what the core itself produces, never assumed.
    eprintln!(
        "joshi-up: mounting follow surface over {} (source {})",
        catalog_dir.display(),
        options.source_id
    );
    let pairing_code_file = state_dir.join("pairing-code");
    let surface_deadline =
        tokio::time::Instant::now() + Duration::from_secs(options.surface_wait_seconds);
    let (core, scene_id) = loop {
        let (scene_tx, mut scene_rx) = watch::channel(None::<String>);
        let mut core_cmd = Command::new(&core_bin);
        core_cmd
            .args(["live-surface-inspect", "--follow"])
            .arg("--catalog")
            .arg(&catalog_dir)
            .arg("--state")
            .arg(&state_dir)
            .args(["--listen", &options.listen])
            .args(["--glass-origin", &glass_origin])
            .args(["--source-id", &options.source_id])
            .args(["--poll-seconds", &options.poll_seconds.to_string()])
            .arg("--pairing-code-file")
            .arg(&pairing_code_file);
        if let Some(venues) = &options.venue_accounts {
            core_cmd.arg("--venue-accounts").arg(venues);
        }
        if let Some(mint) = &options.candles_subject {
            core_cmd.arg("--candles-subject").arg(mint);
        }
        let mut core = core_cmd
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .unwrap_or_else(|error| {
                fail(&format!("could not start the core follow surface: {error}"))
            });
        forward_lines(core.stdout.take().expect("piped"), "core", None);
        forward_lines(core.stderr.take().expect("piped"), "core", Some(scene_tx));

        let scene_or_exit = tokio::time::timeout(Duration::from_secs(90), async {
            loop {
                tokio::select! {
                    changed = scene_rx.changed() => {
                        if let Some(scene) = scene_rx.borrow().clone() {
                            return Ok(scene);
                        }
                        if changed.is_err() {
                            // The core's stderr closed without a scene line; its exit says why.
                            return Err(core.wait().await);
                        }
                    }
                    status = core.wait() => return Err(Ok(status.unwrap_or_else(|error| {
                        fail(&format!("waiting on the core follow surface failed: {error}"))
                    }))),
                }
            }
        })
        .await;

        match scene_or_exit {
            Ok(Ok(scene)) => break (core, scene),
            Ok(Err(exit)) => {
                let described = exit.map_or_else(|error| error.to_string(), describe_exit);
                if options.no_keeper {
                    shutdown_child("keeper", &mut keeper, Duration::from_secs(10)).await;
                    fail(&format!(
                        "the follow surface refused to mount ({described}) and --no-keeper means nothing will change; its lines above say why"
                    ));
                }
                if tokio::time::Instant::now() >= surface_deadline {
                    shutdown_child("keeper", &mut keeper, Duration::from_secs(10)).await;
                    fail(&format!(
                        "the follow surface still cannot mount after {}s ({described}); if the watched coins are quiet their candle windows stay empty — its lines above say what is missing",
                        options.surface_wait_seconds
                    ));
                }
                eprintln!(
                    "joshi-up: surface cannot mount yet ({described}); retrying in 20s while the keeper advances the catalog"
                );
                tokio::time::sleep(Duration::from_secs(20)).await;
            }
            Err(_) => {
                shutdown_child("core", &mut Some(core), Duration::from_secs(10)).await;
                shutdown_child("keeper", &mut keeper, Duration::from_secs(10)).await;
                fail(
                    "the follow surface is running but printed no scene id within 90s; its lines above say why",
                );
            }
        }
    };

    // Stage 4: the cockpit, told exactly what the core told us. --strictPort because the
    // pairing origin embeds the port: silent drift would break pairing invisibly.
    eprintln!("joshi-up: starting Glass cockpit on {glass_origin} (scene {scene_id})");
    let mut glass = Command::new("pnpm")
        .args([
            "dev",
            "--port",
            &options.glass_port.to_string(),
            "--strictPort",
        ])
        .current_dir(&glass_dir)
        .env("VITE_JOSHI_LIVE_SURFACE", "1")
        .env("VITE_JOSHI_CORE_URL", format!("http://{}", options.listen))
        .env("VITE_JOSHI_LAUNCH_SCENE_ID", &scene_id)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .unwrap_or_else(|error| {
            fail(&format!(
                "could not start pnpm dev in {} ({error}); is pnpm on PATH?",
                glass_dir.display()
            ))
        });
    forward_lines(glass.stdout.take().expect("piped"), "glass", None);
    forward_lines(glass.stderr.take().expect("piped"), "glass", None);

    let glass_addr = format!("127.0.0.1:{}", options.glass_port);
    let reachable = tokio::time::timeout(Duration::from_mins(1), async {
        loop {
            if tokio::net::TcpStream::connect(&glass_addr).await.is_ok() {
                return;
            }
            tokio::time::sleep(Duration::from_millis(300)).await;
        }
    })
    .await;
    if reachable.is_err() {
        shutdown_child("glass", &mut Some(glass), Duration::from_secs(10)).await;
        shutdown_child("core", &mut Some(core), Duration::from_secs(10)).await;
        shutdown_child("keeper", &mut keeper, Duration::from_secs(10)).await;
        fail("the cockpit did not answer on its port within 60s; its lines above say why");
    }

    let pairing_code = std::fs::read_to_string(&pairing_code_file).map_or_else(
        |error| {
            fail(&format!(
                "the core reported a mounted surface but its pairing code file {} is unreadable ({error})",
                pairing_code_file.display()
            ))
        },
        |text| text.trim().to_owned(),
    );

    println!();
    println!("JOSHI is up.");
    println!();
    println!("  cockpit   {glass_origin}");
    println!("  pairing   {pairing_code}");
    println!("            (one-time; Cockpit read + operator evidence; no signing, no execution)");
    println!("  feed      http://{}/api/v1/glass/scenes", options.listen);
    if external_keeper {
        println!(
            "  keeper    already running elsewhere (adopted); heartbeat {}",
            keeper_root.join("heartbeat.json").display()
        );
    } else if options.no_keeper {
        println!("  keeper    not running (--no-keeper); the catalog will not advance");
    } else {
        println!(
            "  keeper    {}",
            keeper_root.join("heartbeat.json").display()
        );
    }
    println!();
    println!("Open the cockpit and enter the pairing code. If the code is consumed or expires,");
    println!("a fresh one is written to {}.", pairing_code_file.display());
    println!("Ctrl-C takes everything down in order.");
    println!();

    // Supervise. Any child dying takes the session down loudly; a half-up session that looks
    // up is the failure mode this block exists to prevent.
    let mut sigterm = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        .unwrap_or_else(|error| fail(&format!("cannot install SIGTERM handler: {error}")));
    let mut sigint = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt())
        .unwrap_or_else(|error| fail(&format!("cannot install SIGINT handler: {error}")));

    let mut core = Some(core);
    let mut glass = Some(glass);
    let (failed, reason) = tokio::select! {
        status = wait_or_pending(keeper.as_mut()) => {
            (true, format!("the keeper exited ({})", status.map_or_else(|e| e.to_string(), describe_exit)))
        }
        status = wait_or_pending(core.as_mut()) => {
            (true, format!("the core follow surface exited ({})", status.map_or_else(|e| e.to_string(), describe_exit)))
        }
        status = wait_or_pending(glass.as_mut()) => {
            (true, format!("the Glass cockpit exited ({})", status.map_or_else(|e| e.to_string(), describe_exit)))
        }
        _ = sigint.recv() => (false, "SIGINT".to_owned()),
        _ = sigterm.recv() => (false, "SIGTERM".to_owned()),
    };

    eprintln!("joshi-up: taking the session down ({reason})");
    shutdown_child("glass", &mut glass, Duration::from_secs(10)).await;
    shutdown_child("core", &mut core, Duration::from_secs(10)).await;
    shutdown_child("keeper", &mut keeper, Duration::from_secs(15)).await;
    if failed {
        eprintln!("joshi-up: the session did not survive: {reason}");
        std::process::exit(1);
    }
    eprintln!("joshi-up: down cleanly");
}
