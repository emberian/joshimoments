//! Render tests, including the restart proof.
//!
//! Every catalog here is written by the real single-writer `joshi-store`, and every rendered byte
//! comes out of a cut derived from those committed rows. The last test in this file is the one
//! that matters for the slice: it kills a real child process that wrote the catalog and rendered
//! it, and then re-derives and re-renders the same cutoff in a different process from the file
//! that survived on disk.

use std::{
    env, fs,
    io::Write as _,
    path::{Path, PathBuf},
    process::Command,
    thread,
    time::Duration,
};

use sha2::{Digest, Sha256};
use tempfile::TempDir;

use crate::{
    DerivedSurfaceV1, SURFACE_RENDER_CONTRACT, SURFACE_RENDER_MEDIA_TYPE, SurfaceCatalogReadback,
    SurfaceError, UnresolvedSurfaceInput, parse_surface_render_head, render_surface,
    test_catalog::{build_catalog_at, catalog, profile, s},
};

/// The child process of the restart proof reads its catalog root from this variable. Without it
/// the ignored child test is a no-op, so `cargo test -- --ignored` cannot hang.
const CHILD_ROOT_ENV: &str = "JOSHI_SURFACE_RESTART_CHILD_ROOT";

/// Test path of the child body, as libtest names it on the command line.
const CHILD_TEST: &str = "render_tests::restart_child";

/// The cutoff every render test uses: the whole committed history, including two coverage gaps
/// with differently shaped windows and one observation that names no subject.
const CUTOFF_LABEL: &str = "gap-bounded";

fn line_starting(body: &str, prefix: &str) -> String {
    body.lines()
        .find(|line| line.starts_with(prefix))
        .unwrap_or_else(|| panic!("no rendered line starts with {prefix}"))
        .to_owned()
}

#[test]
fn a_render_names_its_subjects_counts_cutoff_and_every_gap_window() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at(CUTOFF_LABEL), 10)
        .expect("derive");
    let rendered = render_surface(&derived).expect("render");
    let body = rendered.body_text();

    // The cutoff and the commit sequence are the catalog's own, not a caller's.
    assert_eq!(
        line_starting(body, "cutoff "),
        "cutoff 2026-08-18T10:25:00.000000Z"
    );
    assert_eq!(
        line_starting(body, "cutoffCommitSeq "),
        format!("cutoffCommitSeq {}", catalog.at(CUTOFF_LABEL))
    );

    // The subject is named, next to counts nobody typed.
    assert_eq!(
        line_starting(body, "subject \"mint-a\""),
        "subject \"mint-a\" rendered rows=1 memberships=census"
    );
    assert_eq!(
        line_starting(body, "eligibleSubjects "),
        "eligibleSubjects 2"
    );
    assert_eq!(line_starting(body, "renderedRows "), "renderedRows 1");
    assert_eq!(line_starting(body, "SUBJECTS "), "SUBJECTS 2");

    // A declared subject that was never observed is named as omitted rather than dropped.
    assert_eq!(
        line_starting(body, "subject \"mint-b\""),
        "subject \"mint-b\" omitted membership=denominator_only reason=\"not_observed_by_cutoff\""
    );

    // Both open gaps are rendered with the exact window their producer authored: one bounded by a
    // source cursor and a wall clock, one with no upper boundary at all. Neither is fully
    // expressed as a cell state, because `mint-b` carries no observation row to hang one on, and
    // the render says so on the gap line instead of quietly dropping the claim.
    assert_eq!(
        line_starting(body, "gap gapId=\"gap-pump-window\""),
        "gap gapId=\"gap-pump-window\" source=\"pump\" subject=source_wide \
         windowLower=cursor:\"cursor:pump/slot/440345530\" \
         windowUpper=wall:2026-08-18T10:24:00.000000Z durableSince=2026-08-18T10:25:00.000000Z \
         severity=\"scope_stopped\" cause=\"provider_stream_drop\" expressedInCut=no"
    );
    assert_eq!(
        line_starting(body, "gap gapId=\"gap-mint-b\""),
        "gap gapId=\"gap-mint-b\" source=\"pump\" subject=\"mint-b\" \
         windowLower=wall:2026-08-18T10:20:00.000000Z windowUpper=open \
         durableSince=2026-08-18T10:20:00.000000Z severity=\"degraded\" \
         cause=\"provider_stream_drop\" expressedInCut=no"
    );

    // The observation that names no subject is counted, so an empty population can never be read
    // as an empty catalog.
    assert_eq!(
        line_starting(body, "committedObservations "),
        "committedObservations 2"
    );
    assert_eq!(
        line_starting(body, "observationsNamingNoSubject "),
        "observationsNamingNoSubject 1"
    );
    assert!(
        body.contains("unresolved subjects_for_committed_observations"),
        "the unresolved input must be named in the body"
    );

    // Every unresolved input the derivation recorded is visible in the body.
    for input in &derived.derivation.unresolved {
        assert!(
            body.contains(&format!("unresolved {}", input.name())),
            "missing unresolved {}",
            input.name()
        );
    }

    // The head names the same things the body does.
    let head = rendered.head();
    assert_eq!(head.contract.as_str(), SURFACE_RENDER_CONTRACT);
    assert_eq!(head.media_type.as_str(), SURFACE_RENDER_MEDIA_TYPE);
    assert_eq!(head.cutoff, derived.cut.cutoff);
    assert_eq!(head.eligible_count.get(), 2);
    assert_eq!(head.rendered_subjects, vec![s("mint-a")]);
    assert_eq!(head.open_gaps.get(), 2);

    // The body digest is the plain sha256 of the exact bytes, checkable with any sha256 tool.
    assert_eq!(
        head.body_digest.as_str(),
        format!("sha256:{:x}", Sha256::digest(rendered.body()))
    );
    assert_eq!(
        usize::try_from(head.body_length.get()).expect("body length"),
        rendered.body().len()
    );
    rendered.validate().expect("the render validates itself");
}

#[test]
fn the_same_cut_renders_byte_identical_bytes_and_the_same_digest() {
    let catalog = catalog();
    let profile = profile();
    let first = render_surface(
        &catalog
            .open()
            .derive_surface_cut(&profile, catalog.at(CUTOFF_LABEL), 10)
            .expect("derive"),
    )
    .expect("render");
    // A second connection, a second derivation, a second render.
    let second = render_surface(
        &catalog
            .open()
            .derive_surface_cut(&profile, catalog.at(CUTOFF_LABEL), 10)
            .expect("derive"),
    )
    .expect("render");
    assert_eq!(first.body(), second.body());
    assert_eq!(first.head(), second.head());

    // A different cutoff is a different artifact; the digest is not a constant.
    let earlier = render_surface(
        &catalog
            .open()
            .derive_surface_cut(&profile, catalog.at("declare"), 10)
            .expect("derive"),
    )
    .expect("render");
    assert_ne!(earlier.head().body_digest, first.head().body_digest);
}

#[test]
fn an_empty_population_renders_an_explicit_absence_rather_than_silence() {
    let catalog = catalog();
    let mut profile = profile();
    for surface in &mut profile.surfaces {
        surface.source = s("never-registered");
    }
    profile.profile_digest = profile.computed_digest().expect("profile digest");
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at(CUTOFF_LABEL), 10)
        .expect("derive");
    let rendered = render_surface(&derived).expect("render");
    let body = rendered.body_text();

    assert_eq!(line_starting(body, "SUBJECTS "), "SUBJECTS 0");
    assert!(
        body.contains(
            "no subject is eligible at this cutoff: that is the absence of a declared or \
             observed subject row, not evidence that the market was empty"
        ),
        "an empty population must say what it does not know:\n{body}"
    );
    assert!(body.contains(
        "no coverage gap row is open at this cutoff: that is the absence of a gap record, not \
         evidence that coverage was complete"
    ));
    assert!(body.contains("catalog=unregistered"));
    assert!(
        derived
            .derivation
            .unresolved
            .contains(&UnresolvedSurfaceInput::SurfaceSourceNotRegistered)
    );
}

#[test]
fn a_cut_and_a_receipt_from_different_cutoffs_are_refused() {
    let catalog = catalog();
    let profile = profile();
    let early = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("declare"), 10)
        .expect("derive");
    let late = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at(CUTOFF_LABEL), 10)
        .expect("derive");
    let spliced = DerivedSurfaceV1 {
        cut: early.cut,
        derivation: late.derivation,
    };
    assert!(matches!(
        render_surface(&spliced),
        Err(SurfaceError::Contract)
    ));
}

#[test]
fn a_render_head_round_trips_and_refuses_tampered_or_noncanonical_bytes() {
    let catalog = catalog();
    let profile = profile();
    let rendered = render_surface(
        &catalog
            .open()
            .derive_surface_cut(&profile, catalog.at(CUTOFF_LABEL), 10)
            .expect("derive"),
    )
    .expect("render");
    let bytes = rendered.head().canonical_bytes().expect("canonical head");
    assert_eq!(
        &parse_surface_render_head(&bytes).expect("round trip"),
        rendered.head()
    );

    let mut padded = vec![b' '];
    padded.extend(bytes.clone());
    assert!(parse_surface_render_head(&padded).is_err());

    let mut tampered = parse_surface_render_head(&bytes).expect("round trip");
    tampered.eligible_count = joshi_domain::WireU64::new(99);
    assert!(matches!(
        tampered.validate(),
        Err(SurfaceError::DigestMismatch)
    ));
}

/// The restart proof.
///
/// A real child process writes the catalog with the real single-writer store, derives a surface
/// from those committed rows, renders it, and then blocks with the writer and the read-only
/// connection still open. This process kills it with `SIGKILL`, reaps it, reopens the catalog file
/// from disk, re-derives at the same cutoff and re-renders. The subject, the count and the digest
/// must be the ones the dead process wrote, byte for byte.
#[test]
fn a_real_process_kill_between_two_renders_returns_the_same_subject_count_and_digest() {
    let root = TempDir::new().expect("temporary root");
    let log_path = root.path().join("child.log");
    let log = fs::File::create(&log_path).expect("child log");
    let mut child = Command::new(env::current_exe().expect("test binary"))
        .args(["--exact", CHILD_TEST, "--ignored", "--nocapture"])
        .env(CHILD_ROOT_ENV, root.path())
        .stdout(log.try_clone().expect("clone log"))
        .stderr(log)
        .spawn()
        .expect("spawn the child process");

    let marker = root.path().join("child-ready");
    for _ in 0..1_200 {
        if marker.exists() {
            break;
        }
        thread::sleep(Duration::from_millis(50));
    }
    if !marker.exists() {
        child.kill().ok();
        child.wait().ok();
        panic!(
            "the child never rendered:\n{}",
            fs::read_to_string(&log_path).unwrap_or_default()
        );
    }

    // The process dies where it stands, holding an open writer and an open reader.
    child.kill().expect("kill the child process");
    let status = child.wait().expect("reap the child process");
    assert!(
        !status.success(),
        "the child must die by signal rather than exit cleanly"
    );
    #[cfg(unix)]
    {
        use std::os::unix::process::ExitStatusExt as _;
        assert_eq!(status.signal(), Some(9), "the child must be SIGKILLed");
    }

    // The writer died without closing: SQLite leaves the write-ahead log behind, and the reopen
    // below has to recover through it rather than reading a tidily checkpointed file.
    assert!(
        root.path().join("catalog.sqlite-wal").exists(),
        "a killed writer leaves its write-ahead log; a clean close would have removed it"
    );

    // Nothing of the dead process survives except the files it left on disk.
    let cutoff: u64 = fs::read_to_string(root.path().join("cutoff.txt"))
        .expect("cutoff")
        .trim()
        .parse()
        .expect("cutoff is a commit sequence");
    let body_before = fs::read(root.path().join("render.txt")).expect("rendered body");
    let head_before =
        parse_surface_render_head(&fs::read(root.path().join("head.json")).expect("rendered head"))
            .expect("the head the dead process wrote");

    // Reopen the store in this process and render the same cutoff again.
    let reopened =
        SurfaceCatalogReadback::open(&root.path().join("catalog.sqlite"), Duration::from_secs(5))
            .expect("reopen the catalog from disk");
    let derived = reopened
        .derive_surface_cut(&profile(), cutoff, 10)
        .expect("re-derive at the same cutoff");
    let again = render_surface(&derived).expect("re-render");

    assert_eq!(
        again.body(),
        body_before.as_slice(),
        "the rendered bytes changed across the kill"
    );
    assert_eq!(again.head(), &head_before);
    assert_eq!(again.head().body_digest, head_before.body_digest);
    assert_eq!(
        again.head().body_digest.as_str(),
        format!("sha256:{:x}", Sha256::digest(&body_before))
    );

    // The mint, the count and the cutoff are the ones that were rendered before the kill.
    assert_eq!(head_before.rendered_subjects, vec![s("mint-a")]);
    assert_eq!(head_before.eligible_count.get(), 2);
    assert_eq!(head_before.cutoff_commit_seq.get(), cutoff);
    assert!(
        again
            .body_text()
            .contains("subject \"mint-a\" rendered rows=1 memberships=census")
    );
}

/// The child body of the restart proof. It is `#[ignore]`d because it is not a test on its own: it
/// is spawned by the test above and it never returns.
#[test]
#[ignore = "spawned as a child by the restart proof; it blocks until it is killed"]
fn restart_child() {
    let Ok(root) = env::var(CHILD_ROOT_ENV) else {
        // Run directly with `--ignored` and no root: there is nothing to do and nothing to hang.
        return;
    };
    let root = PathBuf::from(root);
    let (_store, seq) = build_catalog_at(&root);
    let cutoff = *seq.get(CUTOFF_LABEL).expect("cutoff label");
    let catalog =
        SurfaceCatalogReadback::open(&root.join("catalog.sqlite"), Duration::from_secs(5))
            .expect("open the catalog read-only");
    let rendered = render_surface(
        &catalog
            .derive_surface_cut(&profile(), cutoff, 10)
            .expect("derive"),
    )
    .expect("render");

    durably_write(&root.join("render.txt"), rendered.body());
    durably_write(
        &root.join("head.json"),
        &rendered.head().canonical_bytes().expect("canonical head"),
    );
    durably_write(&root.join("cutoff.txt"), cutoff.to_string().as_bytes());
    durably_write(&root.join("child-ready"), b"ready\n");

    // The writer and the read-only connection stay open until the parent kills this process.
    loop {
        thread::sleep(Duration::from_secs(1));
    }
}

fn durably_write(path: &Path, bytes: &[u8]) {
    let mut file = fs::File::create(path).expect("create child output");
    file.write_all(bytes).expect("write child output");
    file.sync_all().expect("sync child output");
}

#[test]
fn the_body_separates_a_declared_unobserved_subject_from_an_observed_undeclared_one() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("census"), 10)
        .expect("derive at census cutoff");
    let rendered = render_surface(&derived).expect("render");
    let body = rendered.body_text();

    // Two different facts, two different lines. `mint-b` was in the denominator and was not
    // observed; `mint-c` was observed and was never in any denominator. A reader who cannot tell
    // them apart has been handed the exact conflation this project exists to refuse.
    assert_eq!(
        line_starting(body, "subject \"mint-b\""),
        "subject \"mint-b\" omitted membership=denominator_only reason=\"not_observed_by_cutoff\""
    );
    assert_eq!(
        line_starting(body, "subject \"mint-c\""),
        "subject \"mint-c\" rendered rows=1 memberships=observed_undeclared"
    );
    assert_eq!(
        line_starting(body, "subject \"mint-a\""),
        "subject \"mint-a\" rendered rows=1 memberships=census"
    );

    // The population states its own claim, so `eligibleSubjects` cannot be read as a denominator.
    assert_eq!(line_starting(body, "universeClosed "), "universeClosed no");
    assert_eq!(
        line_starting(body, "universeSampleOnly "),
        "universeSampleOnly yes"
    );
    assert_eq!(
        line_starting(body, "declaredSubjects "),
        "declaredSubjects 2"
    );
    assert_eq!(
        line_starting(body, "observedSubjects "),
        "observedSubjects 2"
    );
    assert_eq!(
        line_starting(body, "eligibleSubjects "),
        "eligibleSubjects 3"
    );
    assert!(body.contains("unresolved undeclared_observed_subject"));

    // One frame named both `mint-a` and `mint-c`; each is its own row rather than a collision.
    assert_eq!(line_starting(body, "ROWS "), "ROWS 2");
    assert_eq!(
        rendered.head().rendered_subjects,
        vec![s("mint-a"), s("mint-c")],
        "both subjects of the one frame are named, ordered by the cut"
    );
}
