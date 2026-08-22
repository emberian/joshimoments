//! One journal entry over a real, store-derived surface, read back through the route after a
//! restart.
//!
//! The exocortex journal (`docs/planning/EXOCORTEX.md`) stores an operator's words as ordinary
//! evidence commands. This walk is its restart proof: mount a copy of a real catalog, pair, ask
//! the read route what it knows before any act (an explicit empty answer, not a blank), commit a
//! hold and a journal entry with real words through the ordinary write route, read both back,
//! then drop the router, the launcher, and the writer, reopen the catalog read-only in a fresh
//! service, and require the read route to return byte-identical commands with the exact words.
//!
//! What this walk does not claim: that a human saw pixels, or that the words are true. It proves
//! that words said over an exact scene come back verbatim, bound to the same scene digest, after
//! the process that recorded them has died.

use crate::{
    live_gesture::{
        LiveGestureError, authorized, exchange, first_candidate, hex_digest, mount_live_surface,
        now, overlay_catalog_config, response_bytes, send,
    },
    pairing::OrdinaryPairingError,
    service::{CoreService, PairingCapability, PairingCapabilityGenerationError},
};
use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use joshi_domain::UtcTimestamp;
use joshi_pairing::{PairingConfig, PairingOrigin, PairingScope};
use joshi_store::{SqliteStore, StoreMode};
use serde::{Deserialize, Serialize};
use std::path::Path;
use thiserror::Error;
use zeroize::Zeroizing;

/// The frozen label that makes a `record_focus` act a journal entry.
///
/// Mirrors `JOURNAL_UI_LABEL` in `apps/glass/src/operator/journal.ts`. The label is the whole
/// discriminator; change it on one side only and every entry already in a catalog is orphaned.
pub const JOURNAL_UI_LABEL: &str = "Journal entry";

/// Exact, secret-free result of one journal entry surviving a restart and its route readback.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct LiveJournalReport {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub catalog_schema: String,
    pub scene_id: String,
    pub view_digest: String,
    pub pairing_session_id: String,
    /// What the read route said before any act existed: an explicit retention state and an
    /// explicit empty list, never a blank or a fabricated row.
    pub empty_readback_retention: String,
    pub subject_mint: String,
    pub hold_command_id: String,
    pub hold_commit_seq: String,
    pub journal_command_id: String,
    /// The exact words the entry carried, echoed here so the report is self-describing.
    pub journal_words: String,
    pub journal_commit_seq: String,
    pub readback_bytes_digest: String,
    pub reopened_readback_bytes_digest: String,
    pub readback_identical_across_restart: bool,
    pub journal_words_read_back: bool,
    pub browser_presented: bool,
    pub product_qualified: bool,
    pub ceiling: &'static str,
}

/// Mount a real catalog, journal one real utterance through the paired route, restart, and read
/// it back through the same route.
///
/// # Errors
///
/// Refuses any route status, digest, ordering, byte-identity, or verbatim-words mismatch.
#[allow(clippy::too_many_lines)] // The ordered walk is clearer in one visible closure.
pub async fn run_live_journal_walk(
    catalog: &Path,
    state: &Path,
    source_id: &str,
    origin: &str,
    journal_words: &str,
) -> Result<LiveJournalReport, LiveJournalError> {
    if journal_words.trim().is_empty() || journal_words.trim() != journal_words {
        return Err(LiveJournalError::Invariant(
            "a journal entry with no words is refused, not recorded as a blank",
        ));
    }
    let mounted = mount_live_surface(catalog, state, source_id)?;
    let catalog_schema = mounted.catalog_schema.clone();
    let scene_id = mounted.view.scene_id().to_string();
    let view_digest = mounted.view.digest().to_string();
    let subject_mint = first_candidate(&mounted.view)?;

    let (core, launcher) = CoreService::with_sqlite_pairing_mounting(
        mounted.store,
        None,
        PairingCapability::generate_os_random()?,
        PairingOrigin::new(origin.to_owned())?,
        PairingConfig::default(),
        Some(mounted.view),
    )?;
    let issued = launcher.issue_code(vec![
        PairingScope::CockpitRead,
        PairingScope::OperatorEvidenceWrite,
    ])?;
    let app = core.router();
    let session = exchange(&app, origin, issued.code.as_str()).await?;
    let capability = Zeroizing::new(session.capability);
    let readback_route = format!("/api/v1/operator/commands?sceneId={scene_id}");

    // Clause 1: before any act, the route answers with an explicit "served, not yet durable"
    // retention and an explicit empty list. This is the shape the cockpit renders as a stated
    // absence rather than as evidence that nothing was ever said.
    let empty = send(
        &app,
        authorized(
            origin,
            "GET",
            &readback_route,
            capability.as_str(),
            Body::empty(),
        )?,
    )
    .await;
    if empty.status() != StatusCode::OK {
        return Err(LiveJournalError::Invariant(
            "readback route refused the served scene before any act",
        ));
    }
    let empty_body: ReadbackBody = serde_json::from_slice(&response_bytes(empty).await?)?;
    if empty_body.scene_retention != "served_not_yet_durable" || !empty_body.commands.is_empty() {
        return Err(LiveJournalError::Invariant(
            "pre-act readback did not state an explicit empty served-scene answer",
        ));
    }

    // Clause 2: one hold and one journal entry, in one client session, through the ordinary
    // write route.
    let issued_at = now()?;
    let walk_id = hex_digest(scene_id.as_bytes())
        .chars()
        .take(16)
        .collect::<String>();
    let client_session = format!("session-journal-{walk_id}");
    let hold_command_id = format!("command-journal-hold-{walk_id}");
    let journal_command_id = format!("command-journal-entry-{walk_id}");
    let hold_receipt = append(
        &app,
        origin,
        capability.as_str(),
        record_focus_bytes(&RecordFocus {
            command_id: &hold_command_id,
            client_session: &client_session,
            client_command_seq: 1,
            scene_id: &scene_id,
            view_digest: &view_digest,
            subject_kind: "candidate",
            subject_key: &subject_mint,
            ui_label: "Hold coin",
            note: None,
            issued_at,
        }),
    )
    .await?;
    let journal_receipt = append(
        &app,
        origin,
        capability.as_str(),
        record_focus_bytes(&RecordFocus {
            command_id: &journal_command_id,
            client_session: &client_session,
            client_command_seq: 2,
            scene_id: &scene_id,
            view_digest: &view_digest,
            subject_kind: "scene",
            subject_key: &scene_id,
            ui_label: JOURNAL_UI_LABEL,
            note: Some(journal_words),
            issued_at,
        }),
    )
    .await?;

    // Clause 3: the same route now reads both acts back in commit order, with the exact words.
    let readback = send(
        &app,
        authorized(
            origin,
            "GET",
            &readback_route,
            capability.as_str(),
            Body::empty(),
        )?,
    )
    .await;
    if readback.status() != StatusCode::OK {
        return Err(LiveJournalError::Invariant(
            "readback route refused the scene after the acts committed",
        ));
    }
    let readback_bytes = response_bytes(readback).await?;
    verify_readback(
        &readback_bytes,
        &view_digest,
        &[
            (hold_command_id.as_str(), &hold_receipt.commit_seq, None),
            (
                journal_command_id.as_str(),
                &journal_receipt.commit_seq,
                Some(journal_words),
            ),
        ],
    )?;

    // Clause 4: everything above dies here -- the router, the pairing launcher, the writer
    // lease, and the mounted in-memory view.
    drop(app);
    drop(launcher);

    let reopened = SqliteStore::open(overlay_catalog_config(state)?, StoreMode::ReadOnly)?;
    let restarted =
        CoreService::new(reopened, None, PairingCapability::generate_os_random()?).router();
    let request = Request::builder()
        .method("GET")
        .uri(&readback_route)
        .header("host", "127.0.0.1")
        .body(Body::empty())
        .map_err(|_| LiveJournalError::Invariant("restart readback request construction failed"))?;
    let reopened_readback = send(&restarted, request).await;
    if reopened_readback.status() != StatusCode::OK {
        return Err(LiveJournalError::Invariant(
            "restarted core refused the journal readback route",
        ));
    }
    let reopened_bytes = response_bytes(reopened_readback).await?;
    verify_readback(
        &reopened_bytes,
        &view_digest,
        &[
            (hold_command_id.as_str(), &hold_receipt.commit_seq, None),
            (
                journal_command_id.as_str(),
                &journal_receipt.commit_seq,
                Some(journal_words),
            ),
        ],
    )?;
    if reopened_bytes != readback_bytes {
        return Err(LiveJournalError::Invariant(
            "journal readback bytes changed across restart",
        ));
    }

    Ok(LiveJournalReport {
        contract: "joshi.core.live_journal",
        schema_version: 1,
        authority: "read_only_no_execution",
        catalog_schema,
        scene_id,
        view_digest,
        pairing_session_id: session.session_id,
        empty_readback_retention: "served_not_yet_durable".to_owned(),
        subject_mint,
        hold_command_id,
        hold_commit_seq: hold_receipt.commit_seq,
        journal_command_id,
        journal_words: journal_words.to_owned(),
        journal_commit_seq: journal_receipt.commit_seq,
        readback_bytes_digest: format!("sha256:{}", hex_digest(&readback_bytes)),
        reopened_readback_bytes_digest: format!("sha256:{}", hex_digest(&reopened_bytes)),
        readback_identical_across_restart: true,
        journal_words_read_back: true,
        browser_presented: false,
        product_qualified: false,
        ceiling: "route_and_restart_closed_no_human_witness",
    })
}

struct RecordFocus<'a> {
    command_id: &'a str,
    client_session: &'a str,
    client_command_seq: u64,
    scene_id: &'a str,
    view_digest: &'a str,
    subject_kind: &'a str,
    subject_key: &'a str,
    ui_label: &'a str,
    note: Option<&'a str>,
    issued_at: UtcTimestamp,
}

/// Builds exactly the canonical `record_focus` bytes the frozen operator contract admits.
fn record_focus_bytes(input: &RecordFocus<'_>) -> Vec<u8> {
    let note = input.note.map_or_else(
        || "null".to_owned(),
        |words| serde_json::to_string(words).expect("strings always encode"),
    );
    format!(
        concat!(
            r#"{{"contract":"joshi.operator.command","schemaVersion":1,"commandId":"{}","#,
            r#""idempotencyKey":"retry-{}","clientSessionId":"{}","clientCommandSeq":"{}","#,
            r#""scene":{{"sceneId":"{}","viewDigest":"{}"}},"issuedAt":"{}","#,
            r#""clientClock":{{"clockId":"live-journal-walk-clock","monotonicNs":"{}"}},"#,
            r#""commandKind":"record_focus","subject":{{"kind":"{}","key":"{}"}},"#,
            r#""payload":{{"context":{{"uiLabel":"{}","uiLabelVersion":"1","#,
            r#""confidencePpm":null,"urgency":null,"whyNow":null,"note":{}}},"#,
            r#""dwellMilliseconds":null}},"#,
            r#""authorityClass":"evidence_only","effectCeiling":"observe_only"}}"#
        ),
        input.command_id,
        input.command_id,
        input.client_session,
        input.client_command_seq,
        input.scene_id,
        input.view_digest,
        input.issued_at,
        input.client_command_seq,
        input.subject_kind,
        input.subject_key,
        input.ui_label,
        note,
    )
    .into_bytes()
}

async fn append(
    app: &axum::Router,
    origin: &str,
    capability: &str,
    bytes: Vec<u8>,
) -> Result<CommandReceiptBody, LiveJournalError> {
    let response = send(
        app,
        authorized(
            origin,
            "POST",
            "/api/v1/operator/commands",
            capability,
            Body::from(bytes),
        )?,
    )
    .await;
    let status = response.status();
    let body = response_bytes(response).await?;
    if status != StatusCode::ACCEPTED {
        return Err(LiveJournalError::Refused(
            String::from_utf8_lossy(&body).into_owned(),
        ));
    }
    Ok(serde_json::from_slice(&body)?)
}

/// Requires the readback body to carry exactly the expected commands, in commit order, bound to
/// the exact view digest, with any expected words present verbatim.
fn verify_readback(
    bytes: &[u8],
    view_digest: &str,
    expected: &[(&str, &String, Option<&str>)],
) -> Result<(), LiveJournalError> {
    let body: ReadbackBody = serde_json::from_slice(bytes)?;
    if body.scene_retention != "durable" {
        return Err(LiveJournalError::Invariant(
            "post-act readback does not state a durable scene",
        ));
    }
    if body.commands.len() != expected.len() {
        return Err(LiveJournalError::Invariant(
            "readback command count differs from the acts committed",
        ));
    }
    for (command, (command_id, commit_seq, words)) in body.commands.iter().zip(expected) {
        if command.command_id != *command_id
            || command.commit_seq != **commit_seq
            || command.scene.view_digest.as_deref() != Some(view_digest)
        {
            return Err(LiveJournalError::Invariant(
                "readback command identity, order, or scene binding differs",
            ));
        }
        if let Some(words) = words {
            let note = command
                .payload
                .get("context")
                .and_then(|context| context.get("note"))
                .and_then(serde_json::Value::as_str);
            if note != Some(*words) {
                return Err(LiveJournalError::Invariant(
                    "journal words did not come back verbatim",
                ));
            }
        }
    }
    Ok(())
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ReadbackBody {
    scene_retention: String,
    commands: Vec<ReadbackCommandBody>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ReadbackCommandBody {
    command_id: String,
    commit_seq: String,
    scene: ReadbackSceneBody,
    payload: serde_json::Value,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ReadbackSceneBody {
    view_digest: Option<String>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct CommandReceiptBody {
    commit_seq: String,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::live_gesture::live_fixture::{FIXTURE_MINT, FIXTURE_SOURCE, seed_catalog};

    const WORDS: &str = "SOLVE likely rips 0-60%; DREGG probably stays 300-500K with an \
                         unlikely spike to 700K+ because Dragon's Clutch is in release prep.";

    #[tokio::test]
    async fn journal_words_survive_restart_and_read_back_verbatim_through_the_route() {
        let root = tempfile::tempdir().expect("temporary live journal root");
        let catalog = root.path().join("catalog");
        let state = root.path().join("state");
        seed_catalog(&catalog).expect("seeded fixture catalog");

        let report = run_live_journal_walk(
            &catalog,
            &state,
            FIXTURE_SOURCE,
            "http://127.0.0.1:4173",
            WORDS,
        )
        .await
        .expect("live journal walk");

        assert_eq!(report.subject_mint, FIXTURE_MINT);
        assert_eq!(report.empty_readback_retention, "served_not_yet_durable");
        assert_eq!(report.journal_words, WORDS);
        assert!(report.readback_identical_across_restart);
        assert!(report.journal_words_read_back);
        assert_eq!(
            report.readback_bytes_digest,
            report.reopened_readback_bytes_digest
        );
        // Commit order is the journal's time order: the hold landed before the entry.
        let hold: u64 = report.hold_commit_seq.parse().expect("hold commit");
        let entry: u64 = report.journal_commit_seq.parse().expect("entry commit");
        assert!(hold < entry);
        assert!(!report.browser_presented);
        assert!(!report.product_qualified);
    }

    #[tokio::test]
    async fn a_wordless_journal_entry_is_refused_not_stored_blank() {
        let root = tempfile::tempdir().expect("temporary refusal root");
        let error = run_live_journal_walk(
            &root.path().join("catalog"),
            &root.path().join("state"),
            FIXTURE_SOURCE,
            "http://127.0.0.1:4173",
            "   ",
        )
        .await
        .expect_err("blank words must be refused before any store or route work");
        assert!(error.to_string().contains("no words"));
    }
}

/// Failure to complete the live journal restart walk.
#[derive(Debug, Error)]
pub enum LiveJournalError {
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Gesture(#[from] LiveGestureError),
    #[error(transparent)]
    Pairing(#[from] OrdinaryPairingError),
    #[error(transparent)]
    PairingGeneration(#[from] PairingCapabilityGenerationError),
    #[error(transparent)]
    Protocol(#[from] joshi_pairing::PairingError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("operator route refused the journal act: {0}")]
    Refused(String),
    #[error("live journal invariant failed: {0}")]
    Invariant(&'static str),
}
