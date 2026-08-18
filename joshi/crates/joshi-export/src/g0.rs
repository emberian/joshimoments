use crate::{
    ExportError, Result,
    production::G0ImportArtifactReadbackV1,
    snapshot::{
        logical_table_digest, parse_json_without_duplicate_keys, qualified_sha256,
        qualified_sha256_file, read_parquet, schema_descriptor,
    },
    specs::{G0_TABLE_SPECS, TableSpec},
};
use arrow_array::{
    ArrayRef, BinaryArray, Int64Array, RecordBatch, StringArray, TimestampMicrosecondArray,
};
use arrow_schema::{DataType, TimeUnit};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_projection::ProjectionAuthority;
use joshi_publication::{
    CockpitV2CoverageRefV1, CockpitV2GapRefV1, CockpitV2MembershipKind, CockpitV2MembershipRefV1,
    CockpitV2OmissionV1, CockpitV2SourceFactRefV1, CockpitV2SurfaceProfileRefV1, ProtectionDomain,
    parse_cockpit_v2_head, parse_cockpit_v2_publication,
};
use joshi_scientific_memory::{
    MemoryKernel, MemoryOccurrence, SceneBinding, parse_memory_occurrence_exact,
};
use rusqlite::{Connection, params};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fs, path::Path, sync::Arc};

pub(crate) fn relation_batches(
    connection: &Connection,
    from: CommitSeq,
    through: CommitSeq,
    import_artifact: Option<&G0ImportArtifactReadbackV1>,
) -> Result<BTreeMap<&'static str, Vec<RecordBatch>>> {
    let from = sql_commit(from)?;
    let through = sql_commit(through)?;
    let mut rows = BTreeMap::new();
    rows.insert(
        "source_fact_occurrences",
        source_rows(connection, from, through)?,
    );
    let publications = publication_rows(connection, from, through)?;
    rows.insert("scene_occurrences", scene_rows(&publications));
    rows.insert("publication_occurrences", publications);
    rows.insert(
        "act_occurrences",
        memory_rows(connection, from, through, "operator_act")?,
    );
    rows.insert(
        "episode_occurrences",
        memory_rows(connection, from, through, "episode")?,
    );
    rows.insert("run_occurrences", run_rows(connection, from, through)?);
    rows.insert(
        "spool_catalog_occurrences",
        spool_rows(connection, from, through)?,
    );
    rows.insert(
        "status_occurrences",
        status_rows(connection, from, through)?,
    );
    rows.insert(
        "export_occurrences",
        export_rows(connection, from, through)?,
    );
    rows.insert(
        "import_occurrences",
        import_rows(connection, from, through)?,
    );
    validate_connected_closure(&rows)?;
    validate_import_artifact_readback(
        &rows["import_occurrences"],
        import_artifact.ok_or_else(|| invalid("V10 import artifact readback is absent"))?,
    )?;

    let mut output = BTreeMap::new();
    for spec in G0_TABLE_SPECS {
        let relation = rows
            .remove(spec.name)
            .ok_or_else(|| invalid(format!("missing G0 relation {}", spec.name)))?;
        if relation.is_empty() {
            return Err(invalid(format!(
                "G0 relation {} must be nonempty within the exact commit range",
                spec.name
            )));
        }
        output.insert(spec.name, vec![batch(spec, &relation)?]);
    }
    Ok(output)
}

pub(crate) fn validate_connected_closure(rows: &BTreeMap<&str, Vec<Value>>) -> Result<()> {
    validate_relational_closure(rows)?;
    let source_row = &rows["source_fact_occurrences"][0];
    let publication_row = &rows["publication_occurrences"][0];
    let scene_row = &rows["scene_occurrences"][0];
    let source = validate_source_bytes(source_row)?;
    let (publication, _head) = validate_publication_bytes(publication_row)?;
    if exact_bytes(scene_row, "publication_bytes")?
        != exact_bytes(publication_row, "publication_bytes")?
        || exact_bytes(scene_row, "head_bytes")? != exact_bytes(publication_row, "head_bytes")?
    {
        return Err(invalid(
            "scene occurrence does not retain the exact publication/head bytes",
        ));
    }
    let manifest = &publication.manifest;
    if source.surface_profile != manifest.surface_profile
        || source.eligible_subjects != manifest.observed_universe.eligible_subjects
        || source.facts != manifest.source_facts
        || source.memberships != manifest.memberships
        || source.coverage != manifest.coverage
        || source.gaps != manifest.gaps
        || source.rendered_subjects != manifest.rendered_subjects
        || source.omissions != manifest.omissions
        || manifest.cutoff.commit_through != Some(source.known_through_commit_seq)
        || manifest.cutoff.knowledge_at != source.maximum_input_available_at
    {
        return Err(invalid(
            "Cockpit V2 publication does not preserve the exact source fact/partition closure",
        ));
    }

    let mut memory = Vec::new();
    for row in &rows["act_occurrences"] {
        let occurrence = validate_memory_bytes(row, "operator_act")?;
        if let MemoryOccurrence::OperatorAct(act) = &occurrence {
            let SceneBinding::Committed(scene) = &act.scene else {
                return Err(invalid("G0 act lacks committed scene bytes"));
            };
            if scene.scene_digest.as_str() != publication.publication_digest.as_str()
                || scene.catalog_cutoff.value() != publication.commit_seq.get()
            {
                return Err(invalid(
                    "G0 act scene bytes differ from the exact Cockpit V2 publication",
                ));
            }
        }
        memory.push((
            row["queue_generation"]
                .as_i64()
                .ok_or_else(|| invalid("memory queue generation is not int64"))?,
            occurrence,
        ));
    }
    for row in &rows["episode_occurrences"] {
        memory.push((
            row["queue_generation"]
                .as_i64()
                .ok_or_else(|| invalid("memory queue generation is not int64"))?,
            validate_memory_bytes(row, "episode")?,
        ));
    }
    memory.sort_by_key(|(generation, _)| *generation);
    if memory.windows(2).any(|window| window[0].0 >= window[1].0) {
        return Err(invalid(
            "memory queue generations are not strictly increasing",
        ));
    }
    let mut kernel = MemoryKernel::new();
    for (_, occurrence) in memory {
        kernel
            .append(occurrence)
            .map_err(|error| invalid(format!("invalid G0 memory prefix: {error}")))?;
    }
    Ok(())
}

#[allow(clippy::too_many_lines)]
fn validate_relational_closure(rows: &BTreeMap<&str, Vec<Value>>) -> Result<()> {
    let relation = |name: &str| {
        rows.get(name)
            .map(Vec::as_slice)
            .ok_or_else(|| invalid(format!("missing G0 relation {name}")))
    };
    let single = |name: &str| -> Result<&Value> {
        let values = relation(name)?;
        if values.len() != 1 {
            return Err(invalid(format!(
                "G0 relation {name} must contain one exact root occurrence"
            )));
        }
        Ok(&values[0])
    };
    let run = single("run_occurrences")?;
    let run_id = required_text(run, "run_registration_id")?;
    let source = single("source_fact_occurrences")?;
    let publication = single("publication_occurrences")?;
    let scene = single("scene_occurrences")?;
    let episode = single("episode_occurrences")?;
    let export = single("export_occurrences")?;
    let import = single("import_occurrences")?;
    let spools = relation("spool_catalog_occurrences")?;
    let acts = relation("act_occurrences")?;
    let statuses = relation("status_occurrences")?;
    if spools.is_empty() || acts.is_empty() || statuses.is_empty() {
        return Err(invalid(
            "G0 root requires nonempty spool, act, and status support",
        ));
    }
    for value in spools
        .iter()
        .chain(statuses)
        .chain([source, export, import])
    {
        if required_text(value, "run_registration_id")? != run_id {
            return Err(invalid("G0 relations mix distinct run registrations"));
        }
    }
    let spool_ids = spools
        .iter()
        .map(|value| required_text(value, "catalog_admission_id"))
        .collect::<Result<Vec<_>>>()?;
    if !spool_ids.contains(&required_text(source, "catalog_admission_id")?) {
        return Err(invalid(
            "source occurrence lacks its in-range spool/catalog support",
        ));
    }
    let known_through = source["known_through_commit_seq"]
        .as_i64()
        .ok_or_else(|| invalid("source known-through commit is not int64"))?;
    if !spools.iter().any(|spool| {
        spool["catalog_admission_id"] == source["catalog_admission_id"]
            && spool["store_commit_seq"].as_i64() == Some(known_through)
    }) {
        return Err(invalid(
            "source occurrence lacks its exact in-range spool store commit",
        ));
    }
    let source_id = required_text(source, "source_occurrence_id")?;
    if required_text(publication, "source_occurrence_id")? != source_id
        || required_text(scene, "source_occurrence_id")? != source_id
        || publication["through_commit_seq"].as_i64() != Some(known_through)
    {
        return Err(invalid(
            "publication/scene does not close the exact source occurrence",
        ));
    }
    let publication_id = required_text(publication, "publication_id")?;
    if required_text(scene, "scene_publication_id")? != publication_id
        || required_text(scene, "publication_digest")?
            != required_text(publication, "publication_digest")?
        || required_text(scene, "head_digest")? != required_text(publication, "head_digest")?
    {
        return Err(invalid(
            "scene occurrence differs from its headed publication",
        ));
    }
    for act in acts {
        if required_text(act, "scene_publication_id")? != publication_id
            || required_text(act, "session_id")? != required_text(episode, "session_id")?
        {
            return Err(invalid(
                "operator act is foreign to the selected scene/session",
            ));
        }
    }
    if required_text(episode, "scene_publication_id")? != publication_id {
        return Err(invalid("episode is foreign to the selected scene"));
    }
    let act_ids = acts
        .iter()
        .map(|value| required_text(value, "act_id"))
        .collect::<Result<Vec<_>>>()?;
    if !act_ids.contains(&required_text(episode, "opening_act_id")?)
        || episode["closing_act_id"]
            .as_str()
            .is_some_and(|value| !act_ids.contains(&value))
    {
        return Err(invalid(
            "episode lacks its in-range opening/closing act support",
        ));
    }
    let export_binding_id = required_text(export, "export_binding_id")?;
    if required_text(import, "export_binding_id")? != export_binding_id
        || required_text(import, "export_request_id")?
            != required_text(export, "export_request_id")?
        || required_text(import, "snapshot_id")? != required_text(export, "snapshot_id")?
        || required_text(import, "truth_fingerprint_digest")?
            != required_text(export, "truth_fingerprint_digest")?
    {
        return Err(invalid(
            "import does not close the selected exact export/truth",
        ));
    }
    let export_commit = export["available_commit_seq"]
        .as_i64()
        .ok_or_else(|| invalid("export commit is not int64"))?;
    if !statuses.iter().any(|status| {
        status["component"] == "export"
            && status["state"] == "ready"
            && status["evidence_commit_seq"].as_i64() == Some(export_commit)
    }) {
        return Err(invalid(
            "G0 status closure lacks a ready export record bound to the exact export commit",
        ));
    }
    let status_ids = statuses
        .iter()
        .map(|status| required_text(status, "record_id"))
        .collect::<Result<Vec<_>>>()?;
    for status in statuses {
        if status["predecessor_record_id"]
            .as_str()
            .is_some_and(|predecessor| !status_ids.contains(&predecessor))
        {
            return Err(invalid(
                "G0 status occurrence lacks its in-range predecessor",
            ));
        }
    }
    if publication["supersedes_publication_id"].as_str().is_some()
        || publication["supersedes_head_publication_id"]
            .as_str()
            .is_some()
    {
        return Err(invalid(
            "G0 headed publication lacks its in-range supersession predecessor",
        ));
    }
    if source["protection_class"] != "public_integrity"
        || acts
            .iter()
            .chain([episode])
            .any(|row| row["qualification"] != "fixture_authority_unverified_semantic")
        || import["claim_scope"] != "descriptive_noncausal"
    {
        return Err(invalid(
            "G0 source, memory, or import qualification differs",
        ));
    }
    for value in relation("source_fact_occurrences")?
        .iter()
        .chain(relation("publication_occurrences")?)
        .chain(relation("scene_occurrences")?)
        .chain(relation("act_occurrences")?)
        .chain(relation("episode_occurrences")?)
        .chain(relation("run_occurrences")?)
        .chain(relation("spool_catalog_occurrences")?)
        .chain(relation("status_occurrences")?)
        .chain(relation("export_occurrences")?)
        .chain(relation("import_occurrences")?)
    {
        if value["authority"] != "read_only_no_execution" {
            return Err(invalid("G0 occurrence exceeds read_only_no_execution"));
        }
    }
    Ok(())
}

pub(crate) fn validate_manifest_publication(
    rows: &BTreeMap<&str, Vec<Value>>,
    publications: &Value,
) -> Result<()> {
    let relation = rows
        .get("publication_occurrences")
        .filter(|rows| rows.len() == 1)
        .and_then(|rows| rows.first())
        .ok_or_else(|| invalid("G0 publication relation is not singular"))?;
    let headed = publications
        .as_array()
        .ok_or_else(|| invalid("manifest publications are not an array"))?
        .iter()
        .filter(|value| value["kind"] == "cockpit_v2")
        .collect::<Vec<_>>();
    if headed.len() != 1 {
        return Err(invalid(
            "G0 manifest requires one exact Cockpit V2 publication",
        ));
    }
    let manifest = headed[0];
    for field in [
        "publication_id",
        "publication_contract",
        "publication_digest",
        "publication_bytes_digest",
        "source_occurrence_id",
        "semantic_digest",
        "container_digest",
        "checkpoint_digest",
        "supersedes_publication_id",
        "head_digest",
        "supersedes_head_publication_id",
        "authority",
    ] {
        if manifest[field] != relation[field] {
            return Err(invalid(format!(
                "G0 manifest publication {field} differs from its relation"
            )));
        }
    }
    for (manifest_field, relation_field) in [
        ("through_commit_seq", "through_commit_seq"),
        ("publication_commit_seq", "publication_commit_seq"),
        ("published_commit_seq", "available_commit_seq"),
    ] {
        let manifest_value = manifest[manifest_field]
            .as_str()
            .and_then(|value| value.parse::<i64>().ok());
        if manifest_value != relation[relation_field].as_i64() {
            return Err(invalid(format!(
                "G0 manifest publication {manifest_field} differs from its relation"
            )));
        }
    }
    Ok(())
}

fn required_text<'a>(value: &'a Value, field: &str) -> Result<&'a str> {
    value[field]
        .as_str()
        .filter(|text| !text.is_empty())
        .ok_or_else(|| invalid(format!("G0 {field} is empty")))
}

#[derive(Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SourceOccurrenceWire {
    contract: StableString,
    schema_version: u16,
    source_occurrence_id: StableString,
    run_registration_id: StableString,
    catalog_admission_id: StableString,
    source_receipt_digest: ValueDigest,
    source_id: StableString,
    surface_profile: CockpitV2SurfaceProfileRefV1,
    facts: Vec<CockpitV2SourceFactRefV1>,
    eligible_subjects: Vec<StableString>,
    memberships: Vec<CockpitV2MembershipRefV1>,
    coverage: Vec<CockpitV2CoverageRefV1>,
    gaps: Vec<CockpitV2GapRefV1>,
    rendered_subjects: Vec<StableString>,
    omissions: Vec<CockpitV2OmissionV1>,
    known_through_commit_seq: CommitSeq,
    maximum_input_available_at: UtcTimestamp,
    protection: ProtectionDomain,
    authority: ProjectionAuthority,
}

fn exact_bytes(value: &Value, field: &str) -> Result<Vec<u8>> {
    if let Some(bytes) = value[field].as_array() {
        return bytes
            .iter()
            .map(|byte| {
                byte.as_u64()
                    .and_then(|value| u8::try_from(value).ok())
                    .ok_or_else(|| invalid(format!("G0 {field} byte is invalid")))
            })
            .collect();
    }
    let hex = value[field]
        .as_object()
        .and_then(|object| object.get("bytes_hex"))
        .and_then(Value::as_str)
        .ok_or_else(|| invalid(format!("G0 {field} bytes are absent")))?;
    if hex.len() % 2 != 0 || !hex.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(invalid(format!("G0 {field} hex bytes are invalid")));
    }
    (0..hex.len())
        .step_by(2)
        .map(|index| {
            u8::from_str_radix(&hex[index..index + 2], 16)
                .map_err(|_| invalid(format!("G0 {field} hex bytes are invalid")))
        })
        .collect()
}

fn validate_source_bytes(row: &Value) -> Result<SourceOccurrenceWire> {
    let bytes = exact_bytes(row, "descriptor_bytes")?;
    let parsed: SourceOccurrenceWire = serde_json::from_slice(&bytes)?;
    let hot = parsed
        .memberships
        .iter()
        .filter(|membership| membership.membership == CockpitV2MembershipKind::Hot)
        .count();
    let cold = parsed
        .memberships
        .iter()
        .filter(|membership| membership.membership == CockpitV2MembershipKind::ColdControl)
        .count();
    if serde_json::to_vec(&parsed)? != bytes
        || parsed.schema_version != 1
        || parsed.contract.as_str() != required_text(row, "descriptor_contract")?
        || parsed.source_occurrence_id.as_str() != required_text(row, "source_occurrence_id")?
        || parsed.run_registration_id.as_str() != required_text(row, "run_registration_id")?
        || parsed.catalog_admission_id.as_str() != required_text(row, "catalog_admission_id")?
        || parsed.source_receipt_digest.as_str() != required_text(row, "receipt_digest")?
        || parsed.source_id.as_str() != required_text(row, "source_id")?
        || parsed.surface_profile.profile_digest.as_str()
            != required_text(row, "surface_profile_digest")?
        || i64::try_from(parsed.facts.len()).ok() != row["fact_count"].as_i64()
        || i64::try_from(parsed.eligible_subjects.len()).ok()
            != row["eligible_subject_count"].as_i64()
        || i64::try_from(parsed.memberships.len()).ok() != row["membership_count"].as_i64()
        || i64::try_from(parsed.coverage.len()).ok() != row["coverage_count"].as_i64()
        || i64::try_from(parsed.gaps.len()).ok() != row["gap_count"].as_i64()
        || i64::try_from(parsed.rendered_subjects.len()).ok()
            != row["rendered_subject_count"].as_i64()
        || i64::try_from(parsed.omissions.len()).ok() != row["omission_count"].as_i64()
        || i64::try_from(hot).ok() != row["hot_subject_count"].as_i64()
        || i64::try_from(cold).ok() != row["cold_control_subject_count"].as_i64()
        || i64::try_from(parsed.known_through_commit_seq.get()).ok()
            != row["known_through_commit_seq"].as_i64()
        || parsed.maximum_input_available_at != exact_timestamp(row, "maximum_input_available_at")?
        || parsed.protection != ProtectionDomain::Public
        || parsed.authority != ProjectionAuthority::ReadOnlyNoExecution
        || format!("sha256:{:x}", Sha256::digest(&bytes))
            != required_text(row, "descriptor_digest")?
        || u64::try_from(bytes.len()).ok() != row["descriptor_byte_length"].as_u64()
    {
        return Err(invalid(
            "source occurrence bytes do not close their exact stored scalars",
        ));
    }
    Ok(parsed)
}

fn exact_timestamp(row: &Value, field: &str) -> Result<UtcTimestamp> {
    if let Some(micros) = row[field].as_i64() {
        return timestamp_micros(micros);
    }
    row[field]
        .as_str()
        .ok_or_else(|| invalid(format!("G0 {field} is not an exact timestamp")))?
        .parse()
        .map_err(|error| invalid(format!("G0 {field} timestamp: {error}")))
}

fn timestamp_micros(value: i64) -> Result<UtcTimestamp> {
    let nanos = i128::from(value)
        .checked_mul(1_000)
        .ok_or_else(|| invalid("G0 timestamp exceeds nanosecond range"))?;
    let instant = time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(|error| invalid(error.to_string()))?;
    UtcTimestamp::new(instant).map_err(|error| invalid(error.to_string()))
}

fn validate_publication_bytes(
    row: &Value,
) -> Result<(
    joshi_publication::CockpitV2PublicationV1,
    joshi_publication::CockpitV2HeadV1,
)> {
    let publication_bytes = exact_bytes(row, "publication_bytes")?;
    let head_bytes = exact_bytes(row, "head_bytes")?;
    let publication = parse_cockpit_v2_publication(&publication_bytes)
        .map_err(|error| invalid(format!("invalid Cockpit V2 publication bytes: {error}")))?;
    let head = parse_cockpit_v2_head(&head_bytes)
        .map_err(|error| invalid(format!("invalid Cockpit V2 head bytes: {error}")))?;
    head.validate_against(&publication)
        .map_err(|error| invalid(format!("Cockpit V2 head/body mismatch: {error}")))?;
    let supersedes = publication
        .supersedes_publication_id
        .as_ref()
        .map(joshi_publication::CockpitPublicationId::as_str);
    let through = publication
        .manifest
        .cutoff
        .commit_through
        .ok_or_else(|| invalid("Cockpit V2 publication omits its store commit cutoff"))?;
    if publication.publication_id.as_str() != required_text(row, "publication_id")?
        || publication.contract.as_str() != required_text(row, "publication_contract")?
        || publication.publication_digest.as_str() != required_text(row, "publication_digest")?
        || qualified_sha256(&publication_bytes) != required_text(row, "publication_bytes_digest")?
        || u64::try_from(publication_bytes.len()).ok() != row["publication_byte_length"].as_u64()
        || publication.manifest.semantic_digest.as_str() != required_text(row, "semantic_digest")?
        || publication.manifest.container_digest.as_str() != required_text(row, "container_digest")?
        || publication.checkpoint.checkpoint_digest.as_str()
            != required_text(row, "checkpoint_digest")?
        || i64::try_from(through.get()).ok() != row["through_commit_seq"].as_i64()
        || supersedes != row["supersedes_publication_id"].as_str()
        || i64::try_from(publication.commit_seq.get()).ok()
            != row["publication_commit_seq"].as_i64()
        || head.publication_id != publication.publication_id
        || head.head_digest.as_str() != required_text(row, "head_digest")?
        || u64::try_from(head_bytes.len()).ok() != row["head_byte_length"].as_u64()
        || head.authority != ProjectionAuthority::ReadOnlyNoExecution
        || publication.authority != ProjectionAuthority::ReadOnlyNoExecution
    {
        return Err(invalid(
            "Cockpit V2 publication/head bytes do not close their exact stored scalars",
        ));
    }
    Ok((publication, head))
}

fn source_rows(connection: &Connection, from: i64, through: i64) -> Result<Vec<Value>> {
    let mut statement = connection.prepare(
        "SELECT source_occurrence_id,run_registration_id,catalog_admission_id,source_id,
                receipt_sha256,descriptor_contract,descriptor_sha256,descriptor_bytes,
                descriptor_byte_length,surface_profile_sha256,fact_count,eligible_subject_count,
                membership_count,coverage_count,gap_count,rendered_subject_count,omission_count,
                hot_subject_count,cold_control_subject_count,known_through_commit_seq,
                maximum_input_available_wall_us,protection_class,authority,created_commit_seq
         FROM wave5_source_occurrence_v1
         WHERE created_commit_seq BETWEEN ?1 AND ?2
           AND known_through_commit_seq BETWEEN ?1 AND ?2
         ORDER BY source_occurrence_id",
    )?;
    statement
        .query_map(params![from, through], |row| {
            let descriptor_digest = row.get::<_, String>(6)?;
            let descriptor_bytes = row.get::<_, Vec<u8>>(7)?;
            Ok(json!({
                "source_occurrence_id":row.get::<_,String>(0)?,
                "run_registration_id":row.get::<_,String>(1)?,
                "catalog_admission_id":row.get::<_,String>(2)?,
                "source_id":row.get::<_,String>(3)?,
                "receipt_digest":qualified(&row.get::<_,String>(4)?),
                "descriptor_contract":row.get::<_,String>(5)?,
                "descriptor_digest":checked_blob(&descriptor_digest,&descriptor_bytes),
                "descriptor_bytes":descriptor_bytes.clone(),
                "descriptor_byte_length":checked_length(row.get::<_,i64>(8)?,&descriptor_bytes),
                "surface_profile_digest":qualified(&row.get::<_,String>(9)?),
                "fact_count":row.get::<_,i64>(10)?,
                "eligible_subject_count":row.get::<_,i64>(11)?,
                "membership_count":row.get::<_,i64>(12)?,
                "coverage_count":row.get::<_,i64>(13)?,
                "gap_count":row.get::<_,i64>(14)?,
                "rendered_subject_count":row.get::<_,i64>(15)?,
                "omission_count":row.get::<_,i64>(16)?,
                "hot_subject_count":row.get::<_,i64>(17)?,
                "cold_control_subject_count":row.get::<_,i64>(18)?,
                "known_through_commit_seq":row.get::<_,i64>(19)?,
                "maximum_input_available_at":row.get::<_,i64>(20)?,
                "protection_class":row.get::<_,String>(21)?,
                "authority":row.get::<_,String>(22)?,
                "available_commit_seq":row.get::<_,i64>(23)?,
            }))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?
        .into_iter()
        .map(|row| {
            let row = checked_row(row)?;
            validate_source_bytes(&row)?;
            Ok(row)
        })
        .collect()
}

fn publication_rows(connection: &Connection, from: i64, through: i64) -> Result<Vec<Value>> {
    let mut statement = connection.prepare(
        "SELECT p.publication_id,p.preparation_id,p.source_occurrence_id,
                p.publication_contract,p.publication_sha256,p.publication_bytes_sha256,
                p.publication_bytes,p.publication_byte_length,p.semantic_sha256,
                p.container_sha256,p.checkpoint_sha256,p.through_commit_seq,
                p.supersedes_publication_id,h.head_sha256,h.head_bytes,h.head_byte_length,
                h.supersedes_head_publication_id,h.authority,p.created_commit_seq,
                h.created_commit_seq
         FROM cockpit_v2_publication_v1 p JOIN cockpit_v2_head_v1 h USING(publication_id)
         JOIN cockpit_v2_preparation_v1 prep ON prep.preparation_id=p.preparation_id
             AND prep.source_occurrence_id=p.source_occurrence_id
         JOIN wave5_source_occurrence_v1 source USING(source_occurrence_id)
         WHERE p.created_commit_seq BETWEEN ?1 AND ?2
           AND h.created_commit_seq BETWEEN ?1 AND ?2
           AND prep.created_commit_seq BETWEEN ?1 AND ?2
           AND source.created_commit_seq BETWEEN ?1 AND ?2
           AND p.through_commit_seq BETWEEN ?1 AND ?2
           AND prep.through_commit_seq BETWEEN ?1 AND ?2
           AND source.known_through_commit_seq BETWEEN ?1 AND ?2
         ORDER BY p.publication_id",
    )?;
    statement
        .query_map(params![from, through], |row| {
            let publication_bytes = row.get::<_,Vec<u8>>(6)?;
            let publication_bytes_digest = row.get::<_,String>(5)?;
            let head_bytes = row.get::<_,Vec<u8>>(14)?;
            let head_digest = row.get::<_,String>(13)?;
            Ok(json!({
                "publication_id":row.get::<_,String>(0)?,
                "preparation_id":row.get::<_,String>(1)?,
                "source_occurrence_id":row.get::<_,String>(2)?,
                "publication_contract":row.get::<_,String>(3)?,
                "publication_digest":qualified(&row.get::<_,String>(4)?),
                "publication_bytes_digest":checked_blob(&publication_bytes_digest,&publication_bytes),
                "publication_bytes":publication_bytes.clone(),
                "publication_byte_length":checked_length(row.get::<_,i64>(7)?,&publication_bytes),
                "semantic_digest":qualified(&row.get::<_,String>(8)?),
                "container_digest":qualified(&row.get::<_,String>(9)?),
                "checkpoint_digest":qualified(&row.get::<_,String>(10)?),
                "through_commit_seq":row.get::<_,i64>(11)?,
                "supersedes_publication_id":row.get::<_,Option<String>>(12)?,
                "head_digest":qualified(&head_digest),
                "head_bytes":head_bytes.clone(),
                "head_byte_length":checked_length(row.get::<_,i64>(15)?,&head_bytes),
                "supersedes_head_publication_id":row.get::<_,Option<String>>(16)?,
                "authority":row.get::<_,String>(17)?,
                "publication_commit_seq":row.get::<_,i64>(18)?,
                "available_commit_seq":row.get::<_,i64>(19)?,
            }))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?
        .into_iter()
        .map(|row| {
            let row = checked_row(row)?;
            validate_publication_bytes(&row)?;
            Ok(row)
        })
        .collect()
}

fn scene_rows(publications: &[Value]) -> Vec<Value> {
    publications
        .iter()
        .map(|row| {
            json!({
                "scene_publication_id":row["publication_id"],
                "source_occurrence_id":row["source_occurrence_id"],
                "publication_digest":row["publication_digest"],
                "publication_bytes":row["publication_bytes"],
                "head_digest":row["head_digest"],
                "head_bytes":row["head_bytes"],
                "supersedes_scene_publication_id":row["supersedes_head_publication_id"],
                "authority":row["authority"],
                "available_commit_seq":row["available_commit_seq"],
            })
        })
        .collect()
}

fn validate_memory_bytes(row: &Value, expected_kind: &str) -> Result<MemoryOccurrence> {
    let bytes = exact_bytes(row, "occurrence_bytes")?;
    let occurrence = parse_memory_occurrence_exact(&bytes)
        .map_err(|error| invalid(format!("invalid scientific-memory bytes: {error}")))?;
    let digest = occurrence
        .exact_digest()
        .map_err(|error| invalid(format!("memory digest failed: {error}")))?;
    if digest.as_str() != required_text(row, "occurrence_digest")?
        || u64::try_from(bytes.len()).ok() != row["occurrence_byte_length"].as_u64()
    {
        return Err(invalid(
            "scientific-memory bytes differ from their exact digest/length",
        ));
    }
    match (&occurrence, expected_kind) {
        (MemoryOccurrence::OperatorAct(act), "operator_act") => {
            let SceneBinding::Committed(scene) = &act.scene else {
                return Err(invalid("G0 operator act lacks a committed scene"));
            };
            if occurrence.occurrence_id() != required_text(row, "act_id")?
                || act.session_id.as_str() != required_text(row, "session_id")?
                || scene.scene_id.as_str() != required_text(row, "scene_publication_id")?
                || act.occurred_at.value().to_string() != required_text(row, "logical_start_tick")?
                || !row["logical_end_tick"].is_null()
            {
                return Err(invalid(
                    "operator-act bytes do not close their exact stored scalars",
                ));
            }
        }
        (MemoryOccurrence::Episode(episode), "episode") => {
            let opening = episode
                .act_ids
                .first()
                .map(|act| format!("act:{}", act.as_str()))
                .ok_or_else(|| invalid("G0 episode bytes contain no opening act"))?;
            let closing = episode
                .act_ids
                .last()
                .map(|act| format!("act:{}", act.as_str()))
                .ok_or_else(|| invalid("G0 episode bytes contain no closing act"))?;
            if occurrence.occurrence_id() != required_text(row, "episode_id")?
                || episode.session_id.as_str() != required_text(row, "session_id")?
                || opening != required_text(row, "opening_act_id")?
                || Some(closing.as_str()) != row["closing_act_id"].as_str()
                || episode.started_at.value().to_string()
                    != required_text(row, "logical_start_tick")?
                || episode
                    .ended_at
                    .map(|tick| tick.value().to_string())
                    .as_deref()
                    != row["logical_end_tick"].as_str()
            {
                return Err(invalid(
                    "episode bytes do not close their exact stored scalars",
                ));
            }
        }
        _ => {
            return Err(invalid(
                "G0 memory relation contains an unsupported occurrence kind",
            ));
        }
    }
    Ok(occurrence)
}

fn memory_rows(connection: &Connection, from: i64, through: i64, kind: &str) -> Result<Vec<Value>> {
    let mut statement = connection.prepare(
        "SELECT occurrence_id,occurrence_sha256,occurrence_bytes,occurrence_byte_length,
                session_id,scene_publication_id,opening_act_id,closing_act_id,
                logical_start_tick,logical_end_tick,queue_generation,qualification,authority,
                created_commit_seq
         FROM scientific_memory_occurrence_v1
         WHERE occurrence_kind=?1 AND created_commit_seq BETWEEN ?2 AND ?3
         ORDER BY occurrence_id",
    )?;
    statement
        .query_map(params![kind, from, through], |row| {
            let bytes = row.get::<_, Vec<u8>>(2)?;
            let digest = row.get::<_, String>(1)?;
            let common = json!({
                "session_id":row.get::<_,String>(4)?,
                "scene_publication_id":row.get::<_,String>(5)?,
                "occurrence_digest":checked_blob(&digest,&bytes),
                "occurrence_bytes":bytes.clone(),
                "occurrence_byte_length":checked_length(row.get::<_,i64>(3)?,&bytes),
                "logical_start_tick":row.get::<_,String>(8)?,
                "logical_end_tick":row.get::<_,Option<String>>(9)?,
                "queue_generation":row.get::<_,i64>(10)?,
                "qualification":row.get::<_,String>(11)?,
                "authority":row.get::<_,String>(12)?,
                "available_commit_seq":row.get::<_,i64>(13)?,
            });
            let mut object = common.as_object().cloned().expect("JSON object");
            if kind == "operator_act" {
                object.insert("act_id".into(), json!(row.get::<_, String>(0)?));
            } else {
                object.insert("episode_id".into(), json!(row.get::<_, String>(0)?));
                object.insert("opening_act_id".into(), json!(row.get::<_, String>(6)?));
                object.insert(
                    "closing_act_id".into(),
                    json!(row.get::<_, Option<String>>(7)?),
                );
            }
            Ok(Value::Object(object))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?
        .into_iter()
        .map(|row| {
            let row = checked_row(row)?;
            validate_memory_bytes(&row, kind)?;
            Ok(row)
        })
        .collect()
}

fn run_rows(connection: &Connection, from: i64, through: i64) -> Result<Vec<Value>> {
    let mut statement = connection.prepare(
        "SELECT run_registration_id,registration_sha256,registration_bytes,
                registration_byte_length,build_sha256,source_tree_sha256,configuration_sha256,
                budget_sha256,privacy_sha256,daily_surface_profile_sha256,authority,
                created_commit_seq
         FROM wave5_run_registration_v1 WHERE created_commit_seq BETWEEN ?1 AND ?2
         ORDER BY run_registration_id",
    )?;
    statement
        .query_map(params![from, through], |row| {
            let bytes = row.get::<_, Vec<u8>>(2)?;
            let digest = row.get::<_, String>(1)?;
            Ok(json!({
                "run_registration_id":row.get::<_,String>(0)?,
                "registration_digest":checked_blob(&digest,&bytes),
                "registration_byte_length":checked_length(row.get::<_,i64>(3)?,&bytes),
                "build_digest":qualified(&row.get::<_,String>(4)?),
                "source_tree_digest":qualified(&row.get::<_,String>(5)?),
                "configuration_digest":qualified(&row.get::<_,String>(6)?),
                "budget_digest":qualified(&row.get::<_,String>(7)?),
                "privacy_digest":qualified(&row.get::<_,String>(8)?),
                "daily_surface_profile_digest":qualified(&row.get::<_,String>(9)?),
                "authority":row.get::<_,String>(10)?,
                "available_commit_seq":row.get::<_,i64>(11)?,
            }))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?
        .into_iter()
        .map(checked_row)
        .collect()
}

fn spool_rows(connection: &Connection, from: i64, through: i64) -> Result<Vec<Value>> {
    simple_blob_rows(
        connection,
        "SELECT b.catalog_admission_id,b.run_registration_id,b.segment_id,b.batch_id,
                b.binding_sha256,b.binding_bytes,b.binding_byte_length,b.authority,
                b.created_commit_seq,s.store_commit_seq
         FROM wave5_spool_catalog_binding_v1 b
         JOIN spool_catalog_admission s ON s.segment_id=b.segment_id AND s.batch_id=b.batch_id
         WHERE b.created_commit_seq BETWEEN ?1 AND ?2
           AND s.store_commit_seq BETWEEN ?1 AND ?2
         ORDER BY b.catalog_admission_id",
        from,
        through,
        |row, digest, bytes| {
            Ok(json!({
                "catalog_admission_id":row.get::<_,String>(0)?,
                "run_registration_id":row.get::<_,String>(1)?,
                "segment_id":row.get::<_,String>(2)?,
                "batch_id":row.get::<_,String>(3)?,
                "store_commit_seq":row.get::<_,i64>(9)?,
                "binding_digest":checked_blob(digest,bytes),
                "binding_byte_length":checked_length(row.get::<_,i64>(6)?,bytes),
                "authority":row.get::<_,String>(7)?,
                "available_commit_seq":row.get::<_,i64>(8)?,
            }))
        },
    )
}

fn status_rows(connection: &Connection, from: i64, through: i64) -> Result<Vec<Value>> {
    let mut statement = connection.prepare(
        "SELECT record_id,run_registration_id,component,record_kind,state,cause,
                predecessor_record_id,evidence_commit_seq,observed_wall_us,detail_sha256,
                record_sha256,record_bytes,record_byte_length,authority,created_commit_seq
         FROM wave5_operational_record_v1 WHERE created_commit_seq BETWEEN ?1 AND ?2
           AND (evidence_commit_seq IS NULL OR evidence_commit_seq BETWEEN ?1 AND ?2)
         ORDER BY record_id",
    )?;
    statement.query_map(params![from,through], |row| {
        let bytes=row.get::<_,Vec<u8>>(11)?;
        let digest=row.get::<_,String>(10)?;
        Ok(json!({
            "record_id":row.get::<_,String>(0)?,"run_registration_id":row.get::<_,String>(1)?,
            "component":row.get::<_,String>(2)?,"record_kind":row.get::<_,String>(3)?,
            "state":row.get::<_,String>(4)?,"cause":row.get::<_,Option<String>>(5)?,
            "predecessor_record_id":row.get::<_,Option<String>>(6)?,
            "evidence_commit_seq":row.get::<_,Option<i64>>(7)?,"observed_at":row.get::<_,i64>(8)?,
            "detail_digest":row.get::<_,Option<String>>(9)?.map(|value|qualified(&value)),
            "record_digest":checked_blob(&digest,&bytes),
            "record_byte_length":checked_length(row.get::<_,i64>(12)?,&bytes),
            "authority":row.get::<_,String>(13)?,"available_commit_seq":row.get::<_,i64>(14)?,
        }))
    })?.collect::<std::result::Result<Vec<_>,_>>()?.into_iter().map(checked_row).collect()
}

fn export_rows(connection: &Connection, from: i64, through: i64) -> Result<Vec<Value>> {
    let mut statement = connection.prepare(
        "SELECT b.export_binding_id,b.run_registration_id,b.export_request_id,b.validation_id,
                b.snapshot_id,e.truth_fingerprint_sha256,b.binding_sha256,b.binding_bytes,
                b.binding_byte_length,b.authority,b.created_commit_seq
         FROM wave5_export_validation_binding_v1 b
         JOIN production_export_request_v2 e USING(export_request_id)
         WHERE b.created_commit_seq BETWEEN ?1 AND ?2 AND e.created_commit_seq BETWEEN ?1 AND ?2
         ORDER BY b.export_binding_id",
    )?;
    statement.query_map(params![from,through], |row| {
        let bytes=row.get::<_,Vec<u8>>(7)?; let digest=row.get::<_,String>(6)?;
        Ok(json!({"export_binding_id":row.get::<_,String>(0)?,
            "run_registration_id":row.get::<_,String>(1)?,"export_request_id":row.get::<_,String>(2)?,
            "validation_id":row.get::<_,String>(3)?,"snapshot_id":row.get::<_,String>(4)?,
            "truth_fingerprint_digest":qualified(&row.get::<_,String>(5)?),
            "binding_digest":checked_blob(&digest,&bytes),
            "binding_byte_length":checked_length(row.get::<_,i64>(8)?,&bytes),
            "authority":row.get::<_,String>(9)?,"available_commit_seq":row.get::<_,i64>(10)?}))
    })?.collect::<std::result::Result<Vec<_>,_>>()?.into_iter().map(checked_row).collect()
}

fn import_rows(connection: &Connection, from: i64, through: i64) -> Result<Vec<Value>> {
    let mut statement=connection.prepare(
        "SELECT a.import_id,a.run_registration_id,a.export_binding_id,a.export_request_id,
                a.analysis_run_id,a.artifact_id,a.artifact_contract,a.manifest_sha256,
                a.manifest_bytes,a.manifest_byte_length,a.snapshot_id,a.claim_scope,
                a.truth_fingerprint_sha256,a.maximum_input_available_wall_us,
                a.registration_sha256,a.registration_bytes,a.registration_byte_length,
                p.physical_sha256,p.byte_length,a.authority,a.created_commit_seq
         FROM wave5_restricted_artifact_v1 a JOIN wave5_restricted_artifact_part_v1 p USING(import_id)
         WHERE a.created_commit_seq BETWEEN ?1 AND ?2 AND p.part_ordinal=0 ORDER BY a.import_id")?;
    statement.query_map(params![from,through], |row| {
        let manifest_bytes=row.get::<_,Vec<u8>>(8)?;
        let manifest_digest=row.get::<_,String>(7)?;
        let bytes=row.get::<_,Vec<u8>>(15)?;let digest=row.get::<_,String>(14)?;
        Ok(json!({"import_id":row.get::<_,String>(0)?,"run_registration_id":row.get::<_,String>(1)?,
            "export_binding_id":row.get::<_,String>(2)?,"export_request_id":row.get::<_,String>(3)?,
            "analysis_run_id":row.get::<_,String>(4)?,"artifact_id":row.get::<_,String>(5)?,
            "artifact_contract":row.get::<_,String>(6)?,
            "manifest_digest":checked_blob(&manifest_digest,&manifest_bytes),
            "manifest_bytes":manifest_bytes.clone(),
            "manifest_byte_length":checked_length(row.get::<_,i64>(9)?,&manifest_bytes),
            "snapshot_id":row.get::<_,String>(10)?,"claim_scope":row.get::<_,String>(11)?,
            "truth_fingerprint_digest":qualified(&row.get::<_,String>(12)?),
            "maximum_input_available_at":row.get::<_,i64>(13)?,
            "registration_digest":checked_blob(&digest,&bytes),
            "registration_byte_length":checked_length(row.get::<_,i64>(16)?,&bytes),
            "cas_physical_digest":qualified(&row.get::<_,String>(17)?),"cas_byte_length":row.get::<_,i64>(18)?,
            "authority":row.get::<_,String>(19)?,"available_commit_seq":row.get::<_,i64>(20)?}))
    })?.collect::<std::result::Result<Vec<_>,_>>()?.into_iter().map(checked_row).collect()
}

fn stable_file_bytes(path: &Path, maximum_bytes: u64, context: &str) -> Result<Vec<u8>> {
    let metadata = fs::symlink_metadata(path).map_err(|error| ExportError::io(path, error))?;
    if metadata.file_type().is_symlink() || !metadata.file_type().is_file() {
        return Err(invalid(format!("{context} must be a real regular file")));
    }
    if metadata.len() == 0 || metadata.len() > maximum_bytes {
        return Err(invalid(format!("{context} exceeds its exact byte bounds")));
    }
    let first = fs::read(path).map_err(|error| ExportError::io(path, error))?;
    let second = fs::read(path).map_err(|error| ExportError::io(path, error))?;
    if first != second
        || u64::try_from(first.len()).ok() != Some(metadata.len())
        || fs::symlink_metadata(path)
            .map_err(|error| ExportError::io(path, error))?
            .len()
            != metadata.len()
    {
        return Err(invalid(format!(
            "{context} changed during independent readback"
        )));
    }
    Ok(first)
}

#[allow(clippy::too_many_lines)]
fn validate_import_artifact_readback(
    imports: &[Value],
    readback: &G0ImportArtifactReadbackV1,
) -> Result<()> {
    if imports.len() != 1 || readback.parts.len() != 1 {
        return Err(invalid(
            "G0 import readback requires the one exact registered V9 CAS part",
        ));
    }
    let imported = &imports[0];
    if readback.import_id.as_str() != required_text(imported, "import_id")?
        || readback.artifact_id.as_str() != required_text(imported, "artifact_id")?
    {
        return Err(invalid(
            "G0 import readback identity differs from the selected import occurrence",
        ));
    }
    let manifest_bytes = stable_file_bytes(
        &readback.manifest_path,
        4 * 1024 * 1024,
        "G0 imported artifact manifest",
    )?;
    if manifest_bytes != exact_bytes(imported, "manifest_bytes")?
        || qualified_sha256(&manifest_bytes) != required_text(imported, "manifest_digest")?
        || u64::try_from(manifest_bytes.len()).ok() != imported["manifest_byte_length"].as_u64()
    {
        return Err(invalid(
            "G0 imported manifest file differs from its registered exact bytes",
        ));
    }
    let manifest = parse_json_without_duplicate_keys(&manifest_bytes)?;
    let canonical_manifest = serde_json::to_vec(&manifest)?;
    if manifest_bytes != canonical_manifest
        && manifest_bytes != [canonical_manifest.as_slice(), b"\n"].concat()
    {
        return Err(invalid(
            "G0 imported artifact manifest is not canonical exact JSON",
        ));
    }
    if manifest["artifact_id"] != readback.artifact_id.as_str()
        || manifest["manifest_version"] != imported["artifact_contract"]
        || manifest["analysis_run_id"] != imported["analysis_run_id"]
        || manifest["input"]["snapshot_id"] != imported["snapshot_id"]
    {
        return Err(invalid(
            "G0 imported artifact manifest changes its registration",
        ));
    }
    let artifacts = manifest["artifacts"]
        .as_array()
        .ok_or_else(|| invalid("G0 imported manifest artifacts are absent"))?;
    if artifacts.len() != readback.parts.len() {
        return Err(invalid(
            "G0 imported manifest does not name every exact CAS part",
        ));
    }
    for (wire, part) in artifacts.iter().zip(&readback.parts) {
        let relative = Path::new(part.relative_path.as_str());
        if relative.is_absolute()
            || relative.components().count() != 1
            || relative.file_name().and_then(|name| name.to_str())
                != Some(part.relative_path.as_str())
        {
            return Err(invalid(
                "G0 imported artifact part path is not a safe child name",
            ));
        }
        let primary_key = wire["primary_key"]
            .as_array()
            .ok_or_else(|| invalid("G0 imported artifact primary key is absent"))?;
        let expected_primary_key = part
            .primary_key
            .iter()
            .map(StableString::as_str)
            .collect::<Vec<_>>();
        if wire["path"] != part.relative_path.as_str()
            || wire["schema_id"] != part.schema_id.as_str()
            || wire["schema_digest"] != part.schema_digest.as_str()
            || wire["physical_digest"] != part.physical_digest.as_str()
            || wire["logical_digest"] != part.logical_digest.as_str()
            || wire["byte_length"]
                .as_str()
                .and_then(|value| value.parse().ok())
                != Some(part.byte_length)
            || wire["row_count"]
                .as_str()
                .and_then(|value| value.parse().ok())
                != Some(part.row_count)
            || primary_key
                .iter()
                .map(Value::as_str)
                .collect::<Option<Vec<_>>>()
                .as_deref()
                != Some(expected_primary_key.as_slice())
        {
            return Err(invalid(
                "G0 imported artifact part descriptor differs from its manifest",
            ));
        }
        let physical_bytes =
            stable_file_bytes(&part.path, 256 * 1024 * 1024, "G0 imported Parquet part")?;
        if u64::try_from(physical_bytes.len()).ok() != Some(part.byte_length)
            || qualified_sha256(&physical_bytes) != part.physical_digest.as_str()
            || qualified_sha256_file(&part.path)? != part.physical_digest.as_str()
        {
            return Err(invalid(
                "G0 imported CAS part differs from its exact physical registration",
            ));
        }
        let batches = read_parquet(&part.path)?;
        let schema = batches
            .first()
            .map(RecordBatch::schema)
            .ok_or_else(|| invalid("G0 imported Parquet part has no schema"))?;
        let descriptor = schema_descriptor(&schema)?;
        let rows = batches.iter().try_fold(0_u64, |sum, batch| {
            sum.checked_add(
                u64::try_from(batch.num_rows())
                    .map_err(|_| invalid("G0 imported part row count exceeds u64"))?,
            )
            .ok_or_else(|| invalid("G0 imported part row count exceeds u64"))
        })?;
        if wire["schema"] != descriptor
            || qualified_sha256(&serde_json::to_vec(&descriptor)?) != part.schema_digest.as_str()
            || logical_table_digest(&batches, &expected_primary_key)?
                != part.logical_digest.as_str()
            || rows != part.row_count
        {
            return Err(invalid(
                "G0 imported CAS part fails schema/logical/row readback",
            ));
        }
    }
    let part = &readback.parts[0];
    if part.physical_digest.as_str() != required_text(imported, "cas_physical_digest")?
        || Some(part.byte_length) != imported["cas_byte_length"].as_u64()
    {
        return Err(invalid(
            "G0 imported CAS part differs from the selected import occurrence",
        ));
    }
    Ok(())
}

fn simple_blob_rows<F>(
    connection: &Connection,
    sql: &str,
    from: i64,
    through: i64,
    map: F,
) -> Result<Vec<Value>>
where
    F: Fn(&rusqlite::Row<'_>, &str, &[u8]) -> rusqlite::Result<Value>,
{
    let mut statement = connection.prepare(sql)?;
    statement
        .query_map(params![from, through], |row| {
            let digest = row.get::<_, String>(4)?;
            let bytes = row.get::<_, Vec<u8>>(5)?;
            map(row, &digest, &bytes)
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?
        .into_iter()
        .map(checked_row)
        .collect()
}

fn checked_blob(expected: &str, bytes: &[u8]) -> Value {
    let actual = format!("{:x}", Sha256::digest(bytes));
    if expected == actual {
        Value::String(qualified(expected))
    } else {
        Value::Null
    }
}

fn checked_length(expected: i64, bytes: &[u8]) -> Value {
    if usize::try_from(expected).ok() == Some(bytes.len()) {
        json!(expected)
    } else {
        Value::Null
    }
}

fn checked_row(value: Value) -> Result<Value> {
    if !value.is_object() {
        return Err(invalid("G0 SQL adapter did not produce an object row"));
    }
    Ok(value)
}

fn batch(spec: &TableSpec, rows: &[Value]) -> Result<RecordBatch> {
    let schema = Arc::new(spec.schema());
    let mut arrays = Vec::<ArrayRef>::with_capacity(schema.fields().len());
    for field in schema.fields() {
        let values = rows
            .iter()
            .map(|row| &row[field.name()])
            .collect::<Vec<_>>();
        let array: ArrayRef = match field.data_type() {
            DataType::Utf8 => {
                let strings = values
                    .iter()
                    .map(|value| value.as_str())
                    .collect::<Vec<_>>();
                if !field.is_nullable() && strings.iter().any(Option::is_none) {
                    return Err(invalid(format!(
                        "{} has a null {}",
                        spec.name,
                        field.name()
                    )));
                }
                Arc::new(StringArray::from(strings))
            }
            DataType::Binary => {
                let bytes = values
                    .iter()
                    .map(|value| {
                        if value.is_null() {
                            Ok(None)
                        } else {
                            exact_bytes(&json!({"value": value}), "value").map(Some)
                        }
                    })
                    .collect::<Result<Vec<_>>>()?;
                if !field.is_nullable() && bytes.iter().any(Option::is_none) {
                    return Err(invalid(format!(
                        "{} has a null {}",
                        spec.name,
                        field.name()
                    )));
                }
                Arc::new(
                    bytes
                        .iter()
                        .map(|value| value.as_deref())
                        .collect::<BinaryArray>(),
                )
            }
            DataType::Int64 => {
                let integers = values
                    .iter()
                    .map(|value| value.as_i64())
                    .collect::<Vec<_>>();
                if !field.is_nullable() && integers.iter().any(Option::is_none) {
                    return Err(invalid(format!(
                        "{} has a null {}",
                        spec.name,
                        field.name()
                    )));
                }
                Arc::new(Int64Array::from(integers))
            }
            DataType::Timestamp(TimeUnit::Microsecond, timezone)
                if timezone.as_deref() == Some("UTC") =>
            {
                let instants = values
                    .iter()
                    .map(|value| value.as_i64())
                    .collect::<Vec<_>>();
                if !field.is_nullable() && instants.iter().any(Option::is_none) {
                    return Err(invalid(format!(
                        "{} has a null {}",
                        spec.name,
                        field.name()
                    )));
                }
                Arc::new(TimestampMicrosecondArray::from(instants).with_timezone("UTC"))
            }
            other => return Err(invalid(format!("unsupported G0 Arrow type {other}"))),
        };
        arrays.push(array);
    }
    RecordBatch::try_new(schema, arrays).map_err(ExportError::Arrow)
}

fn qualified(raw: &str) -> String {
    format!("sha256:{raw}")
}
fn sql_commit(value: CommitSeq) -> Result<i64> {
    i64::try_from(value.get()).map_err(|_| invalid("commit exceeds SQLite i64"))
}
fn invalid(message: impl Into<String>) -> ExportError {
    ExportError::Invalid(message.into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use joshi_domain::WireU64;
    use joshi_publication::{
        COCKPIT_V2_RESOLVED_SOURCE_FACTS_INPUT_CONTRACT, COCKPIT_V2_SCHEMA_VERSION,
        CockpitPublicationId, CockpitV2Ceiling, CockpitV2CoverageState, CockpitV2CutoffV1,
        CockpitV2ObservedUniverseRefV1, CockpitV2ResolvedSourceFactsInputV1,
        CockpitV2SurfaceFieldRefV1, finalize_cockpit_v2,
        prepare_cockpit_v2_from_resolved_source_facts,
    };
    use joshi_scientific_memory::{
        ActId, ActKind, CatalogCommitSeq, Digest as MemoryDigest, Episode, EpisodeCompleteness,
        EpisodeId, LogicalSessionTick, OperatorAct, PresentationBinding, PresentationGap,
        PresentationGapReason, SceneId, SceneRef, SessionId,
    };
    use std::str::FromStr;

    fn connected_rows() -> BTreeMap<&'static str, Vec<Value>> {
        BTreeMap::from([
            (
                "source_fact_occurrences",
                vec![json!({
                    "source_occurrence_id":"source-1","run_registration_id":"run-1",
                    "catalog_admission_id":"catalog-1","known_through_commit_seq":2,
                    "protection_class":"public_integrity","authority":"read_only_no_execution"
                })],
            ),
            (
                "publication_occurrences",
                vec![json!({
                    "publication_id":"publication-1","source_occurrence_id":"source-1",
                    "publication_digest":"sha256:publication","head_digest":"sha256:head",
                    "through_commit_seq":2,"supersedes_publication_id":null,
                    "supersedes_head_publication_id":null,"authority":"read_only_no_execution"
                })],
            ),
            (
                "scene_occurrences",
                vec![json!({
                    "scene_publication_id":"publication-1","source_occurrence_id":"source-1",
                    "publication_digest":"sha256:publication","head_digest":"sha256:head",
                    "authority":"read_only_no_execution"
                })],
            ),
            (
                "act_occurrences",
                vec![json!({
                    "act_id":"act-1","session_id":"session-1",
                    "scene_publication_id":"publication-1",
                    "qualification":"fixture_authority_unverified_semantic",
                    "authority":"read_only_no_execution"
                })],
            ),
            (
                "episode_occurrences",
                vec![json!({
                    "episode_id":"episode-1","session_id":"session-1",
                    "scene_publication_id":"publication-1","opening_act_id":"act-1",
                    "closing_act_id":null,
                    "qualification":"fixture_authority_unverified_semantic",
                    "authority":"read_only_no_execution"
                })],
            ),
            (
                "run_occurrences",
                vec![json!({"run_registration_id":"run-1","authority":"read_only_no_execution"})],
            ),
            (
                "spool_catalog_occurrences",
                vec![json!({
                    "catalog_admission_id":"catalog-1","run_registration_id":"run-1",
                    "store_commit_seq":2,"authority":"read_only_no_execution"
                })],
            ),
            (
                "status_occurrences",
                vec![json!({
                    "record_id":"status-1","run_registration_id":"run-1",
                    "component":"export","state":"ready","predecessor_record_id":null,
                    "evidence_commit_seq":9,"authority":"read_only_no_execution"
                })],
            ),
            (
                "export_occurrences",
                vec![json!({
                    "export_binding_id":"binding-1","run_registration_id":"run-1",
                    "export_request_id":"request-1","snapshot_id":"snapshot-1",
                    "truth_fingerprint_digest":"sha256:truth","available_commit_seq":9,
                    "authority":"read_only_no_execution"
                })],
            ),
            (
                "import_occurrences",
                vec![json!({
                    "import_id":"import-1","run_registration_id":"run-1",
                    "export_binding_id":"binding-1","export_request_id":"request-1",
                    "snapshot_id":"snapshot-1","truth_fingerprint_digest":"sha256:truth",
                    "claim_scope":"descriptive_noncausal","authority":"read_only_no_execution"
                })],
            ),
        ])
    }

    fn stable(value: &str) -> StableString {
        StableString::new(value).expect("stable string")
    }

    fn digest(fill: char) -> ValueDigest {
        ValueDigest::new(format!("sha256:{}", fill.to_string().repeat(64))).expect("digest")
    }

    fn wire_digest(value: &str) -> ValueDigest {
        ValueDigest::new(value).expect("wire digest")
    }

    fn instant(value: &str) -> UtcTimestamp {
        UtcTimestamp::from_str(value).expect("timestamp")
    }

    #[allow(clippy::too_many_lines)]
    fn semantic_rows() -> BTreeMap<&'static str, Vec<Value>> {
        let maximum = instant("2026-08-18T12:00:00.000000Z");
        let profile = CockpitV2SurfaceProfileRefV1 {
            profile_id: stable("profile-1"),
            profile_digest: digest('1'),
            field_cells: vec![CockpitV2SurfaceFieldRefV1 {
                surface_id: stable("surface-1"),
                source_id: stable("source-store-1"),
                field: stable("mint"),
            }],
        };
        let facts = vec![CockpitV2SourceFactRefV1 {
            fact_id: stable("fact-1"),
            fact_digest: digest('2'),
            surface_id: stable("surface-1"),
            source_id: stable("source-store-1"),
            subject: stable("mint-1"),
            field: stable("mint"),
            protection: ProtectionDomain::Public,
            observed_at: instant("2026-08-18T11:00:00.000000Z"),
            known_at: instant("2026-08-18T11:30:00.000000Z"),
            commit_seq: Some(CommitSeq::new(2)),
        }];
        let memberships = vec![
            CockpitV2MembershipRefV1 {
                subject: stable("mint-1"),
                membership: CockpitV2MembershipKind::Hot,
                observed_at: instant("2026-08-18T11:00:00.000000Z"),
                evidence_digest: digest('3'),
            },
            CockpitV2MembershipRefV1 {
                subject: stable("mint-2"),
                membership: CockpitV2MembershipKind::ColdControl,
                observed_at: instant("2026-08-18T11:00:00.000000Z"),
                evidence_digest: digest('4'),
            },
        ];
        let coverage = vec![
            CockpitV2CoverageRefV1 {
                surface_id: stable("surface-1"),
                source_id: stable("source-store-1"),
                subject: stable("mint-1"),
                field: stable("mint"),
                fact_ids: vec![stable("fact-1")],
                state: CockpitV2CoverageState::Complete,
                coverage_digest: digest('5'),
            },
            CockpitV2CoverageRefV1 {
                surface_id: stable("surface-1"),
                source_id: stable("source-store-1"),
                subject: stable("mint-2"),
                field: stable("mint"),
                fact_ids: vec![],
                state: CockpitV2CoverageState::Unavailable,
                coverage_digest: digest('6'),
            },
        ];
        let gaps = vec![CockpitV2GapRefV1 {
            gap_id: stable("gap-1"),
            surface_id: stable("surface-1"),
            source_id: stable("source-store-1"),
            subject: stable("mint-2"),
            field: stable("mint"),
            reason: stable("unavailable"),
            since: instant("2026-08-18T10:00:00.000000Z"),
            until: None,
            evidence_digest: Some(digest('7')),
        }];
        let omissions = vec![CockpitV2OmissionV1 {
            subject: stable("mint-2"),
            reason: stable("denominator_only"),
            membership: CockpitV2MembershipKind::DenominatorOnly,
        }];
        let mut universe = CockpitV2ObservedUniverseRefV1 {
            universe_id: stable("universe-1"),
            universe_digest: digest('0'),
            eligible_count: WireU64::new(2),
            eligible_subjects: vec![stable("mint-1"), stable("mint-2")],
        };
        universe.universe_digest = universe.computed_digest().expect("universe digest");
        let input = CockpitV2ResolvedSourceFactsInputV1 {
            contract: stable(COCKPIT_V2_RESOLVED_SOURCE_FACTS_INPUT_CONTRACT),
            schema_version: COCKPIT_V2_SCHEMA_VERSION,
            surface_profile: profile.clone(),
            observed_universe: universe,
            cutoff: CockpitV2CutoffV1 {
                knowledge_at: maximum,
                commit_through: Some(CommitSeq::new(2)),
                chain_slot: None,
            },
            source_facts: facts.clone(),
            memberships: memberships.clone(),
            coverage: coverage.clone(),
            gaps: gaps.clone(),
            rendered_subjects: vec![stable("mint-1")],
            omissions: omissions.clone(),
            ordering_policy: stable("store_resolved_membership_then_subject"),
            pagination_policy: stable("store_resolved_complete_partition"),
            authority: ProjectionAuthority::ReadOnlyNoExecution,
            ceiling: CockpitV2Ceiling::UnverifiedSemantic,
        };
        let prepared = prepare_cockpit_v2_from_resolved_source_facts(input)
            .expect("valid prepared publication");
        let publication = finalize_cockpit_v2(
            &prepared,
            CockpitPublicationId::new("publication-1").expect("publication ID"),
            CommitSeq::new(3),
            None,
            None,
        )
        .expect("publication");
        let head = joshi_publication::CockpitV2HeadV1::from_publication(&publication)
            .expect("publication head");
        let publication_bytes = publication.canonical_bytes().expect("publication bytes");
        let head_bytes = head.canonical_bytes().expect("head bytes");
        let source_wire = SourceOccurrenceWire {
            contract: stable("joshi.store.wave5.source_occurrence.v1"),
            schema_version: 1,
            source_occurrence_id: stable("source-1"),
            run_registration_id: stable("run-1"),
            catalog_admission_id: stable("catalog-1"),
            source_receipt_digest: digest('8'),
            source_id: stable("source-store-1"),
            surface_profile: profile,
            facts,
            eligible_subjects: vec![stable("mint-1"), stable("mint-2")],
            memberships,
            coverage,
            gaps,
            rendered_subjects: vec![stable("mint-1")],
            omissions,
            known_through_commit_seq: CommitSeq::new(2),
            maximum_input_available_at: maximum,
            protection: ProtectionDomain::Public,
            authority: ProjectionAuthority::ReadOnlyNoExecution,
        };
        let source_bytes = serde_json::to_vec(&source_wire).expect("source bytes");

        let tick = LogicalSessionTick::new(9_007_199_254_740_993).expect("wide tick");
        let scene = SceneRef {
            scene_id: SceneId::new("publication-1").expect("scene ID"),
            scene_digest: MemoryDigest::new(publication.publication_digest.to_string())
                .expect("scene digest"),
            catalog_cutoff: CatalogCommitSeq::new(3).expect("scene cutoff"),
        };
        let act = MemoryOccurrence::OperatorAct(OperatorAct {
            act_id: ActId::new("act-1").expect("act ID"),
            session_id: SessionId::new("session-1").expect("session ID"),
            occurred_at: tick,
            scene: SceneBinding::Committed(scene.clone()),
            presentation: PresentationBinding::Gap(PresentationGap {
                gap_id: "presentation-gap-1".into(),
                scene: Some(scene),
                reason: PresentationGapReason::Unavailable,
                detected_at: tick,
            }),
            kind: ActKind::Notice,
            subject: Some("mint-1".into()),
            assertion: None,
        });
        let episode = MemoryOccurrence::Episode(Episode {
            episode_id: EpisodeId::new("episode-1").expect("episode ID"),
            session_id: SessionId::new("session-1").expect("session ID"),
            act_ids: vec![ActId::new("act-1").expect("act ID")],
            decision_cutoff: LogicalSessionTick::new(9_007_199_254_740_994).expect("wide tick"),
            started_at: tick,
            ended_at: Some(LogicalSessionTick::new(9_007_199_254_740_994).expect("wide end tick")),
            completeness: EpisodeCompleteness::Partial,
            segments: vec![],
        });
        let act_bytes = serde_json::to_vec(&act).expect("act bytes");
        let episode_bytes = serde_json::to_vec(&episode).expect("episode bytes");

        let mut rows = connected_rows();
        rows.insert(
            "source_fact_occurrences",
            vec![json!({
                "source_occurrence_id":"source-1","run_registration_id":"run-1",
                "catalog_admission_id":"catalog-1","source_id":"source-store-1",
                "receipt_digest":digest('8'),
                "descriptor_contract":"joshi.store.wave5.source_occurrence.v1",
                "descriptor_digest":qualified_sha256(&source_bytes),
                "descriptor_bytes":source_bytes,"descriptor_byte_length":source_bytes.len(),
                "surface_profile_digest":digest('1'),"fact_count":1,
                "eligible_subject_count":2,"membership_count":2,"coverage_count":2,
                "gap_count":1,"rendered_subject_count":1,"omission_count":1,
                "hot_subject_count":1,"cold_control_subject_count":1,
                "known_through_commit_seq":2,"maximum_input_available_at":maximum
                    .as_datetime().unix_timestamp_nanos()/1_000,
                "protection_class":"public_integrity","authority":"read_only_no_execution",
                "available_commit_seq":2
            })],
        );
        rows.insert(
            "publication_occurrences",
            vec![json!({
                "publication_id":"publication-1","preparation_id":"preparation-1",
                "source_occurrence_id":"source-1","publication_contract":publication.contract,
                "publication_digest":publication.publication_digest,
                "publication_bytes_digest":qualified_sha256(&publication_bytes),
                "publication_bytes":publication_bytes,"publication_byte_length":publication_bytes.len(),
                "semantic_digest":publication.manifest.semantic_digest,
                "container_digest":publication.manifest.container_digest,
                "checkpoint_digest":publication.checkpoint.checkpoint_digest,
                "through_commit_seq":2,"supersedes_publication_id":null,
                "head_digest":head.head_digest,"head_bytes":head_bytes,
                "head_byte_length":head_bytes.len(),"supersedes_head_publication_id":null,
                "authority":"read_only_no_execution","publication_commit_seq":3,
                "available_commit_seq":4
            })],
        );
        rows.insert(
            "scene_occurrences",
            scene_rows(&rows["publication_occurrences"]),
        );
        rows.insert(
            "act_occurrences",
            vec![json!({
                "act_id":"act:act-1","session_id":"session-1",
                "scene_publication_id":"publication-1",
                "occurrence_digest":qualified_sha256(&act_bytes),"occurrence_bytes":act_bytes,
                "occurrence_byte_length":act_bytes.len(),"logical_start_tick":tick.value().to_string(),
                "logical_end_tick":null,"queue_generation":1,
                "qualification":"fixture_authority_unverified_semantic",
                "authority":"read_only_no_execution","available_commit_seq":5
            })],
        );
        rows.insert(
            "episode_occurrences",
            vec![json!({
                "episode_id":"episode:episode-1","session_id":"session-1",
                "scene_publication_id":"publication-1","opening_act_id":"act:act-1",
                "closing_act_id":"act:act-1","occurrence_digest":qualified_sha256(&episode_bytes),
                "occurrence_bytes":episode_bytes,"occurrence_byte_length":episode_bytes.len(),
                "logical_start_tick":tick.value().to_string(),
                "logical_end_tick":"9007199254740994","queue_generation":2,
                "qualification":"fixture_authority_unverified_semantic",
                "authority":"read_only_no_execution","available_commit_seq":6
            })],
        );
        rows
    }

    #[test]
    fn exact_connected_g0_component_is_accepted() {
        validate_relational_closure(&connected_rows()).expect("connected component");
    }

    #[test]
    fn exact_semantic_bytes_survive_binary_batches_and_revalidate() {
        let rows = semantic_rows();
        validate_connected_closure(&rows).expect("semantic closure");
        for name in [
            "source_fact_occurrences",
            "publication_occurrences",
            "scene_occurrences",
            "act_occurrences",
            "episode_occurrences",
        ] {
            let spec = G0_TABLE_SPECS
                .iter()
                .find(|spec| spec.name == name)
                .expect("G0 table spec");
            let encoded = batch(spec, &rows[name]).expect("binary relation batch");
            let reopened = crate::snapshot::relation_rows(&[encoded]).expect("reopened rows");
            match name {
                "source_fact_occurrences" => {
                    validate_source_bytes(&reopened[0]).expect("reopened source");
                }
                "publication_occurrences" => {
                    validate_publication_bytes(&reopened[0]).expect("reopened publication");
                }
                "act_occurrences" => {
                    validate_memory_bytes(&reopened[0], "operator_act").expect("reopened act");
                }
                "episode_occurrences" => {
                    validate_memory_bytes(&reopened[0], "episode").expect("reopened episode");
                }
                _ => {}
            }
        }
    }

    #[test]
    fn malformed_source_and_memory_bytes_and_semantic_head_substitution_are_refused() {
        let mut rows = semantic_rows();
        rows.get_mut("source_fact_occurrences").expect("source")[0]["descriptor_bytes"] =
            json!(b"{}".to_vec());
        assert!(validate_connected_closure(&rows).is_err());

        let mut rows = semantic_rows();
        let mut act: Value = serde_json::from_slice(
            &exact_bytes(&rows["act_occurrences"][0], "occurrence_bytes").expect("act bytes"),
        )
        .expect("act JSON");
        act["value"]["occurredAt"] = json!("18446744073709551616");
        rows.get_mut("act_occurrences").expect("acts")[0]["occurrence_bytes"] =
            json!(serde_json::to_vec(&act).expect("forged act"));
        assert!(validate_connected_closure(&rows).is_err());

        let mut rows = semantic_rows();
        rows.get_mut("publication_occurrences")
            .expect("publications")[0]["head_digest"] = json!(digest('f'));
        rows.insert(
            "scene_occurrences",
            scene_rows(&rows["publication_occurrences"]),
        );
        assert!(validate_connected_closure(&rows).is_err());
    }

    #[test]
    fn import_readback_reopens_every_exact_cas_byte_and_refuses_delete_or_tamper() {
        let workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .expect("workspace");
        let fixture = workspace.join(
            "fixtures/artifact/derived-759c5d7d2be1f318fcbc213db9759a3a4653d139ea29b6f55d47403e5d030e55",
        );
        let temporary = tempfile::tempdir().expect("temporary CAS");
        let manifest_path = temporary.path().join("manifest.json");
        let part_path = temporary.path().join("descriptive_chart_shapes.parquet");
        fs::copy(fixture.join("manifest.json"), &manifest_path).expect("copy manifest");
        fs::copy(fixture.join("descriptive_chart_shapes.parquet"), &part_path).expect("copy part");
        let manifest_bytes = fs::read(&manifest_path).expect("manifest bytes");
        let manifest: Value = serde_json::from_slice(&manifest_bytes).expect("manifest JSON");
        let wire = &manifest["artifacts"][0];
        let artifact_id =
            wire_digest(required_text(&manifest, "artifact_id").expect("artifact ID"));
        let physical =
            wire_digest(required_text(wire, "physical_digest").expect("physical digest"));
        let readback = G0ImportArtifactReadbackV1 {
            import_id: stable("import-1"),
            artifact_id: artifact_id.clone(),
            manifest_path: manifest_path.clone(),
            parts: vec![crate::production::G0ImportPartReadbackV1 {
                path: part_path.clone(),
                relative_path: stable(required_text(wire, "path").expect("part path")),
                schema_id: stable(required_text(wire, "schema_id").expect("schema ID")),
                schema_digest: wire_digest(
                    required_text(wire, "schema_digest").expect("schema digest"),
                ),
                physical_digest: physical.clone(),
                logical_digest: wire_digest(
                    required_text(wire, "logical_digest").expect("logical digest"),
                ),
                primary_key: wire["primary_key"]
                    .as_array()
                    .expect("primary key")
                    .iter()
                    .map(|value| stable(value.as_str().expect("key")))
                    .collect(),
                byte_length: wire["byte_length"]
                    .as_str()
                    .expect("byte length")
                    .parse()
                    .expect("u64 byte length"),
                row_count: wire["row_count"]
                    .as_str()
                    .expect("row count")
                    .parse()
                    .expect("u64 row count"),
            }],
        };
        let imported = vec![json!({
            "import_id":"import-1","artifact_id":artifact_id,
            "artifact_contract":manifest["manifest_version"],
            "analysis_run_id":manifest["analysis_run_id"],
            "snapshot_id":manifest["input"]["snapshot_id"],
            "manifest_digest":qualified_sha256(&manifest_bytes),
            "manifest_bytes":manifest_bytes,"manifest_byte_length":manifest_bytes.len(),
            "cas_physical_digest":physical,"cas_byte_length":fs::metadata(&part_path)
                .expect("part metadata").len()
        })];
        validate_import_artifact_readback(&imported, &readback).expect("exact CAS readback");

        let original = fs::read(&part_path).expect("part bytes");
        fs::write(&part_path, b"tampered").expect("tamper part");
        assert!(validate_import_artifact_readback(&imported, &readback).is_err());
        fs::write(&part_path, original).expect("restore part");
        fs::remove_file(&part_path).expect("delete part");
        assert!(validate_import_artifact_readback(&imported, &readback).is_err());
    }

    #[test]
    fn source_spool_and_publication_cutoffs_must_be_the_same_support() {
        let mut rows = connected_rows();
        rows.get_mut("spool_catalog_occurrences").expect("spool")[0]["store_commit_seq"] = json!(1);
        assert!(validate_relational_closure(&rows).is_err());

        let mut rows = connected_rows();
        rows.get_mut("publication_occurrences")
            .expect("publication")[0]["through_commit_seq"] = json!(1);
        assert!(validate_relational_closure(&rows).is_err());
    }

    #[test]
    fn lower_bound_is_applied_to_source_publication_and_spool_semantic_support() {
        let workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .expect("workspace");
        let connection = Connection::open_with_flags(
            workspace.join("fixtures/export/operational_catalog_v10.sqlite"),
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .expect("V10 catalog");
        assert!(
            source_rows(&connection, 9, 25)
                .expect("source query")
                .is_empty()
        );
        assert!(
            publication_rows(&connection, 9, 25)
                .expect("publication query")
                .is_empty()
        );
        assert!(
            spool_rows(&connection, 9, 25)
                .expect("spool query")
                .is_empty()
        );
    }

    #[test]
    fn status_predecessor_and_publication_supersession_cannot_escape_the_slice() {
        let mut rows = connected_rows();
        rows.get_mut("status_occurrences").expect("status")[0]["predecessor_record_id"] =
            json!("status-before-from");
        assert!(validate_relational_closure(&rows).is_err());

        let mut rows = connected_rows();
        rows.get_mut("publication_occurrences")
            .expect("publication")[0]["supersedes_publication_id"] =
            json!("publication-before-from");
        assert!(validate_relational_closure(&rows).is_err());
    }

    #[test]
    fn unrelated_status_or_mixed_run_cannot_launder_nonempty_relations() {
        let mut rows = connected_rows();
        rows.get_mut("status_occurrences").expect("status")[0]["component"] = json!("host");
        assert!(validate_relational_closure(&rows).is_err());

        let mut rows = connected_rows();
        rows.get_mut("status_occurrences").expect("status")[0]["run_registration_id"] =
            json!("run-foreign");
        assert!(validate_relational_closure(&rows).is_err());
    }
}
