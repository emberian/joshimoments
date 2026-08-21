//! Pillar 7 slice S8: one descriptive number about the real market, from the durable catalog.
//!
//! `run` reads the observations a real Helius session already committed, derives one assertion per
//! listed transaction from the exact retained response bytes, commits those assertions and their
//! coverage windows and gaps through the ordinary admission path, publishes the projection that
//! names them, exports two Snapshot V2 directories at different lower commit bounds, and reads the
//! number back out of the installed Parquet in two runtimes.
//!
//! `read` reopens one installed snapshot directory and prints the same number. It shares no state
//! with `run`, so a separate `read` invocation after the writer has exited is the restart evidence.
//!
//! This program observes and counts. It constructs no transaction, signs nothing, submits nothing,
//! and computes no position, fill, or return.

use joshi_admission::{AdmissionPolicy, SourceDraftBatch, source_drafts};
use joshi_domain::{
    AssertionId, CommitSeq, CoverageId, ObservationId, OpenVariant, SourceId, StableString,
    UtcTimestamp, ValueDigest,
};
use joshi_evidence::{
    AssertionDraft, AssertionEvidence, Boundary, CoverageGap, CoverageScope, CoverageWindow,
    EventValidInterval, EvidenceDraft,
};
use joshi_export::{
    ListingErrorCensusV1, OperationalExportRequestV2, OperationalPublicationV2,
    ProjectionPublicationInputV2, PythonValidatorV2, export_operational_snapshot_v2,
    listing_error_census_v1, validate_operational_snapshot_v2_directory,
};
use joshi_store::{
    OperationalCommitContext, ProjectionPublicationCapability, ProjectionRegistration, SqliteStore,
    StoreConfig, StoreMode,
};
use rusqlite::{Connection, OpenFlags};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    error::Error,
    fs,
    path::{Path, PathBuf},
    process::Command,
    time::Duration,
};
use time::OffsetDateTime;

const PRODUCER: &str = "joshi.pillar7.listing_census";
const PRODUCER_VERSION: &str = "joshi.pillar7.listing_census.v1";
const ASSERTION_KIND: &str = "solana_finalized_listing_entry";
const COVERAGE_FAMILY: &str = "market_census";
const SIGNATURE_METHOD: &str = "helius:http:getSignaturesForAddress";
const TRANSACTION_METHOD: &str = "helius:http:getTransaction";
const MAX_SIGNATURE_LIMIT: u32 = 1_000;

type Fallible<T> = Result<T, Box<dyn Error>>;

/// The exact canonical preimage `joshi-store` hashes for one assertion value.
///
/// Field order is the digest, so this mirrors the store's private material struct rather than
/// building a sorted JSON object.
#[derive(serde::Serialize)]
struct AssertionValueMaterial<'a> {
    contract: &'static str,
    assertion_kind: &'a OpenVariant,
    producer: &'a StableString,
    producer_version: &'a StableString,
    extension: &'a Value,
}

fn main() -> Fallible<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    match arguments.first().map(String::as_str) {
        Some("read") => {
            let snapshot = required(&arguments, "--snapshot")?;
            let receipt = validate_operational_snapshot_v2_directory(Path::new(&snapshot))?;
            let census = listing_error_census_v1(Path::new(&snapshot))?;
            println!(
                "{}",
                serde_json::to_string_pretty(&json!({
                    "readback_validator": receipt.validator(),
                    "readback_table_count": receipt.table_count().to_string(),
                    "readback_total_rows": receipt.total_row_count().to_string(),
                    "census": census,
                }))?
            );
            Ok(())
        }
        Some("run") => run(&arguments),
        _ => Err("usage: pillar7_estimand run|read ...".into()),
    }
}

fn run(arguments: &[String]) -> Fallible<()> {
    let catalog = PathBuf::from(required(arguments, "--catalog")?);
    let state_root = PathBuf::from(required(arguments, "--state-root")?);
    let out = PathBuf::from(required(arguments, "--out")?);
    let analysis = PathBuf::from(required(arguments, "--analysis")?);
    let uv = PathBuf::from(optional(arguments, "--uv").unwrap_or_else(|| "uv".to_owned()));
    fs::create_dir_all(&out)?;

    let namespace = format!("pillar7-s8-{}", std::process::id());
    let clock_id = StableString::new(format!("joshi-pillar7-{}", std::process::id()))?;
    let build = StableString::new(env!("CARGO_PKG_VERSION"))?;

    let mut store = SqliteStore::open(
        StoreConfig {
            catalog_path: catalog.clone(),
            blob_root: state_root.join("blobs"),
            export_root: state_root.join("exports"),
            inline_blob_max_bytes: 4 * 1024 * 1024,
            busy_timeout: Duration::from_secs(5),
            catalog_id: StableString::new("joshi-collector-live")?,
            max_observations_per_batch: 256,
            max_raw_bytes_per_batch: 64 * 1024 * 1024,
        },
        StoreMode::SingleWriter,
    )?;
    store.migrate(now()?)?;
    let catalog_schema = store.catalog_schema()?;

    let retained = read_retained(&catalog)?;
    let census = build_census(&retained)?;
    let (first_census_commit, last_census_commit) =
        commit_census(&mut store, &census, &namespace, &clock_id, &build)?;
    let publication = publish_projection(
        &mut store,
        &census,
        last_census_commit,
        &namespace,
        &clock_id,
        &build,
    )?;
    let cutoff = publication.published_commit_seq;

    let python_validator = PythonValidatorV2 {
        program: uv.clone(),
        analysis_directory: analysis.clone(),
    };
    let wide = out.join("snapshot-from-1");
    let narrow = out.join("snapshot-from-census");
    let wide_snapshot = export_operational_snapshot_v2(&request(
        &catalog,
        &catalog_schema,
        CommitSeq::new(1),
        cutoff,
        &format!("export-{namespace}-from-1"),
        &publication,
        &census,
        &wide,
        &python_validator,
        &build,
    ))?;
    let narrow_snapshot = export_operational_snapshot_v2(&request(
        &catalog,
        &catalog_schema,
        first_census_commit,
        cutoff,
        &format!("export-{namespace}-from-{}", first_census_commit.get()),
        &publication,
        &census,
        &narrow,
        &python_validator,
        &build,
    ))?;

    let rust_reading = listing_error_census_v1(&wide)?;
    let python_reading = python_census(&uv, &analysis, &wide)?;
    let agreement = compare(&rust_reading, &python_reading)?;
    let report = report(
        &catalog,
        &catalog_schema,
        &census,
        first_census_commit,
        &publication,
        [(&wide, &wide_snapshot), (&narrow, &narrow_snapshot)],
        &rust_reading,
        &python_reading,
        &agreement,
    );
    let path = out.join("s8-report.json");
    fs::write(&path, serde_json::to_vec_pretty(&report)?)?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn report(
    catalog: &Path,
    catalog_schema: &StableString,
    census: &Census,
    first_census_commit: CommitSeq,
    publication: &ProjectionPublicationInputV2,
    exports: [(&PathBuf, &joshi_export::ValidatedProductionSnapshotV2); 2],
    rust_reading: &ListingErrorCensusV1,
    python_reading: &Value,
    agreement: &Value,
) -> Value {
    let (wide, wide_snapshot) = exports[0];
    let (narrow, narrow_snapshot) = exports[1];
    json!({
        "contract": "joshi.pillar7.s8-estimand-report/v1",
        "authority": "read_only_no_execution",
        "catalog": catalog.display().to_string(),
        "catalog_schema": catalog_schema.as_str(),
        "census_commits": census.batches.iter()
            .map(|batch| batch.source_commit_seq.to_string()).collect::<Vec<_>>(),
        "first_census_commit_seq": first_census_commit.get().to_string(),
        "publication_id": publication.publication_id.as_str(),
        "exports": [
            export_summary(wide, wide_snapshot),
            export_summary(narrow, narrow_snapshot),
        ],
        "from_commit_seq_is_applied": {
            "wide_from": wide_snapshot.commit_range().0.get().to_string(),
            "narrow_from": narrow_snapshot.commit_range().0.get().to_string(),
            "wide_snapshot_id": wide_snapshot.snapshot_id().as_str(),
            "narrow_snapshot_id": narrow_snapshot.snapshot_id().as_str(),
            "wide_truth_fingerprint": wide_snapshot.truth_fingerprint(),
            "narrow_truth_fingerprint": narrow_snapshot.truth_fingerprint(),
            "identities_differ": wide_snapshot.snapshot_id() != narrow_snapshot.snapshot_id(),
        },
        "runtimes": {
            "rust_arrow_parquet": rust_reading,
            "python_duckdb": python_reading,
            "agreement": agreement,
        },
        "unresolved": census.unresolved,
    })
}

// ---------------------------------------------------------------------------------------------
// Retained evidence

struct Retained {
    observation_id: String,
    commit_seq: i64,
    received_wall_us: i64,
    source_id: String,
    method: String,
    request_fingerprint: String,
    body: Vec<u8>,
}

fn read_retained(catalog: &Path) -> Fallible<Vec<Retained>> {
    let connection = Connection::open_with_flags(
        catalog,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    let mut statement = connection.prepare(
        "SELECT o.observation_id,o.commit_seq,o.received_wall_us,o.source_id,
                a.source_locator_redacted,a.request_fingerprint,b.inline_bytes
         FROM observation o
         JOIN acquisition a ON a.acquisition_id=o.acquisition_id
         JOIN blob b ON b.blob_id=o.blob_id
         ORDER BY o.commit_seq,o.intra_commit_seq",
    )?;
    let rows = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, Option<String>>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, Option<Vec<u8>>>(6)?,
            ))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    let mut output = Vec::with_capacity(rows.len());
    for (observation_id, commit_seq, received_wall_us, source_id, method, fingerprint, envelope) in
        rows
    {
        let Some(envelope) = envelope else {
            return Err(format!("observation {observation_id} is an external blob; this census only reads inline retained bytes").into());
        };
        let envelope: Value = serde_json::from_slice(&envelope)?;
        let body = envelope["body"]
            .as_array()
            .ok_or("retained frame envelope has no body array")?
            .iter()
            .map(|value| {
                u8::try_from(value.as_u64().ok_or("body byte is not an integer")?)
                    .map_err(|_| "body byte exceeds one octet".into())
            })
            .collect::<Fallible<Vec<u8>>>()?;
        output.push(Retained {
            observation_id,
            commit_seq,
            received_wall_us,
            source_id,
            method: method.unwrap_or_default(),
            request_fingerprint: fingerprint,
            body,
        });
    }
    Ok(output)
}

/// Recomputes the exact fingerprint the source adapter stored for one redacted request.
fn request_fingerprint(source_id: &str, locator: &str, material: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"joshi.source.request.v1\0");
    hasher.update(source_id.as_bytes());
    hasher.update(b"\0");
    hasher.update(locator.as_bytes());
    hasher.update(b"\0");
    hasher.update(material.as_bytes());
    format!("{:x}", hasher.finalize())
}

// ---------------------------------------------------------------------------------------------
// Census

#[derive(Clone)]
struct ListingEntry {
    signature: String,
    slot: u64,
    block_time_unix_s: i64,
    confirmation_status: String,
    transaction_index: Option<u64>,
    error_json: Option<String>,
}

struct Page {
    observation_id: String,
    source_id: String,
    commit_seq: i64,
    received_wall_us: i64,
    subject: String,
    limit: u32,
    entries: Vec<ListingEntry>,
}

struct FetchedTransaction {
    observation_id: String,
    commit_seq: i64,
    received_wall_us: i64,
    signature: String,
    present: bool,
    error_present: bool,
}

struct CensusBatch {
    source_commit_seq: i64,
    drafts: Vec<EvidenceDraft>,
}

struct Census {
    batches: Vec<CensusBatch>,
    subject_addresses: BTreeSet<String>,
    source_ids: BTreeSet<String>,
    entries: usize,
    unresolved: Vec<Value>,
    input_closure: Vec<String>,
}

#[allow(clippy::too_many_lines)]
fn build_census(retained: &[Retained]) -> Fallible<Census> {
    // Pass one: the exact fetched transactions, which also supply the address candidates the
    // redacted listing fingerprints are recovered from.
    let mut candidates = BTreeSet::new();
    let mut fetched_bodies = Vec::new();
    for item in retained
        .iter()
        .filter(|item| item.method == TRANSACTION_METHOD)
    {
        let body: Value = serde_json::from_slice(&item.body)?;
        let result = &body["result"];
        if let Some(keys) = result["transaction"]["message"]["accountKeys"].as_array() {
            for key in keys {
                if let Some(key) = key.as_str() {
                    candidates.insert(key.to_owned());
                }
            }
        }
        for field in ["writable", "readonly"] {
            if let Some(keys) = result["meta"]["loadedAddresses"][field].as_array() {
                for key in keys {
                    if let Some(key) = key.as_str() {
                        candidates.insert(key.to_owned());
                    }
                }
            }
        }
        fetched_bodies.push((item, body));
    }

    // Pass two: every listing page, with its subject address recovered by exact preimage against
    // the stored request fingerprint. Nothing here guesses; a page whose fingerprint no candidate
    // reproduces is reported unresolved rather than attributed.
    let mut unresolved = Vec::new();
    let mut pages = Vec::new();
    let mut input_closure = Vec::new();
    for item in retained
        .iter()
        .filter(|item| item.method == SIGNATURE_METHOD)
    {
        let body: Value = serde_json::from_slice(&item.body)?;
        let listed = body["result"]
            .as_array()
            .ok_or("signature listing result is not an array")?;
        let mut entries = Vec::with_capacity(listed.len());
        for value in listed {
            entries.push(ListingEntry {
                signature: value["signature"]
                    .as_str()
                    .ok_or("listing entry has no signature")?
                    .to_owned(),
                slot: value["slot"].as_u64().ok_or("listing entry has no slot")?,
                block_time_unix_s: value["blockTime"]
                    .as_i64()
                    .ok_or("listing entry has no blockTime")?,
                confirmation_status: value["confirmationStatus"]
                    .as_str()
                    .unwrap_or("unstated")
                    .to_owned(),
                transaction_index: value["transactionIndex"].as_u64(),
                error_json: match &value["err"] {
                    Value::Null => None,
                    other => Some(serde_json::to_string(other)?),
                },
            });
        }
        let recovered = recover_subject(item, &candidates, entries.len());
        let Some((subject, limit)) = recovered else {
            unresolved.push(json!({
                "kind": "listing_subject_unrecovered",
                "observation_id": item.observation_id,
                "detail": "no candidate address and page limit reproduces the stored request fingerprint",
            }));
            continue;
        };
        input_closure.push(item.observation_id.clone());
        pages.push(Page {
            observation_id: item.observation_id.clone(),
            source_id: item.source_id.clone(),
            commit_seq: item.commit_seq,
            received_wall_us: item.received_wall_us,
            subject,
            limit,
            entries,
        });
    }
    if pages.is_empty() {
        return Err(
            "no listing page in the catalog could be attributed to a subject address".into(),
        );
    }

    let listed_signatures = pages
        .iter()
        .flat_map(|page| page.entries.iter().map(|entry| entry.signature.clone()))
        .collect::<BTreeSet<_>>();
    let mut fetched = Vec::new();
    for (item, body) in fetched_bodies {
        let signature = body["result"]["transaction"]["signatures"][0]
            .as_str()
            .map(str::to_owned)
            .or_else(|| recover_signature(item, &listed_signatures));
        let Some(signature) = signature else {
            unresolved.push(json!({
                "kind": "transaction_subject_unrecovered",
                "observation_id": item.observation_id,
                "detail": "the response carried no signature and no listed signature reproduces the stored request fingerprint",
            }));
            continue;
        };
        let present = !body["result"].is_null();
        input_closure.push(item.observation_id.clone());
        fetched.push(FetchedTransaction {
            observation_id: item.observation_id.clone(),
            commit_seq: item.commit_seq,
            received_wall_us: item.received_wall_us,
            signature,
            present,
            error_present: !body["result"]["meta"]["err"].is_null(),
        });
    }

    let available_at = now()?;
    let mut batches: BTreeMap<i64, Vec<EvidenceDraft>> = BTreeMap::new();
    let mut subject_addresses = BTreeSet::new();
    let mut source_ids = BTreeSet::new();
    let mut seen: BTreeMap<(String, String), bool> = BTreeMap::new();
    let mut entry_count = 0_usize;
    let mut previous_page: Option<&Page> = None;

    for (ordinal, page) in pages.iter().enumerate() {
        subject_addresses.insert(page.subject.clone());
        source_ids.insert(page.source_id.clone());
        let scope = CoverageScope {
            source_id: SourceId::new(page.source_id.clone())?,
            family: OpenVariant::known(COVERAGE_FAMILY)?,
            subject: Some(StableString::new(page.subject.clone())?),
        };
        let window_id = CoverageId::new(format!(
            "coverage:{PRODUCER}:{}:page{ordinal}",
            page.subject
        ))?;
        let lowest = page
            .entries
            .iter()
            .map(|entry| entry.block_time_unix_s)
            .min()
            .ok_or("a retained listing page enumerated nothing, which this census cannot scope")?;
        let highest = page
            .entries
            .iter()
            .map(|entry| entry.block_time_unix_s)
            .max()
            .expect("nonempty");
        let drafts = batches.entry(page.commit_seq).or_default();
        drafts.push(EvidenceDraft::CoverageWindow(CoverageWindow {
            coverage_id: window_id.clone(),
            scope: scope.clone(),
            lower: Boundary::Wall {
                value: utc_from_seconds(lowest)?,
            },
            // The listing is authoritative only up to the instant the page was received; above
            // that instant this read says nothing at all about the address.
            upper: Some(Boundary::Wall {
                value: utc_from_micros(page.received_wall_us)?,
            }),
            state: OpenVariant::known("partial")?,
            available_at,
        }));

        if u32::try_from(page.entries.len()).unwrap_or(u32::MAX) >= page.limit {
            drafts.push(EvidenceDraft::CoverageGap(CoverageGap {
                gap_id: CoverageId::new(format!(
                    "gap:{PRODUCER}:{}:page{ordinal}:truncated",
                    page.subject
                ))?,
                coverage_id: window_id.clone(),
                scope: scope.clone(),
                lower: Boundary::Wall {
                    value: utc_from_seconds(lowest)?,
                },
                upper: None,
                reason: OpenVariant::known("listing_limit_truncated")?,
                detected_at: utc_from_micros(page.received_wall_us)?,
            }));
        }
        if let Some(previous) = previous_page {
            let previous_high = previous
                .entries
                .iter()
                .map(|entry| entry.block_time_unix_s)
                .max()
                .expect("nonempty");
            drafts.push(EvidenceDraft::CoverageGap(CoverageGap {
                gap_id: CoverageId::new(format!(
                    "gap:{PRODUCER}:{}:page{ordinal}:between_reads",
                    page.subject
                ))?,
                coverage_id: window_id.clone(),
                scope: scope.clone(),
                lower: Boundary::Wall {
                    value: utc_from_seconds(previous_high)?,
                },
                upper: None,
                reason: OpenVariant::known("unenumerated_between_listing_reads")?,
                detected_at: utc_from_micros(page.received_wall_us)?,
            }));
        }
        let _ = highest;
        previous_page = Some(page);

        for entry in &page.entries {
            let errored = entry.error_json.is_some();
            let identity = (page.subject.clone(), entry.signature.clone());
            if let Some(previous) = seen.insert(identity.clone(), errored) {
                if previous != errored {
                    return Err(format!(
                        "two retained pages disagree about whether {} carried an error",
                        entry.signature
                    )
                    .into());
                }
                continue;
            }
            entry_count += 1;
            let family = if errored {
                joshi_export::LANDED_ERROR_FAMILY
            } else {
                joshi_export::LANDED_NO_ERROR_FAMILY
            };
            let mut evidence = vec![AssertionEvidence {
                observation_id: ObservationId::new(page.observation_id.clone())?,
                role: OpenVariant::known("decoded_from")?,
            }];
            let mut corroboration = Value::Null;
            for detail in fetched
                .iter()
                .filter(|item| item.signature == entry.signature && item.present)
            {
                if detail.error_present != errored {
                    return Err(format!(
                        "the retained listing and the retained transaction disagree about {}",
                        entry.signature
                    )
                    .into());
                }
                evidence.push(AssertionEvidence {
                    observation_id: ObservationId::new(detail.observation_id.clone())?,
                    role: OpenVariant::known("corroborates")?,
                });
                corroboration = json!(detail.observation_id);
            }
            let mut extension = Map::new();
            extension.insert("signature".into(), json!(entry.signature));
            extension.insert("subject_address".into(), json!(page.subject));
            extension.insert("slot".into(), json!(entry.slot.to_string()));
            extension.insert(
                "block_time_unix_s".into(),
                json!(entry.block_time_unix_s.to_string()),
            );
            extension.insert(
                "confirmation_status".into(),
                json!(entry.confirmation_status),
            );
            extension.insert(
                "transaction_index".into(),
                entry
                    .transaction_index
                    .map_or(Value::Null, |value| json!(value.to_string())),
            );
            extension.insert("landed_error".into(), json!(errored.to_string()));
            extension.insert(
                "landed_error_json".into(),
                entry
                    .error_json
                    .clone()
                    .map_or(Value::Null, |value| json!(value)),
            );
            extension.insert("source_method".into(), json!("getSignaturesForAddress"));
            extension.insert("corroborating_observation_id".into(), corroboration);
            let extension = Value::Object(extension);
            let assertion_kind = OpenVariant::known(ASSERTION_KIND)?;
            let producer = StableString::new(PRODUCER)?;
            let producer_version = StableString::new(PRODUCER_VERSION)?;
            let value_digest =
                ValueDigest::new(qualified(&serde_json::to_vec(&AssertionValueMaterial {
                    contract: "joshi.assertion_value.v1",
                    assertion_kind: &assertion_kind,
                    producer: &producer,
                    producer_version: &producer_version,
                    extension: &extension,
                })?))?;
            batches
                .entry(page.commit_seq)
                .or_default()
                .push(EvidenceDraft::Assertion(AssertionDraft {
                    assertion_id: AssertionId::new(format!(
                        "assertion:{PRODUCER}:{}:{}",
                        page.subject, entry.signature
                    ))?,
                    semantic_key: StableString::new(format!(
                        "{family}/{}/{}",
                        page.subject, entry.signature
                    ))?,
                    assertion_kind,
                    producer,
                    producer_version,
                    assertion_status: OpenVariant::known("accepted")?,
                    valid_time: EventValidInterval {
                        status: OpenVariant::known("bounded")?,
                        lower: Some(utc_from_seconds(entry.block_time_unix_s)?),
                        upper: Some(utc_from_seconds(entry.block_time_unix_s + 1)?),
                    },
                    evidence,
                    source_events: Vec::new(),
                    command_evidence: Vec::new(),
                    supersedes_assertion_id: None,
                    available_at,
                    value_digest,
                    extension,
                }));
        }

        // A detail read the provider answered with a null result is an explicit gap on the exact
        // signature it asked about, never a silence and never an absence of the transaction.
        for detail in fetched
            .iter()
            .filter(|item| !item.present && item.commit_seq == page.commit_seq)
        {
            let listed = page
                .entries
                .iter()
                .find(|entry| entry.signature == detail.signature);
            let opened = listed.map_or_else(
                || utc_from_micros(detail.received_wall_us),
                |entry| utc_from_seconds(entry.block_time_unix_s),
            )?;
            batches
                .entry(page.commit_seq)
                .or_default()
                .push(EvidenceDraft::CoverageGap(CoverageGap {
                    gap_id: CoverageId::new(format!(
                        "gap:{PRODUCER}:{}:detail:{}",
                        page.subject, detail.signature
                    ))?,
                    coverage_id: window_id.clone(),
                    scope: scope.clone(),
                    lower: Boundary::Wall { value: opened },
                    upper: None,
                    reason: OpenVariant::known("transaction_detail_absent")?,
                    detected_at: utc_from_micros(detail.received_wall_us)?,
                }));
            unresolved.push(json!({
                "kind": "transaction_detail_absent",
                "signature": detail.signature,
                "observation_id": detail.observation_id,
                "detail": "the provider answered getTransaction with a null result for a signature it had just listed as finalized",
            }));
        }
    }

    input_closure.sort();
    input_closure.dedup();
    Ok(Census {
        batches: batches
            .into_iter()
            .map(|(source_commit_seq, drafts)| CensusBatch {
                source_commit_seq,
                drafts,
            })
            .collect(),
        subject_addresses,
        source_ids,
        entries: entry_count,
        unresolved,
        input_closure,
    })
}

fn recover_subject(
    item: &Retained,
    candidates: &BTreeSet<String>,
    listed: usize,
) -> Option<(String, u32)> {
    let listed = u32::try_from(listed).unwrap_or(u32::MAX);
    for candidate in candidates {
        for limit in listed..=MAX_SIGNATURE_LIMIT {
            let material = format!(
                "method=getSignaturesForAddress;address={candidate};limit={limit};commitment=finalized"
            );
            if request_fingerprint(&item.source_id, SIGNATURE_METHOD, &material)
                == item.request_fingerprint
            {
                return Some((candidate.clone(), limit));
            }
        }
    }
    None
}

fn recover_signature(item: &Retained, listed: &BTreeSet<String>) -> Option<String> {
    listed
        .iter()
        .find(|signature| {
            let material = format!(
                "method=getTransaction;signature={signature};commitment=finalized;encoding=json"
            );
            request_fingerprint(&item.source_id, TRANSACTION_METHOD, &material)
                == item.request_fingerprint
        })
        .cloned()
}

// ---------------------------------------------------------------------------------------------
// Durable commit

fn commit_census(
    store: &mut SqliteStore,
    census: &Census,
    namespace: &str,
    clock_id: &StableString,
    build: &StableString,
) -> Fallible<(CommitSeq, CommitSeq)> {
    let mut first = None;
    let mut last = None;
    for batch in &census.batches {
        let admission = source_drafts(SourceDraftBatch {
            batch_id: StableString::new(format!(
                "{namespace}-census-c{}",
                batch.source_commit_seq
            ))?,
            drafts: batch.drafts.clone(),
            source_events: Vec::new(),
            cursor_advances: Vec::new(),
            registrations: Vec::new(),
            policy: AdmissionPolicy::public_source()?,
            committed_at: now()?,
            writer_clock_id: clock_id.clone(),
            committed_mono_ns: monotonic_ns(),
            writer_build: build.clone(),
        })?;
        let receipt = admission.commit(store)?;
        let seq = CommitSeq::new(receipt.commit_seq.parse::<u64>()?);
        if first.is_none() {
            first = Some(seq);
        }
        last = Some(seq);
    }
    match (first, last) {
        (Some(first), Some(last)) => Ok((first, last)),
        _ => Err("the census produced no batch to commit".into()),
    }
}

fn publish_projection(
    store: &mut SqliteStore,
    census: &Census,
    through: CommitSeq,
    namespace: &str,
    clock_id: &StableString,
    build: &StableString,
) -> Fallible<ProjectionPublicationInputV2> {
    let name = StableString::new(PRODUCER)?;
    let version = StableString::new(PRODUCER_VERSION)?;
    let projection_id = StableString::new(format!("projection:{PRODUCER}:{namespace}"))?;
    let configuration = json!({
        "producer": PRODUCER,
        "producer_version": PRODUCER_VERSION,
        "families": [
            joshi_export::LANDED_ERROR_FAMILY,
            joshi_export::LANDED_NO_ERROR_FAMILY,
        ],
        "coverage_family": COVERAGE_FAMILY,
    });
    let configuration_digest = ValueDigest::new(qualified(&serde_json::to_vec(&configuration)?))?;
    let schema_digest = ValueDigest::new(qualified(&serde_json::to_vec(&json!([
        "semantic_key",
        "value_digest",
        "evidence"
    ]))?))?;
    store.register_projection(&ProjectionRegistration {
        name: name.clone(),
        version: version.clone(),
        producer_build: build.clone(),
        configuration_digest,
        schema_digest,
        deterministic: true,
    })?;

    let artifact = serde_json::to_vec(&json!({
        "contract": "joshi.pillar7.listing_census_artifact/v1",
        "subject_addresses": census.subject_addresses.iter().collect::<Vec<_>>(),
        "source_ids": census.source_ids.iter().collect::<Vec<_>>(),
        "listed_transaction_count": census.entries.to_string(),
        "input_closure": census.input_closure,
    }))?;
    let artifact_digest = ValueDigest::new(qualified(&artifact))?;
    let result_digest = artifact_digest.clone();
    let input_closure_digest =
        ValueDigest::new(qualified(&serde_json::to_vec(&census.input_closure)?))?;
    let publication_bytes = serde_json::to_vec(&json!({
        "contract": "joshi.pillar7.listing_census_publication/v1",
        "projection_name": PRODUCER,
        "projection_version": PRODUCER_VERSION,
        "artifact_digest": artifact_digest.as_str(),
        "through_commit_seq": through.get().to_string(),
    }))?;
    let publication_bytes_digest = ValueDigest::new(qualified(&publication_bytes))?;
    let publication_digest = publication_bytes_digest.clone();
    let publication_id = StableString::new(format!("publication:{PRODUCER}:{namespace}"))?;
    let capability = ProjectionPublicationCapability::new(
        publication_id.clone(),
        projection_id.clone(),
        result_digest.clone(),
        artifact_digest.clone(),
        artifact,
        input_closure_digest.clone(),
        publication_digest.clone(),
        publication_bytes_digest.clone(),
        publication_bytes,
        through,
        None,
    )?;
    let receipt = store.commit_projection_publication_v1(
        &capability,
        &OperationalCommitContext::new(
            StableString::new(format!("{namespace}-publication"))?,
            now()?,
            clock_id.clone(),
            monotonic_ns(),
            build.clone(),
        ),
    )?;
    Ok(ProjectionPublicationInputV2 {
        publication_id,
        publication_contract: StableString::new("joshi.pillar7.listing_census_publication/v1")?,
        publication_digest,
        publication_bytes_digest,
        projection_id,
        projection_name: name,
        projection_version: version,
        result_digest,
        artifact_digest,
        input_closure_digest,
        through_commit_seq: through,
        published_commit_seq: receipt.commit_seq(),
    })
}

// ---------------------------------------------------------------------------------------------
// Export and readback

#[allow(clippy::too_many_arguments)]
fn request(
    catalog: &Path,
    catalog_schema: &StableString,
    from: CommitSeq,
    through: CommitSeq,
    export_request_id: &str,
    publication: &ProjectionPublicationInputV2,
    census: &Census,
    destination: &Path,
    python_validator: &PythonValidatorV2,
    build: &StableString,
) -> OperationalExportRequestV2 {
    let mut coverage_window_ids = census
        .batches
        .iter()
        .flat_map(|batch| batch.drafts.iter())
        .filter_map(|draft| match draft {
            EvidenceDraft::CoverageWindow(window) => {
                StableString::new(window.coverage_id.as_str()).ok()
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    coverage_window_ids.sort();
    coverage_window_ids.dedup();
    OperationalExportRequestV2 {
        catalog_snapshot_path: catalog.to_path_buf(),
        catalog_id: StableString::new("joshi-collector-live").expect("catalog id"),
        catalog_schema: catalog_schema.clone(),
        from_commit_seq: from,
        through_commit_seq: through,
        export_request_id: StableString::new(export_request_id).expect("export request id"),
        producer_build: build.clone(),
        created_at: now().expect("clock"),
        producer_projection_publication_id: publication.publication_id.clone(),
        publications: vec![OperationalPublicationV2::Projection(publication.clone())],
        coverage_window_ids,
        destination: destination.to_path_buf(),
        python_validator: python_validator.clone(),
        g0_import_artifact: None,
    }
}

fn export_summary(root: &Path, snapshot: &joshi_export::ValidatedProductionSnapshotV2) -> Value {
    json!({
        "root": root.display().to_string(),
        "snapshot_id": snapshot.snapshot_id().as_str(),
        "manifest_digest": snapshot.manifest_digest().as_str(),
        "from_commit_seq": snapshot.commit_range().0.get().to_string(),
        "through_commit_seq": snapshot.commit_range().1.get().to_string(),
        "table_count": snapshot.tables().len().to_string(),
        "nonempty_tables": snapshot.tables().iter().filter(|table| table.row_count() > 0)
            .map(|table| json!({"name": table.name().as_str(), "rows": table.row_count().to_string()}))
            .collect::<Vec<_>>(),
        "total_rows": snapshot.tables().iter().map(joshi_export::ValidatedTableArtifactV1::row_count).sum::<u64>().to_string(),
        "rust_validation": snapshot.rust_validation().validator(),
        "python_validation": snapshot.python_validation().validator(),
    })
}

fn python_census(uv: &Path, analysis: &Path, snapshot: &Path) -> Fallible<Value> {
    let output = Command::new(uv)
        .arg("--directory")
        .arg(analysis)
        .args([
            "run",
            "--locked",
            "--offline",
            "joshi-analysis",
            "listing-census",
            "--snapshot",
        ])
        .arg(snapshot)
        .output()?;
    if !output.status.success() {
        return Err(format!(
            "python listing census failed: {}",
            String::from_utf8_lossy(&output.stderr)
        )
        .into());
    }
    Ok(serde_json::from_slice(&output.stdout)?)
}

fn compare(rust: &ListingErrorCensusV1, python: &Value) -> Fallible<Value> {
    let expectations = [
        ("landed_error_count", rust.landed_error_count.to_string()),
        (
            "landed_no_error_count",
            rust.landed_no_error_count.to_string(),
        ),
        ("enumerated_count", rust.enumerated_count.to_string()),
        (
            "provenance_edge_count",
            rust.provenance_edge_count.to_string(),
        ),
        ("corroborated_count", rust.corroborated_count.to_string()),
        ("snapshot_id", rust.snapshot_id.clone()),
        ("manifest_digest", rust.manifest_digest.clone()),
        ("through_commit_seq", rust.through_commit_seq.clone()),
        ("from_commit_seq", rust.from_commit_seq.clone()),
    ];
    for (field, expected) in &expectations {
        let actual = python[*field].as_str().unwrap_or("<absent>");
        if actual != expected {
            return Err(
                format!("runtimes disagree on {field}: rust={expected} python={actual}").into(),
            );
        }
    }
    Ok(json!({
        "compared_fields": expectations.iter().map(|(field, _)| *field).collect::<Vec<_>>(),
        "identical": true,
    }))
}

// ---------------------------------------------------------------------------------------------
// Small helpers

fn required(arguments: &[String], flag: &str) -> Fallible<String> {
    optional(arguments, flag).ok_or_else(|| format!("{flag} is required").into())
}

fn optional(arguments: &[String], flag: &str) -> Option<String> {
    arguments
        .iter()
        .position(|value| value == flag)
        .and_then(|index| arguments.get(index + 1))
        .cloned()
}

fn qualified(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

fn now() -> Fallible<UtcTimestamp> {
    let value = OffsetDateTime::now_utc();
    let truncated = value.replace_nanosecond(value.microsecond() * 1_000)?;
    Ok(UtcTimestamp::new(truncated)?)
}

fn utc_from_micros(value: i64) -> Fallible<UtcTimestamp> {
    Ok(UtcTimestamp::new(
        OffsetDateTime::from_unix_timestamp_nanos(i128::from(value) * 1_000)?,
    )?)
}

fn utc_from_seconds(value: i64) -> Fallible<UtcTimestamp> {
    Ok(UtcTimestamp::new(OffsetDateTime::from_unix_timestamp(
        value,
    )?)?)
}

fn monotonic_ns() -> u64 {
    u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or_default(),
    )
    .unwrap_or(u64::MAX)
}
