use super::*;

const OCCURRENCE_FIXTURE: &str = include_str!("../../../fixtures/pairing/ordinary_pairing_v1.json");
const SESSION_FIXTURE: &str = include_str!("../../../fixtures/pairing/session_descriptor_v1.json");
const EPOCH_FIXTURE: &str = include_str!("../../../fixtures/pairing/epoch_started_v1.json");

#[derive(Clone)]
struct RepeatEntropy;

impl Entropy for RepeatEntropy {
    fn fill(&mut self, bytes: &mut [u8]) -> Result<(), PairingError> {
        bytes.fill(7);
        Ok(())
    }
}

fn origin(value: &str) -> PairingOrigin {
    PairingOrigin::new(value).unwrap()
}

fn wall(value: &str) -> PairingWallInstant {
    value.parse().unwrap()
}

fn make_clock(now: u64) -> TestClock {
    TestClock::new(now, wall("2026-08-18T12:00:00.000000Z"))
}

fn exchanged(outcome: PairingConsumeOutcome) -> ExchangedPairing {
    match outcome {
        PairingConsumeOutcome::Exchanged(value) => value,
        PairingConsumeOutcome::Rejected(value) => panic!("unexpected rejection: {:?}", value.error),
    }
}

#[test]
fn one_canonical_high_entropy_code_is_consumed_once_and_capability_is_domain_separated() {
    let service_origin = origin("http://127.0.0.1:8787");
    let mut registry = PairingRegistry::new(
        service_origin.clone(),
        1,
        PairingConfig::default(),
        TestEntropy::new(1),
    )
    .unwrap();
    let mut clock = make_clock(100);
    let issued = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    assert_eq!(issued.code.as_str().len(), PAIRING_CODE_TEXT_LENGTH);
    assert_eq!(
        issued.code.as_str(),
        "JOSHI-040G-7080-XPTK-366S-YS65-1JRN-4N5D-NJ7N"
    );
    assert_eq!(
        SecretCode::parse(issued.code.as_str()).unwrap().as_str(),
        issued.code.as_str()
    );
    assert!(!format!("{issued:?}").contains(issued.code.as_str()));
    clock.advance(1).unwrap();
    let exchanged = exchanged(
        registry
            .consume_now(&issued.code, &service_origin, &mut clock)
            .unwrap(),
    );
    assert!(
        exchanged
            .capability
            .as_str()
            .starts_with(PAIRING_CAPABILITY_PREFIX)
    );
    assert_ne!(issued.code.as_str(), exchanged.capability.as_str());
    clock.advance(1).unwrap();
    assert_eq!(
        registry
            .authorize_now(
                &exchanged.capability,
                &service_origin,
                PairingScope::CockpitRead,
                &mut clock,
            )
            .unwrap()
            .0
            .session_id,
        exchanged.descriptor.session_id
    );
    clock.advance(1).unwrap();
    assert!(matches!(
        registry
            .consume_now(&issued.code, &service_origin, &mut clock)
            .unwrap(),
        PairingConsumeOutcome::Rejected(_)
    ));
}

#[test]
fn wrong_origin_does_not_consume_and_failed_attempts_are_bounded_and_auditable() {
    let service_origin = origin("http://localhost:8787");
    let wrong_origin = origin("http://127.0.0.1:8787");
    let config = PairingConfig {
        max_failed_attempts: 2,
        ..PairingConfig::default()
    };
    let mut registry =
        PairingRegistry::new(service_origin.clone(), 1, config, TestEntropy::new(4)).unwrap();
    let mut clock = make_clock(1);
    let issued = registry
        .issue_now(&mut clock, vec![PairingScope::ReplayRead])
        .unwrap();
    clock.advance(1).unwrap();
    assert!(matches!(
        registry.consume_now(&issued.code, &wrong_origin, &mut clock),
        Err(PairingError::OriginMismatch)
    ));
    let wrong = SecretCode::parse("JOSHI-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ").unwrap();
    clock.advance(1).unwrap();
    let PairingConsumeOutcome::Rejected(first) = registry
        .consume_now(&wrong, &service_origin, &mut clock)
        .unwrap()
    else {
        panic!("wrong code exchanged")
    };
    assert_eq!(first.error, PairingError::InvalidCode);
    assert_eq!(
        first.occurrence.kind,
        PairingOccurrenceKind::AttemptRejected
    );
    assert_eq!(first.occurrence.failed_attempt_ordinal, Some(1));
    assert!(
        !String::from_utf8(first.occurrence.canonical_bytes().unwrap())
            .unwrap()
            .contains(wrong.as_str())
    );
    clock.advance(1).unwrap();
    let PairingConsumeOutcome::Rejected(second) = registry
        .consume_now(&wrong, &service_origin, &mut clock)
        .unwrap()
    else {
        panic!("wrong code exchanged")
    };
    assert_eq!(second.error, PairingError::RateLimited);
    clock.advance(1).unwrap();
    assert!(matches!(
        registry
            .consume_now(&issued.code, &service_origin, &mut clock)
            .unwrap(),
        PairingConsumeOutcome::Rejected(RejectedPairingAttempt {
            error: PairingError::RateLimited,
            ..
        })
    ));
}

#[test]
fn successful_consume_does_not_reset_the_durable_attempt_window() {
    let service_origin = origin("http://localhost:8787");
    let mut registry = PairingRegistry::new(
        service_origin.clone(),
        1,
        PairingConfig::default(),
        TestEntropy::new(44),
    )
    .unwrap();
    let mut clock = make_clock(1);
    let first = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    let wrong = SecretCode::parse("JOSHI-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ").unwrap();
    clock.advance(1).unwrap();
    let PairingConsumeOutcome::Rejected(first_rejection) = registry
        .consume_now(&wrong, &service_origin, &mut clock)
        .unwrap()
    else {
        panic!("wrong code exchanged")
    };
    assert_eq!(first_rejection.occurrence.failed_attempt_ordinal, Some(1));
    clock.advance(1).unwrap();
    let _ = exchanged(
        registry
            .consume_now(&first.code, &service_origin, &mut clock)
            .unwrap(),
    );
    clock.advance(1).unwrap();
    let _second = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    clock.advance(1).unwrap();
    let PairingConsumeOutcome::Rejected(second_rejection) = registry
        .consume_now(&wrong, &service_origin, &mut clock)
        .unwrap()
    else {
        panic!("wrong code exchanged")
    };
    assert_eq!(second_rejection.occurrence.failed_attempt_ordinal, Some(2));
    assert_eq!(
        second_rejection
            .occurrence
            .attempt_window_started_monotonic_ms,
        first_rejection
            .occurrence
            .attempt_window_started_monotonic_ms
    );
}

#[test]
fn malformed_bounded_submission_is_counted_without_retaining_submitted_bytes() {
    let service_origin = origin("http://localhost:8787");
    let mut registry = PairingRegistry::new(
        service_origin.clone(),
        1,
        PairingConfig::default(),
        TestEntropy::new(55),
    )
    .unwrap();
    let mut clock = make_clock(1);
    let rejection = registry
        .reject_attempt_now(&service_origin, &mut clock)
        .unwrap();
    assert_eq!(rejection.error, PairingError::InvalidCode);
    assert_eq!(rejection.occurrence.failed_attempt_ordinal, Some(1));
    let bytes = rejection.occurrence.canonical_bytes().unwrap();
    let text = String::from_utf8(bytes).unwrap();
    assert!(!text.contains("EMBER"));
    assert!(!text.contains("oneTimeCode"));
}

#[test]
fn wall_clock_rollback_is_refused_and_forward_jump_does_not_extend_monotonic_expiry() {
    let service_origin = origin("https://localhost:9443");
    let config = PairingConfig {
        code_ttl_ms: 30_000,
        session_ttl_ms: 60_000,
        ..PairingConfig::default()
    };
    let mut registry =
        PairingRegistry::new(service_origin.clone(), 7, config, TestEntropy::new(9)).unwrap();
    let mut clock = make_clock(10);
    let issued = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    assert_eq!(
        issued.metadata.expires_at,
        Some(wall("2026-08-18T12:00:30.000000Z"))
    );
    clock.set_monotonic(11);
    clock.set_wall(wall("2020-01-01T00:00:00.000000Z"));
    assert!(matches!(
        registry.consume_now(&issued.code, &service_origin, &mut clock),
        Err(PairingError::InvalidWallClock)
    ));
    clock.set_wall(wall("2099-01-01T00:00:00.000000Z"));
    let session = exchanged(
        registry
            .consume_now(&issued.code, &service_origin, &mut clock)
            .unwrap(),
    );
    assert_eq!(
        session.descriptor.expires_at,
        wall("2099-01-01T00:01:00.000000Z")
    );
    clock.set_monotonic(12);
    clock.set_wall(wall("2099-01-01T00:00:01.000000Z"));
    assert!(
        registry
            .authorize_now(
                &session.capability,
                &service_origin,
                PairingScope::CockpitRead,
                &mut clock,
            )
            .is_ok()
    );
    clock.set_monotonic(60_011);
    clock.set_wall(wall("2099-01-01T00:00:02.000000Z"));
    let expired = registry.expire_now(&mut clock).unwrap();
    assert_eq!(expired.len(), 1);
    assert_eq!(expired[0].kind, PairingOccurrenceKind::Expired);
}

#[test]
fn revoke_restart_and_fail_closed_compensation_drop_secret_state() {
    let service_origin = origin("http://localhost:8787");
    let mut registry = PairingRegistry::new(
        service_origin.clone(),
        1,
        PairingConfig::default(),
        TestEntropy::new(20),
    )
    .unwrap();
    let mut clock = make_clock(1);
    let first = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    assert!(registry.invalidate_issue(first.metadata.issue_id.as_ref().unwrap().as_str()));
    clock.advance(1).unwrap();
    assert!(matches!(
        registry
            .consume_now(&first.code, &service_origin, &mut clock)
            .unwrap(),
        PairingConsumeOutcome::Rejected(_)
    ));

    clock.advance(60_000).unwrap();
    let second = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    clock.advance(1).unwrap();
    let session = exchanged(
        registry
            .consume_now(&second.code, &service_origin, &mut clock)
            .unwrap(),
    );
    assert!(registry.invalidate_session(session.descriptor.session_id.as_str()));

    clock.advance(1).unwrap();
    let third = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    clock.advance(1).unwrap();
    let session = exchanged(
        registry
            .consume_now(&third.code, &service_origin, &mut clock)
            .unwrap(),
    );
    clock.advance(1).unwrap();
    let revoked = registry
        .revoke_now(
            session.descriptor.session_id.as_str(),
            &mut clock,
            "operator_requested",
        )
        .unwrap();
    assert_eq!(revoked.kind, PairingOccurrenceKind::Revoked);

    clock.advance(1).unwrap();
    let live = registry
        .issue_now(&mut clock, vec![PairingScope::ReplayRead])
        .unwrap();
    clock.advance(1).unwrap();
    let _ = registry
        .consume_now(&live.code, &service_origin, &mut clock)
        .unwrap();
    clock.advance(1).unwrap();
    let invalidated = registry.restart_now(2, &mut clock).unwrap();
    assert_eq!(invalidated.len(), 1);
    assert_eq!(
        invalidated[0].kind,
        PairingOccurrenceKind::RestartInvalidated
    );
    assert_eq!(registry.epoch(), 2);
}

#[test]
fn representations_origins_and_config_bounds_are_strict() {
    assert!(PairingOrigin::new("http://localhost:8787/path").is_err());
    assert!(PairingOrigin::new("http://user@localhost:8787").is_err());
    assert!(SecretCode::parse("EMBER-482901").is_err());
    assert!(SecretCode::parse("JOSHI-OOOO-OOOO-OOOO-OOOO-OOOO-OOOO-OOOO-OOOO").is_err());
    assert!(
        SecretCapability::parse(&format!("{PAIRING_CAPABILITY_PREFIX}{}", "A".repeat(64))).is_err()
    );
    assert!(constant_time_equal(b"abc", b"abc"));
    assert!(!constant_time_equal(b"abc", b"abd"));
    assert!(
        PairingConfig {
            code_ttl_ms: 301_000,
            ..PairingConfig::default()
        }
        .validate()
        .is_err()
    );
    assert!(
        PairingConfig {
            max_failed_attempts: 9,
            ..PairingConfig::default()
        }
        .validate()
        .is_err()
    );
    let zero: MonotonicMillis = serde_json::from_str("\"0\"").unwrap();
    assert_eq!(serde_json::to_string(&zero).unwrap(), "\"0\"");
}

#[test]
fn occurrence_identities_are_origin_bound_and_restart_ordinals_are_seeded() {
    let first = origin("http://127.0.0.1:8787");
    let second = origin("http://localhost:8787");
    assert_ne!(
        pairing_epoch_occurrence_id(&first, 1),
        pairing_epoch_occurrence_id(&second, 1)
    );
    assert_eq!(
        pairing_origin_tag(&first),
        "57d735b9c189b41426a4e6c40b217edda92f19d354a230542126af9e8182f9da"
    );
    assert_eq!(
        pairing_epoch_occurrence_id(&first, 1).as_str(),
        "pair-epoch-57d735b9c189b41426a4e6c40b217edda92f19d354a230542126af9e8182f9da-1"
    );
    assert_eq!(
        pairing_occurrence_id(&first, 2, 3).as_str(),
        "pair-occurrence-57d735b9c189b41426a4e6c40b217edda92f19d354a230542126af9e8182f9da-2-3"
    );
    assert_eq!(
        pairing_origin_tag(&second),
        "5d5a5f6be5baf996c3382c16990e8dfe658e5192258a38fbe4781198577c62c1"
    );

    let sample = PairingClockSample {
        monotonic_ms: MonotonicMillis::new(0),
        observed_at: wall("2026-08-18T12:00:10.000000Z"),
    };
    let rate = PairingRateBootstrap {
        last_observed_at: sample.observed_at,
        attempt: PairingRateWindowBootstrap {
            window_id: None,
            used: 0,
            expires_at: None,
        },
        issue: PairingRateWindowBootstrap {
            window_id: None,
            used: 0,
            expires_at: None,
        },
    };
    let mut registry = PairingRegistry::new_after_durable_epoch(
        first.clone(),
        2,
        PairingConfig::default(),
        TestEntropy::new(7),
        2,
        sample,
        rate,
    )
    .unwrap();
    let mut clock = TestClock::new(0, sample.observed_at);
    let issued = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    assert_eq!(
        issued.metadata.occurrence_id,
        pairing_occurrence_id(&first, 2, 3)
    );
}

#[test]
fn durable_rate_bootstrap_survives_restart_until_wall_deadline() {
    let service_origin = origin("http://127.0.0.1:8787");
    let config = PairingConfig {
        max_failed_attempts: 2,
        max_issued_per_window: 1,
        ..PairingConfig::default()
    };
    let sample = PairingClockSample {
        monotonic_ms: MonotonicMillis::new(0),
        observed_at: wall("2026-08-18T12:00:10.000000Z"),
    };
    let deadline = wall("2026-08-18T12:01:00.000000Z");
    let bootstrap = PairingRateBootstrap {
        last_observed_at: sample.observed_at,
        attempt: PairingRateWindowBootstrap {
            window_id: Some(
                joshi_domain::StableString::new("pair-occurrence-prior-attempt").unwrap(),
            ),
            used: 1,
            expires_at: Some(deadline),
        },
        issue: PairingRateWindowBootstrap {
            window_id: Some(
                joshi_domain::StableString::new("pair-occurrence-prior-issue").unwrap(),
            ),
            used: 1,
            expires_at: Some(deadline),
        },
    };
    let mut registry = PairingRegistry::new_after_durable_epoch(
        service_origin.clone(),
        2,
        config,
        TestEntropy::new(9),
        0,
        sample,
        bootstrap,
    )
    .unwrap();
    let mut clock = TestClock::new(0, sample.observed_at);
    assert!(matches!(
        registry.issue_now(&mut clock, vec![PairingScope::CockpitRead]),
        Err(PairingError::RateLimited)
    ));
    let wrong = SecretCode::parse("JOSHI-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ").unwrap();
    let PairingConsumeOutcome::Rejected(rejected) = registry
        .consume_now(&wrong, &service_origin, &mut clock)
        .unwrap()
    else {
        panic!("wrong code exchanged")
    };
    assert_eq!(rejected.error, PairingError::RateLimited);
    assert_eq!(rejected.occurrence.failed_attempt_ordinal, Some(2));
    assert!(matches!(
        registry.consume_now(&wrong, &service_origin, &mut clock),
        Err(PairingError::RateLimited)
    ));

    clock.advance(50_000).unwrap();
    let issued = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    let PairingConsumeOutcome::Rejected(rejected) = registry
        .consume_now(&wrong, &service_origin, &mut clock)
        .unwrap()
    else {
        panic!("wrong code exchanged")
    };
    assert_eq!(rejected.error, PairingError::InvalidCode);
    assert_eq!(rejected.occurrence.failed_attempt_ordinal, Some(1));
    assert!(issued.metadata.observed_at >= deadline);
}

#[test]
fn deterministic_metadata_fixtures_are_exact_and_secret_free() {
    let epoch = parse_pairing_occurrence(EPOCH_FIXTURE.trim_end().as_bytes()).unwrap();
    assert_eq!(epoch.kind, PairingOccurrenceKind::EpochStarted);
    assert_eq!(
        epoch.canonical_bytes().unwrap(),
        EPOCH_FIXTURE.trim_end().as_bytes()
    );
    let occurrence = parse_pairing_occurrence(OCCURRENCE_FIXTURE.trim_end().as_bytes()).unwrap();
    assert_eq!(
        occurrence.canonical_bytes().unwrap(),
        OCCURRENCE_FIXTURE.trim_end().as_bytes()
    );
    assert!(!OCCURRENCE_FIXTURE.contains("capability"));
    assert!(!OCCURRENCE_FIXTURE.contains("oneTimeCode"));
    let session = parse_pairing_session_descriptor(SESSION_FIXTURE.trim_end().as_bytes()).unwrap();
    assert_eq!(
        session.canonical_bytes().unwrap(),
        SESSION_FIXTURE.trim_end().as_bytes()
    );
    let already_expired =
        OCCURRENCE_FIXTURE.replace("2026-08-18T12:02:00.000000Z", "2026-08-18T12:00:00.000000Z");
    assert!(parse_pairing_occurrence(already_expired.as_bytes()).is_err());
}

#[test]
fn revoke_after_monotonic_expiry_records_expiry_not_revocation() {
    let service_origin = origin("http://localhost:8787");
    let config = PairingConfig {
        session_ttl_ms: 60_000,
        ..PairingConfig::default()
    };
    let mut registry =
        PairingRegistry::new(service_origin.clone(), 1, config, TestEntropy::new(33)).unwrap();
    let mut clock = make_clock(1);
    let issue = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    clock.advance(1).unwrap();
    let session = exchanged(
        registry
            .consume_now(&issue.code, &service_origin, &mut clock)
            .unwrap(),
    );
    clock.advance(60_000).unwrap();
    let occurrence = registry
        .revoke_now(
            session.descriptor.session_id.as_str(),
            &mut clock,
            "operator_requested",
        )
        .unwrap();
    assert_eq!(occurrence.kind, PairingOccurrenceKind::Expired);
    assert_eq!(
        occurrence.reason.as_ref().unwrap().as_str(),
        "monotonic_expiry"
    );
}

#[test]
fn authorization_refusal_returns_the_exact_boundary_expiry_occurrence() {
    let service_origin = origin("http://localhost:8787");
    let config = PairingConfig {
        session_ttl_ms: 60_000,
        ..PairingConfig::default()
    };
    let mut registry =
        PairingRegistry::new(service_origin.clone(), 1, config, TestEntropy::new(66)).unwrap();
    let mut clock = make_clock(1);
    let issue = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    clock.advance(1).unwrap();
    let session = exchanged(
        registry
            .consume_now(&issue.code, &service_origin, &mut clock)
            .unwrap(),
    );
    clock.advance(60_000).unwrap();
    let outcome = PairingSessionPort::authorize_capability(
        &mut registry,
        &session.capability,
        &service_origin,
        PairingScope::CockpitRead,
        &mut clock,
    )
    .unwrap();
    let PairingAuthorizationOutcome::Rejected { error, occurrences } = outcome else {
        panic!("expired session authorized")
    };
    assert_eq!(error, PairingError::InvalidSession);
    assert_eq!(occurrences.len(), 1);
    assert_eq!(occurrences[0].kind, PairingOccurrenceKind::Expired);
    assert_eq!(
        occurrences[0].session_id,
        Some(session.descriptor.session_id)
    );
}

#[test]
fn clock_rollback_duplicate_entropy_and_issue_rate_fail_closed() {
    let service_origin = origin("http://localhost:8787");
    let mut clock = make_clock(100);
    let mut registry = PairingRegistry::new(
        service_origin.clone(),
        1,
        PairingConfig::default(),
        TestEntropy::new(1),
    )
    .unwrap();
    registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    clock.set_monotonic(99);
    assert!(matches!(
        registry.issue_now(&mut clock, vec![PairingScope::CockpitRead]),
        Err(PairingError::ClockRollback)
    ));

    let mut duplicate_registry =
        PairingRegistry::new(service_origin, 1, PairingConfig::default(), RepeatEntropy).unwrap();
    let mut clock = make_clock(1);
    duplicate_registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    clock.advance(1).unwrap();
    assert!(matches!(
        duplicate_registry.issue_now(&mut clock, vec![PairingScope::CockpitRead]),
        Err(PairingError::DuplicateSecret)
    ));

    let config = PairingConfig {
        max_issued_per_window: 2,
        ..PairingConfig::default()
    };
    let service_origin = origin("http://localhost:8787");
    let mut bounded =
        PairingRegistry::new(service_origin.clone(), 1, config, TestEntropy::new(72)).unwrap();
    let mut clock = make_clock(1);
    for _ in 0..2 {
        let issue = bounded
            .issue_now(&mut clock, vec![PairingScope::CockpitRead])
            .unwrap();
        clock.advance(1).unwrap();
        let _ = exchanged(
            bounded
                .consume_now(&issue.code, &service_origin, &mut clock)
                .unwrap(),
        );
        clock.advance(1).unwrap();
    }
    assert!(matches!(
        bounded.issue_now(&mut clock, vec![PairingScope::CockpitRead]),
        Err(PairingError::RateLimited)
    ));
}
