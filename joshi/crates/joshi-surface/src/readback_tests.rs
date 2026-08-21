//! Store-readback tests.
//!
//! Every test here writes rows with the real single-writer `joshi-store` and then reads the
//! surface back through the adapter. Nothing hands the adapter a struct literal: if the derivation
//! stopped reading the catalog, these tests would fail rather than keep passing.

use std::collections::BTreeSet;

use joshi_domain::WireU64;

use crate::{
    FieldState, SurfaceGapBoundaryV1, SurfaceMembership, UnresolvedSurfaceInput,
    parse_surface_derivation_receipt, surface_event_identity,
    test_catalog::{PAYLOAD_A, PAYLOAD_CENSUS, PUMP, catalog, content_digest, profile, s, t},
};

fn cell(cut: &crate::SurfaceCutV1, subject: &str, field: &str) -> FieldState {
    cut.source_states
        .iter()
        .find(|state| state.subject.as_str() == subject && state.field.as_str() == field)
        .map(|state| state.state.clone())
        .expect("derived cell")
}

#[test]
fn population_facts_and_clocks_are_derived_from_committed_rows() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive at assert cutoff");

    // The cutoff wall time is the catalog's own commit clock, not a caller value.
    assert_eq!(derived.derivation.cutoff, t("2026-08-18T10:05:00.000000Z"));
    assert_eq!(derived.cut.cutoff, derived.derivation.cutoff);

    // The population is declared coverage scope union observed subjects, recomputed here.
    let subjects: Vec<_> = derived
        .cut
        .universe
        .eligible_subjects
        .iter()
        .map(|value| value.as_str().to_owned())
        .collect();
    assert_eq!(subjects, vec!["mint-a".to_owned(), "mint-b".to_owned()]);
    assert_eq!(derived.cut.universe.eligible_count.get(), 2);
    assert_eq!(derived.derivation.declared_subjects.get(), 2);
    assert_eq!(derived.derivation.observed_subjects.get(), 1);
    // The declared digest is the recomputed one; the DTO refuses any other.
    derived.cut.universe.validate().expect("universe closure");

    // The single rendered row is the committed observation, keyed by its real identities and
    // carrying the sha256 of the exact ingested provider bytes.
    assert_eq!(derived.cut.rendered.len(), 1);
    let row = &derived.cut.rendered[0];
    assert_eq!(row.subject.as_str(), "mint-a");
    assert_eq!(
        row.event_id.as_str(),
        surface_event_identity("launch", "mint-a", "obs-a")
    );
    assert_eq!(row.evidence_digest.as_str(), content_digest(PAYLOAD_A));
    assert_eq!(row.memberships, vec![SurfaceMembership::Census]);
    assert_eq!(row.observed_at, t("2026-08-18T09:59:30.000000Z"));
    assert_eq!(row.known_at, t("2026-08-18T10:00:00.000000Z"));

    // Cells come from effective assertions; a fresh one is covered and an old one is stale.
    assert_eq!(
        cell(&derived.cut, "mint-a", "name"),
        FieldState::Covered {
            observed_at: t("2026-08-18T10:04:30.000000Z")
        }
    );
    assert_eq!(
        cell(&derived.cut, "mint-a", "mint"),
        FieldState::Stale {
            observed_at: t("2026-08-18T09:50:00.000000Z"),
            age_seconds: WireU64::new(900)
        }
    );
    // A declared but unobserved subject keeps explicit unknown cells rather than vanishing.
    assert!(matches!(
        cell(&derived.cut, "mint-b", "name"),
        FieldState::Unknown { .. }
    ));
    assert!(matches!(
        cell(&derived.cut, "mint-a", "migration"),
        FieldState::Unknown { .. }
    ));

    derived
        .cut
        .validate_against(&profile)
        .expect("cut closes against the approved profile");
}

#[test]
fn derivation_receipt_names_every_input_it_could_not_resolve() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive");
    let unresolved = &derived.derivation.unresolved;
    for expected in [
        UnresolvedSurfaceInput::HotLeaseReceipts,
        UnresolvedSurfaceInput::QualificationSessions,
        UnresolvedSurfaceInput::WorldEligibility,
        // `chain-lifecycle` declares cadence `event` and ordering `slot`.
        UnresolvedSurfaceInput::CadenceStalenessBound,
        UnresolvedSurfaceInput::RenderOrderingPolicy,
    ] {
        assert!(unresolved.contains(&expected), "missing {expected:?}");
    }
    assert!(!unresolved.contains(&UnresolvedSurfaceInput::FieldAssertionsAbsent));

    // The receipt is exact-byte canonical, like every other artifact this crate emits.
    let bytes = derived
        .derivation
        .canonical_bytes()
        .expect("canonical receipt bytes");
    let parsed = parse_surface_derivation_receipt(&bytes).expect("round trip");
    assert_eq!(parsed, derived.derivation);
    let mut padded = vec![b' '];
    padded.extend(bytes);
    assert!(parse_surface_derivation_receipt(&padded).is_err());
}

#[test]
fn an_earlier_cutoff_cannot_see_later_committed_knowledge() {
    let catalog = catalog();
    let profile = profile();
    let early = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("declare"), 10)
        .expect("derive at declare cutoff");
    assert_eq!(early.derivation.field_assertion_rows.get(), 0);
    assert!(
        early
            .derivation
            .unresolved
            .contains(&UnresolvedSurfaceInput::FieldAssertionsAbsent)
    );
    assert!(matches!(
        cell(&early.cut, "mint-a", "name"),
        FieldState::Unknown { .. }
    ));
    assert_eq!(early.derivation.cutoff, t("2026-08-18T10:00:00.000000Z"));

    let late = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive at assert cutoff");
    assert!(matches!(
        cell(&late.cut, "mint-a", "name"),
        FieldState::Covered { .. }
    ));
}

#[test]
fn an_open_gap_becomes_a_derived_cell_and_a_terminal_recovery_clears_it() {
    let catalog = catalog();
    let profile = profile();
    let during = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("gap"), 10)
        .expect("derive at gap cutoff");
    assert_eq!(during.derivation.open_gaps.len(), 1);
    assert!(during.derivation.open_gaps[0].expressed_in_cut);
    assert_eq!(
        during.derivation.open_gaps[0]
            .subject
            .as_ref()
            .map(|value| value.as_str()),
        Some("mint-a")
    );
    assert_eq!(
        cell(&during.cut, "mint-a", "name"),
        FieldState::Gap {
            gap_id: s("gap-mint-a"),
            // Gap knowledge time is the commit that made the gap durable.
            since: t("2026-08-18T10:10:00.000000Z")
        }
    );

    let after = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("recover"), 10)
        .expect("derive at recovery cutoff");
    assert!(after.derivation.open_gaps.is_empty());
    // The cell falls back to its assertion evidence. By 10:15 that evidence is older than the
    // profile's 60s cadence, so the recomputed state is stale rather than covered.
    assert!(matches!(
        cell(&after.cut, "mint-a", "name"),
        FieldState::Stale { .. }
    ));
}

#[test]
fn stale_age_is_recomputed_against_each_cutoff() {
    let catalog = catalog();
    let profile = profile();
    let early = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive");
    let late = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("recover"), 10)
        .expect("derive");
    let age = |state: FieldState| match state {
        FieldState::Stale { age_seconds, .. } => age_seconds.get(),
        other => panic!("expected a stale cell, got {other:?}"),
    };
    // 10:05:00 - 09:50:00 and 10:15:00 - 09:50:00 against the same stored assertion.
    assert_eq!(age(cell(&early.cut, "mint-a", "mint")), 900);
    assert_eq!(age(cell(&late.cut, "mint-a", "mint")), 1_500);
}

#[test]
fn an_uncommitted_cutoff_is_refused_rather_than_projected() {
    let catalog = catalog();
    let profile = profile();
    let beyond = catalog.seq.values().max().copied().expect("commits") + 1;
    let error = catalog
        .open()
        .derive_surface_cut(&profile, beyond, 10)
        .expect_err("uncommitted cutoff");
    assert!(matches!(
        error,
        crate::SurfaceReadbackError::UnknownCutoff { .. }
    ));
}

#[test]
fn an_unregistered_surface_source_is_named_rather_than_silently_empty() {
    let catalog = catalog();
    let mut profile = profile();
    profile.surfaces[1].source = s("never-registered");
    profile.profile_digest = profile.computed_digest().expect("profile digest");
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive");
    assert!(
        derived
            .derivation
            .unresolved
            .contains(&UnresolvedSurfaceInput::SurfaceSourceNotRegistered)
    );
    let binding = derived
        .derivation
        .bindings
        .iter()
        .find(|value| value.surface_id.as_str() == "chain-lifecycle")
        .expect("binding row");
    assert!(binding.catalog_source_id.is_none());
    let bound: BTreeSet<_> = derived
        .derivation
        .bindings
        .iter()
        .filter_map(|value| value.catalog_source_id.as_ref())
        .map(|value| value.as_str().to_owned())
        .collect();
    assert_eq!(bound, BTreeSet::from([PUMP.to_owned()]));
}

#[test]
fn a_gap_on_an_unobserved_subject_is_named_rather_than_quietly_dropped() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("gap-unobserved"), 10)
        .expect("derive at unobserved-gap cutoff");
    let row = derived
        .derivation
        .open_gaps
        .iter()
        .find(|value| value.gap_id.as_str() == "gap-mint-b")
        .expect("the gap is on the receipt");
    // `mint-b` is declared in coverage but was never observed, so no cut row can carry the gap.
    assert!(!row.expressed_in_cut);
    assert!(
        derived
            .derivation
            .unresolved
            .contains(&UnresolvedSurfaceInput::GapCellsForUnobservedSubjects)
    );
    assert!(matches!(
        cell(&derived.cut, "mint-b", "name"),
        FieldState::Unknown { .. }
    ));
}

#[test]
fn a_gap_carries_the_exact_window_its_producer_authored() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("gap-bounded"), 10)
        .expect("derive at bounded-gap cutoff");
    let gap = derived
        .derivation
        .open_gaps
        .iter()
        .find(|value| value.gap_id.as_str() == "gap-pump-window")
        .expect("the bounded gap is open at this cutoff");

    // The producer bounded this window with a source-native cursor and a wall clock. Neither is
    // projected onto the other, and neither is the commit clock that made the gap durable.
    assert_eq!(
        gap.window_lower,
        SurfaceGapBoundaryV1::SourceCursor {
            value: s("cursor:pump/slot/440345530")
        }
    );
    assert_eq!(
        gap.window_upper,
        Some(SurfaceGapBoundaryV1::Wall {
            value: t("2026-08-18T10:24:00.000000Z")
        })
    );
    assert_eq!(gap.since, t("2026-08-18T10:25:00.000000Z"));
    assert!(
        gap.subject.is_none(),
        "this gap is scoped to the whole source"
    );

    // The still-open `mint-b` gap has no upper boundary at all, and that absence is retained
    // rather than closed at the cutoff.
    let open_ended = derived
        .derivation
        .open_gaps
        .iter()
        .find(|value| value.gap_id.as_str() == "gap-mint-b")
        .expect("the earlier gap is still open");
    assert_eq!(
        open_ended.window_lower,
        SurfaceGapBoundaryV1::Wall {
            value: t("2026-08-18T10:20:00.000000Z")
        }
    );
    assert_eq!(open_ended.window_upper, None);
}

#[test]
fn committed_observations_are_counted_even_when_they_name_no_subject() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive");
    // One observation is committed for the bound sources at this cutoff and it names a subject,
    // so the population is not silently smaller than the evidence.
    assert_eq!(derived.derivation.committed_observations.get(), 1);
    assert_eq!(derived.derivation.observations_without_subject.get(), 0);
    assert!(
        !derived
            .derivation
            .unresolved
            .contains(&UnresolvedSurfaceInput::SubjectsForCommittedObservations)
    );
}

#[test]
fn the_latest_commit_sequence_comes_from_the_catalog_rather_than_a_caller() {
    let catalog = catalog();
    let latest = catalog
        .open()
        .latest_commit_seq()
        .expect("read the catalog commit order")
        .expect("a written catalog has commits");
    assert_eq!(
        latest,
        catalog.seq.values().copied().max().expect("commits"),
        "the newest durable knowledge order is the catalog's own"
    );
}

#[test]
fn one_observation_naming_two_subjects_becomes_one_row_per_subject() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("census"), 10)
        .expect("derive at census cutoff");

    // `obs-census` names `mint-a` and `mint-c` through two `contains` links. A cut row is one
    // surface's view of one subject, so the observation identity alone cannot key both: keying
    // them by the surface/observation pair collided two rows under one event id and the reducer
    // refused the whole cut as a conflicting event.
    let rows: Vec<_> = derived
        .cut
        .rendered
        .iter()
        .filter(|row| row.event_id.as_str().contains("obs-census"))
        .collect();
    assert_eq!(rows.len(), 2, "one row per subject the frame named");
    let subjects: BTreeSet<_> = rows.iter().map(|row| row.subject.as_str()).collect();
    assert_eq!(subjects, BTreeSet::from(["mint-a", "mint-c"]));
    let identities: BTreeSet<_> = rows.iter().map(|row| row.event_id.as_str()).collect();
    assert_eq!(identities.len(), 2, "the row identities are distinct");
    assert!(identities.contains(surface_event_identity("launch", "mint-a", "obs-census").as_str()));
    assert!(identities.contains(surface_event_identity("launch", "mint-c", "obs-census").as_str()));
    // Both rows carry the exact bytes of the one frame they came from.
    for row in &rows {
        assert_eq!(row.evidence_digest.as_str(), content_digest(PAYLOAD_CENSUS));
    }
}

#[test]
fn an_observed_subject_nobody_declared_is_rendered_rather_than_inverted_into_the_denominator() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("census"), 10)
        .expect("derive at census cutoff");

    // `mint-c` turned up inside a declared scope without ever having been declared itself. That
    // is the honest shape of a census, and it is the opposite of denominator-only: it was
    // observed and was never in any denominator.
    let observed = derived
        .cut
        .rendered
        .iter()
        .find(|row| row.subject.as_str() == "mint-c")
        .expect("the undeclared observed subject is rendered");
    assert_eq!(
        observed.memberships,
        vec![SurfaceMembership::ObservedUndeclared]
    );
    assert!(
        derived
            .derivation
            .unresolved
            .contains(&UnresolvedSurfaceInput::UndeclaredObservedSubject),
        "its product membership is still unresolved and the receipt says so"
    );

    // `mint-b` is the other fact: declared in coverage and never observed. It stays an explicit
    // omission even though the derived universe is open.
    let omitted = derived
        .cut
        .omissions
        .iter()
        .find(|omission| omission.subject.as_str() == "mint-b")
        .expect("the declared unobserved subject is omitted with a reason");
    assert_eq!(omitted.membership, SurfaceMembership::DenominatorOnly);
    assert_eq!(omitted.reason.as_str(), "not_observed_by_cutoff");
    assert!(
        derived
            .cut
            .omissions
            .iter()
            .all(|omission| omission.subject.as_str() != "mint-c"),
        "an observed subject is never also omitted"
    );

    // A population a subject can join by being observed is not a denominator, and the universe
    // says so on the wire rather than in a footnote.
    assert!(!derived.cut.universe.closed);
    assert!(derived.cut.universe.sample_only);
    assert_eq!(derived.derivation.declared_subjects.get(), 2);
    assert_eq!(derived.derivation.observed_subjects.get(), 2);
    assert_eq!(derived.cut.universe.eligible_count.get(), 3);
    derived
        .cut
        .validate_against(&profile)
        .expect("cut closes against the approved profile");
}
