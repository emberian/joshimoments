//! Render one surface out of a real operational catalog, and print it.
//!
//! This is the CLI end of the S1 path: point it at a catalog file and an Ember-approved surface
//! profile, and it derives the population, the facts, the gaps and both clocks from committed rows
//! and prints the rendered body a person reads. It opens the catalog **read-only** and writes
//! nothing to it.
//!
//! ```text
//! render-catalog render <catalog.sqlite> <profile.json> <commit-seq|latest> [render-limit]
//! render-catalog seal-profile <profile-in.json> <profile-out.json>
//! ```
//!
//! `render` prints the exact rendered bytes on stdout and the canonical render head on stderr, so
//! that `render-catalog render ... > surface.txt` leaves a file whose `sha256sum` is the
//! `bodyDigest` the head names.
//!
//! `seal-profile` recomputes a profile's own digest. A profile is Ember-approved configuration,
//! not evidence: sealing one is a pure function of its contents and says nothing about any market.
//! Every number the rendered surface carries still comes from the catalog.

use std::{
    path::{Path, PathBuf},
    process::ExitCode,
    time::Duration,
};

use joshi_surface::{DailyUseSurfaceProfileV1, SurfaceCatalogReadback, render_surface};

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("render-catalog: {message}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("render") => {
            let catalog = PathBuf::from(args.next().ok_or("missing <catalog.sqlite>")?);
            let profile = PathBuf::from(args.next().ok_or("missing <profile.json>")?);
            let cutoff = args.next().ok_or("missing <commit-seq|latest>")?;
            let limit = match args.next() {
                Some(value) => value.parse().map_err(|_| "render limit is not a number")?,
                None => 100_usize,
            };
            render(&catalog, &profile, &cutoff, limit)
        }
        Some("seal-profile") => {
            let input = PathBuf::from(args.next().ok_or("missing <profile-in.json>")?);
            let output = PathBuf::from(args.next().ok_or("missing <profile-out.json>")?);
            seal(&input, &output)
        }
        other => Err(format!(
            "unknown command {other:?}; expected `render` or `seal-profile`"
        )),
    }
}

fn render(catalog: &Path, profile: &Path, cutoff: &str, limit: usize) -> Result<(), String> {
    let bytes = std::fs::read(profile).map_err(|error| format!("read profile: {error}"))?;
    let profile: DailyUseSurfaceProfileV1 =
        serde_json::from_slice(&bytes).map_err(|error| format!("decode profile: {error}"))?;
    profile
        .validate()
        .map_err(|error| format!("the profile is not approved bytes: {error}"))?;

    let readback = SurfaceCatalogReadback::open(catalog, Duration::from_secs(5))
        .map_err(|error| format!("open catalog read-only: {error}"))?;
    let cutoff_commit_seq = match cutoff {
        "latest" => readback
            .latest_commit_seq()
            .map_err(|error| format!("read commit order: {error}"))?
            .ok_or("the catalog has committed nothing, so there is no cutoff to render at")?,
        value => value
            .parse()
            .map_err(|_| "cutoff must be a commit sequence or `latest`")?,
    };
    let derived = readback
        .derive_surface_cut(&profile, cutoff_commit_seq, limit)
        .map_err(|error| format!("derive surface: {error}"))?;
    let rendered = render_surface(&derived).map_err(|error| format!("render surface: {error}"))?;
    let head = rendered
        .head()
        .canonical_bytes()
        .map_err(|error| format!("encode head: {error}"))?;
    print!("{}", rendered.body_text());
    eprintln!("{}", String::from_utf8_lossy(&head));
    Ok(())
}

fn seal(input: &Path, output: &Path) -> Result<(), String> {
    let bytes = std::fs::read(input).map_err(|error| format!("read profile: {error}"))?;
    let mut profile: DailyUseSurfaceProfileV1 =
        serde_json::from_slice(&bytes).map_err(|error| format!("decode profile: {error}"))?;
    profile.profile_digest = profile
        .computed_digest()
        .map_err(|error| format!("compute profile digest: {error}"))?;
    let sealed = profile
        .canonical_bytes()
        .map_err(|error| format!("the profile is not a valid approved profile: {error}"))?;
    std::fs::write(output, &sealed).map_err(|error| format!("write profile: {error}"))?;
    eprintln!("sealed {} bytes to {}", sealed.len(), output.display());
    Ok(())
}
