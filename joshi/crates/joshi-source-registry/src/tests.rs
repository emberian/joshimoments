use joshi_domain::{SourceId, StableString, ValueDigest};

use crate::{
    AbsenceSemantics, AccessClass, BillingPolicy, BillingUnit, Commitment, CostEstimate,
    CredentialAuthority, FieldAuthority, FieldContract, FieldKind, FinalityPolicy, GapSemantics,
    KillSwitch, MethodContract, MethodKind, ProgressSemantics, ProtectionClass, QuotaReset,
    QuotaSpec, RegistryError, RetentionClass, RetryPolicy, RunBudget, SchemaFingerprint,
    SourceContract, SourceStatus, ZeroPriceAttestation, pumpportal_contract,
};

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable")
}
fn digest(value: &str) -> ValueDigest {
    ValueDigest::new(value).expect("digest")
}

fn source(access: AccessClass, credential: CredentialAuthority) -> SourceContract {
    let method_key = stable("poll");
    SourceContract {
        source_id: SourceId::new("fixture").expect("id"),
        provider: stable("fixture"),
        contract_version: stable("fixture/v1"),
        status: SourceStatus::Enabled,
        access,
        credential,
        credential_descriptor: (credential != CredentialAuthority::None).then(|| {
            crate::CredentialDescriptor {
                key_id: stable("fixture-key"),
                authority: credential,
                owner_only: true,
                purpose: stable("test"),
            }
        }),
        methods: vec![MethodContract {
            key: method_key.clone(),
            kind: MethodKind::Fixture,
            schema_fingerprint: SchemaFingerprint {
                algorithm: stable("sha256"),
                digest: digest("sha256:schema"),
            },
            billing: BillingPolicy {
                unit: BillingUnit::Request,
                minor_units_per_unit: 0,
                currency: None,
                asset_id: None,
                zero_price_attestation: ZeroPriceAttestation::OperatorConformanceOnly,
            },
            quota: QuotaSpec {
                unit: BillingUnit::Request,
                hard_limit: Some(10),
                reset: QuotaReset::UtcDay,
                window_seconds: Some(86_400),
                remaining_observable: true,
            },
            commitment: Commitment::Finalized,
            finality: FinalityPolicy::RequireFinalized,
            absence: AbsenceSemantics::EmptyOnlyWhenComplete,
            max_request_bytes: 1,
            max_response_bytes: 1_024,
        }],
        fields: vec![FieldContract {
            field: FieldKind::Launch,
            authority: FieldAuthority::Primary,
            method_keys: vec![method_key],
            absence: AbsenceSemantics::EmptyOnlyWhenComplete,
        }],
        progress: ProgressSemantics::FixtureSequence,
        retry: RetryPolicy {
            max_attempts: 1,
            max_delay_ms: 0,
            retryable_statuses: Vec::new(),
            gap: GapSemantics::RecoverableWithBoundedRead,
        },
        protection: ProtectionClass::Public,
        retention: RetentionClass::Public,
        kill_switch: KillSwitch {
            enabled: false,
            reason: stable("none"),
            requires_operator_reenable: false,
        },
        schema_fingerprint: None,
    }
}

#[test]
fn strict_fingerprint_and_unknown_fields() {
    let source = source(
        AccessClass::UnauthenticatedPublic,
        CredentialAuthority::None,
    )
    .fingerprinted()
    .expect("valid");
    source.validate().expect("fingerprint validates");
    let bytes = serde_json::to_vec(&source).expect("json");
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).expect("value");
    value
        .as_object_mut()
        .expect("object")
        .insert("unknown".into(), true.into());
    assert!(serde_json::from_value::<SourceContract>(value).is_err());
}

#[test]
fn canonical_fixture_is_a_valid_registry() {
    let registry: crate::SourceRegistry = serde_json::from_slice(include_bytes!(
        "../../../fixtures/source-registry/canonical_registry.v1.json"
    ))
    .expect("registry fixture");
    registry.validate().expect("registry validates");
}

#[test]
fn budget_wire_integers_are_decimal_strings() {
    let value = serde_json::to_value(crate::BudgetUsage {
        requests: 2,
        ingress_bytes: 4,
        ..crate::BudgetUsage::default()
    })
    .expect("json");
    assert_eq!(value["requests"], "2");
    assert_eq!(value["ingressBytes"], "4");
}

#[test]
fn field_absence_and_kill_switch_are_not_inferred() {
    let mut mismatched = source(
        AccessClass::UnauthenticatedPublic,
        CredentialAuthority::None,
    );
    mismatched.fields[0].absence = AbsenceSemantics::IntervalCensored;
    assert_eq!(mismatched.validate(), Err(RegistryError::InvalidSemantics));
    let mut switched = source(
        AccessClass::UnauthenticatedPublic,
        CredentialAuthority::None,
    );
    switched.kill_switch.enabled = true;
    switched = switched.fingerprinted().expect("structural contract");
    assert_eq!(switched.admit(), Err(RegistryError::KillSwitched));
}

#[test]
fn wallet_bearing_pumpportal_is_fail_closed_even_zero_priced() {
    assert_eq!(
        pumpportal_contract(),
        Err(RegistryError::WalletBearingCredential)
    );
}

#[test]
fn unauthenticated_zero_price_requires_attestation() {
    let mut source = source(
        AccessClass::UnauthenticatedPublic,
        CredentialAuthority::None,
    );
    source.methods[0].billing.zero_price_attestation = ZeroPriceAttestation::NotProvided;
    assert_eq!(
        source.validate(),
        Err(RegistryError::ZeroPriceNotUnauthenticated)
    );
}

#[test]
fn bounded_reservation_releases_and_rejects_double_settle() {
    let cap = crate::BudgetUsage {
        requests: 2,
        ingress_bytes: 100,
        ..crate::BudgetUsage::default()
    };
    let mut budget = RunBudget::new(cap).expect("budget");
    let mut reservation = budget
        .reserve(CostEstimate {
            worst_case: crate::BudgetUsage {
                requests: 1,
                ingress_bytes: 50,
                ..crate::BudgetUsage::default()
            },
            max_overshoot: crate::BudgetUsage {
                requests: 0,
                ingress_bytes: 10,
                ..crate::BudgetUsage::default()
            },
        })
        .expect("reserve");
    budget
        .settle(
            &mut reservation,
            crate::BudgetUsage {
                requests: 1,
                ingress_bytes: 60,
                ..crate::BudgetUsage::default()
            },
        )
        .expect("settle");
    assert_eq!(
        budget.settle(&mut reservation, crate::BudgetUsage::default()),
        Err(RegistryError::ReservationMismatch)
    );
    assert_eq!(
        budget.snapshot().expect("snapshot").consumed.ingress_bytes,
        60
    );
}

#[test]
fn reservation_reserves_overshoot_and_never_borrows_dimensions() {
    let cap = crate::BudgetUsage {
        requests: 1,
        ingress_bytes: 100,
        provider_credits: 1,
        ..crate::BudgetUsage::default()
    };
    let mut budget = RunBudget::new(cap).expect("budget");
    let first = budget
        .reserve(CostEstimate {
            worst_case: crate::BudgetUsage {
                requests: 1,
                ingress_bytes: 50,
                provider_credits: 1,
                ..crate::BudgetUsage::default()
            },
            max_overshoot: crate::BudgetUsage {
                ingress_bytes: 50,
                ..crate::BudgetUsage::default()
            },
        })
        .expect("reserve");
    assert!(
        budget
            .reserve(CostEstimate {
                worst_case: crate::BudgetUsage {
                    ingress_bytes: 1,
                    ..crate::BudgetUsage::default()
                },
                max_overshoot: crate::BudgetUsage::default()
            })
            .is_err()
    );
    let mut first = first;
    budget
        .settle(
            &mut first,
            crate::BudgetUsage {
                requests: 1,
                ingress_bytes: 100,
                provider_credits: 1,
                ..crate::BudgetUsage::default()
            },
        )
        .expect("settle");
}

#[test]
fn source_bound_reservation_requires_method_ceiling_and_binds_scope() {
    let source = source(
        AccessClass::UnauthenticatedPublic,
        CredentialAuthority::None,
    )
    .fingerprinted()
    .expect("source");
    let mut budget = RunBudget::with_run_id(
        stable("run-1"),
        crate::BudgetUsage {
            requests: 1,
            ingress_bytes: 2_048,
            durable_bytes: 2_048,
            wall_millis: 1_000,
            ..crate::BudgetUsage::default()
        },
    )
    .expect("budget");
    let key = stable("poll");
    let bad = budget.reserve_for_method(
        &source,
        &key,
        CostEstimate {
            worst_case: crate::BudgetUsage {
                requests: 1,
                ingress_bytes: 1,
                durable_bytes: 1,
                ..crate::BudgetUsage::default()
            },
            max_overshoot: crate::BudgetUsage::default(),
        },
    );
    assert_eq!(bad, Err(RegistryError::BudgetExceeded));
    let mut reservation = budget
        .reserve_for_method(
            &source,
            &key,
            CostEstimate {
                worst_case: crate::BudgetUsage {
                    requests: 1,
                    ingress_bytes: 1_024,
                    durable_bytes: 1_024,
                    wall_millis: 1_000,
                    ..crate::BudgetUsage::default()
                },
                max_overshoot: crate::BudgetUsage::default(),
            },
        )
        .expect("bound reservation");
    assert_eq!(reservation.scope.as_ref().expect("scope").method_key, key);
    reservation.scope = Some(crate::ReservationScope {
        source_id: SourceId::new("other").expect("id"),
        method_key: stable("poll"),
    });
    assert_eq!(
        budget.settle(
            &mut reservation,
            crate::BudgetUsage {
                requests: 1,
                ingress_bytes: 1_024,
                durable_bytes: 1_024,
                wall_millis: 1_000,
                ..crate::BudgetUsage::default()
            }
        ),
        Err(RegistryError::ReservationMismatch)
    );
}

#[test]
fn paid_units_require_exact_currency_events_and_observable_quota() {
    let mut paid = source(
        AccessClass::UnauthenticatedPublic,
        CredentialAuthority::None,
    );
    paid.methods[0].billing.unit = BillingUnit::Event;
    paid.methods[0].billing.minor_units_per_unit = 2;
    paid.methods[0].billing.currency = Some(stable("USD"));
    paid.methods[0].quota.unit = BillingUnit::Event;
    paid.methods[0].quota.remaining_observable = true;
    paid = paid.fingerprinted().expect("paid source");
    let key = stable("poll");
    let mut budget = RunBudget::with_run_id(
        stable("run:paid"),
        crate::BudgetUsage {
            requests: 1,
            events: 5,
            ingress_bytes: 1_024,
            durable_bytes: 1_024,
            provider_currency_minor: [(stable("USD"), 10)].into_iter().collect(),
            ..crate::BudgetUsage::default()
        },
    )
    .expect("budget");
    assert!(
        budget
            .reserve_for_method(
                &paid,
                &key,
                CostEstimate {
                    worst_case: crate::BudgetUsage {
                        requests: 1,
                        events: 0,
                        ingress_bytes: 1_024,
                        durable_bytes: 1_024,
                        ..crate::BudgetUsage::default()
                    },
                    max_overshoot: crate::BudgetUsage::default()
                }
            )
            .is_err()
    );
    let reservation = budget.reserve_for_method(
        &paid,
        &key,
        CostEstimate {
            worst_case: crate::BudgetUsage {
                requests: 1,
                events: 5,
                ingress_bytes: 1_024,
                durable_bytes: 1_024,
                provider_currency_minor: [(stable("USD"), 10)].into_iter().collect(),
                ..crate::BudgetUsage::default()
            },
            max_overshoot: crate::BudgetUsage::default(),
        },
    );
    let mut reservation = reservation.expect("reservation");
    assert_eq!(
        budget.settle(
            &mut reservation,
            crate::BudgetUsage {
                wall_millis: 1,
                ..crate::BudgetUsage::default()
            }
        ),
        Err(RegistryError::BudgetExceeded)
    );
    assert_eq!(
        budget.settle(
            &mut reservation,
            crate::BudgetUsage {
                requests: 1,
                ingress_bytes: 1_024,
                durable_bytes: 1_024,
                ..crate::BudgetUsage::default()
            }
        ),
        Err(RegistryError::BudgetExceeded)
    );
    budget
        .settle(
            &mut reservation,
            crate::BudgetUsage {
                requests: 1,
                events: 5,
                ingress_bytes: 1_024,
                durable_bytes: 1_024,
                provider_currency_minor: [(stable("USD"), 10)].into_iter().collect(),
                ..crate::BudgetUsage::default()
            },
        )
        .expect("exact settlement");
}

#[test]
fn unbound_source_reservation_and_public_authenticated_retention_are_refused() {
    let auth_source = source(
        AccessClass::AuthenticatedReadOnly,
        CredentialAuthority::ReadOnlyApi,
    );
    assert_eq!(
        auth_source.validate(),
        Err(RegistryError::InvalidContract(
            "authenticated source requires private protection and retention"
        ))
    );
    let mut unbound = RunBudget::new(crate::BudgetUsage {
        requests: 1,
        ..crate::BudgetUsage::default()
    })
    .expect("fixture budget");
    let key = stable("poll");
    let source = source(
        AccessClass::UnauthenticatedPublic,
        CredentialAuthority::None,
    )
    .fingerprinted()
    .expect("source");
    assert_eq!(
        unbound.reserve_for_method(
            &source,
            &key,
            CostEstimate {
                worst_case: crate::BudgetUsage {
                    requests: 1,
                    ingress_bytes: 1_024,
                    durable_bytes: 1_024,
                    ..crate::BudgetUsage::default()
                },
                max_overshoot: crate::BudgetUsage::default()
            }
        ),
        Err(RegistryError::InvalidValue("run registration required"))
    );
}

#[test]
fn live_operator_conformance_and_unpinned_schema_are_refused() {
    let mut live = source(
        AccessClass::UnauthenticatedPublic,
        CredentialAuthority::None,
    );
    live.methods[0].kind = MethodKind::HttpGet;
    assert_eq!(
        live.validate(),
        Err(RegistryError::ZeroPriceNotUnauthenticated)
    );
    let unpinned = source(
        AccessClass::UnauthenticatedPublic,
        CredentialAuthority::None,
    );
    assert_eq!(
        unpinned.validate(),
        Err(RegistryError::InvalidContract(
            "source schema fingerprint required"
        ))
    );
}

#[test]
fn planning_profiles_are_bounded_and_metered_profiles_have_credits() {
    let profiles = crate::planning_profiles();
    assert_eq!(profiles.len(), 5);
    assert_eq!(profiles[0].budget.provider_credits, 0);
    assert_eq!(profiles[1].budget.requests, 25);
    assert_eq!(profiles[4].budget.provider_credits, 100_000);
    for profile in profiles {
        assert!(profile.run_budget().is_err());
        profile
            .registered_run_budget(stable("run:fixture"))
            .expect("registered run budget");
    }
}

#[test]
fn no_secret_like_string_is_needed_for_a_source_contract() {
    let source = source(
        AccessClass::UnauthenticatedPublic,
        CredentialAuthority::None,
    )
    .fingerprinted()
    .expect("source");
    let json = serde_json::to_string(&source).expect("json");
    assert!(!json.contains("api-key") && !json.contains("secret") && !json.contains("token"));
}
