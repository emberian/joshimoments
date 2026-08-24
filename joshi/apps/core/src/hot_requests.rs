//! The operational hot-attention channel: one owner-only file under the keeper root.
//!
//! When Ember focuses in on a coin — a hold (`record_focus` on a candidate), a hot-scope request,
//! or the automatic inspect-lens assertion Glass emits — the act itself is already durable in the
//! session store the moment the operator route commits it. THAT is the evidence. This module is
//! only the operational channel derived from it: after a qualifying act commits, core appends the
//! coin's mint to `<keeper-root>/hot-requests.json` so a keeper watching that root starts tapping
//! the mint (candles, trades, one coin record, one callout read) while her attention is on it.
//!
//! THE SEAM IS NAMED. Core writes this file; the keeper re-reads it every tick exactly the way it
//! re-reads its config; neither imports the other. The mirrored constants live in
//! `apps/collector/src/keeper.rs` (`HOT_REQUESTS_CONTRACT` there must match here, like Glass's
//! `HOLD_UI_LABEL` mirrors `live_gesture.rs`). A keeper that never sees the file — the operator
//! runs core on a different box, or no keeper exists — simply never has hot mints: degradation is
//! silence-with-absence, never an error, and the durable acts lose nothing.
//!
//! The file is never evidence. Its `authority` field says so in every copy, it is rewritten
//! whole (atomic rename, owner-only), entries expire on a TTL that further acts refresh, and a
//! malformed file is recovered by rewriting rather than guessed about — core is its only writer.

use joshi_operator::{OperatorCommandKind, ValidatedOperatorCommandV1};
use serde::{Deserialize, Serialize};
use std::{fs, io::Write as _, path::Path, time::Duration};
use thiserror::Error;
use time::OffsetDateTime;

/// File name under the keeper root. The keeper mirrors this constant.
pub const HOT_REQUESTS_FILE_NAME: &str = "hot-requests.json";
/// The seam's contract identifier. The keeper mirrors this constant.
pub const HOT_REQUESTS_CONTRACT: &str = "joshi.attention.hot_requests.v1";
/// What every copy of the file states about itself.
pub const HOT_REQUESTS_AUTHORITY: &str =
    "operational_signal_derived_from_durable_acts_not_evidence";
/// How long one act keeps a mint requested-hot; any further qualifying act refreshes it.
/// Thirty minutes, spelled in seconds because `Duration::from_mins` is not yet stable.
#[allow(clippy::duration_suboptimal_units)]
pub const HOT_REQUEST_TTL: Duration = Duration::from_secs(30 * 60);
/// Hard bound on entries the file may carry. When a fresh request would exceed it, the entries
/// expiring soonest are dropped first — they are the least-recently-refreshed attention.
pub const MAX_HOT_REQUESTS: usize = 16;
const MAX_FILE_BYTES: u64 = 256 * 1024;

/// One requested-hot mint. Times are the store's six-digit UTC wire format.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HotRequestV1 {
    pub mint: String,
    pub first_requested_at: String,
    pub last_requested_at: String,
    /// Hotness end unless refreshed. The keeper stops hot taps at this instant with a note,
    /// never an error.
    pub expires_at: String,
    /// The qualifying act that most recently refreshed this entry, for reading the file by hand.
    /// Operational breadcrumbs only — the durable acts in the session store are the record.
    pub last_command_kind: String,
    pub last_command_id: String,
    pub last_commit_seq: String,
}

/// The whole file. Unknown fields are tolerated on read so version drift degrades gently.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HotRequestsV1 {
    pub contract: String,
    pub schema_version: u16,
    pub authority: String,
    pub written_at: String,
    pub requests: Vec<HotRequestV1>,
}

/// What one qualifying act asks to run hot, extracted from the validated command.
///
/// - `record_focus` on a candidate subject (the hold, and the deliberate focus capture) names
///   the candidate key, which in a live surface is the mint itself.
/// - `request_hot_scope` names the mint inside its payload (`scope.subject` of kind `mint`) —
///   both the manual capture and the automatic inspect-lens assertion carry it there, whatever
///   the command's own subject is (candidate for the manual gesture, scene for the automatic
///   one, which keeps the automatic act invisible to the selection instrument).
///
/// Anything else — journal words, choice sets, dispositions — is attention *about* a scene, not
/// a request for richer observation of one coin, and never reaches the file. A key that is not a
/// plausible base58 mint (a fixture candidate id, a non-live surface) is also refused here: the
/// keeper re-validates with a full base58 decode before spending a request, so this filter only
/// keeps obvious non-mints out of the channel.
#[must_use]
pub fn qualifying_hot_mint(command: &ValidatedOperatorCommandV1) -> Option<String> {
    let key = match command.kind() {
        OperatorCommandKind::RecordFocus => {
            if command.subject().kind().as_str() != "candidate" {
                return None;
            }
            command.subject().key().as_str().to_owned()
        }
        OperatorCommandKind::RequestHotScope => {
            let payload: HotScopePayloadMirror =
                serde_json::from_slice(command.payload_bytes()).ok()?;
            if payload.scope.subject.kind != "mint" {
                return None;
            }
            payload.scope.subject.key
        }
        _ => return None,
    };
    plausible_mint(&key).then_some(key)
}

/// Base58 charset and 32-byte-address length envelope, without decoding. See
/// [`qualifying_hot_mint`] for why plausibility suffices on this side of the seam.
fn plausible_mint(value: &str) -> bool {
    const BASE58: &str = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    (32..=44).contains(&value.len()) && value.chars().all(|character| BASE58.contains(character))
}

#[derive(Deserialize)]
struct HotScopePayloadMirror {
    scope: HotScopeMirror,
}

#[derive(Deserialize)]
struct HotScopeMirror {
    subject: HotScopeSubjectMirror,
}

#[derive(Deserialize)]
struct HotScopeSubjectMirror {
    kind: String,
    key: String,
}

/// Record one qualifying act into the file: read, prune expired, upsert the mint (TTL refreshed,
/// first-requested instant kept), bound the entry count, write atomically owner-only.
///
/// # Errors
///
/// Fails on filesystem trouble or a symlinked target. Callers on the act-commit path must treat
/// a failure as operational noise (log it), never as a reason to fail the already-durable act.
pub fn record_hot_request(
    path: &Path,
    mint: &str,
    command_kind: &str,
    command_id: &str,
    commit_seq: &str,
    now: OffsetDateTime,
) -> Result<(), HotRequestsError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            return Err(HotRequestsError::UnsafeFile);
        }
        _ => {}
    }
    let now_wire = wire_instant(now)?;
    let expires_wire = wire_instant(now + time::Duration::seconds(ttl_seconds()))?;
    // Core is this file's single writer, so an unreadable or malformed file is a torn or foreign
    // artifact; the honest recovery for an operational channel is a fresh rewrite, not a guess.
    let mut requests = read_requests(path)
        .map(|file| file.requests)
        .unwrap_or_default();
    requests.retain(|request| !expired(&request.expires_at, now));
    if let Some(existing) = requests.iter_mut().find(|request| request.mint == mint) {
        existing.last_requested_at.clone_from(&now_wire);
        existing.expires_at = expires_wire;
        command_kind.clone_into(&mut existing.last_command_kind);
        command_id.clone_into(&mut existing.last_command_id);
        commit_seq.clone_into(&mut existing.last_commit_seq);
    } else {
        requests.push(HotRequestV1 {
            mint: mint.to_owned(),
            first_requested_at: now_wire.clone(),
            last_requested_at: now_wire.clone(),
            expires_at: expires_wire,
            last_command_kind: command_kind.to_owned(),
            last_command_id: command_id.to_owned(),
            last_commit_seq: commit_seq.to_owned(),
        });
    }
    if requests.len() > MAX_HOT_REQUESTS {
        // Soonest-expiring first out; the entry just refreshed has the latest expiry and stays.
        requests.sort_by(|left, right| left.expires_at.cmp(&right.expires_at));
        let excess = requests.len() - MAX_HOT_REQUESTS;
        requests.drain(..excess);
    }
    requests.sort_by(|left, right| left.mint.cmp(&right.mint));
    let file = HotRequestsV1 {
        contract: HOT_REQUESTS_CONTRACT.to_owned(),
        schema_version: 1,
        authority: HOT_REQUESTS_AUTHORITY.to_owned(),
        written_at: now_wire,
        requests,
    };
    write_atomic(path, &serde_json::to_vec_pretty(&file)?)
}

/// Read the file as core last wrote it. `None` for absent, unreadable, oversized, or malformed —
/// the caller rewrites; nothing here is evidence to preserve.
#[must_use]
pub fn read_requests(path: &Path) -> Option<HotRequestsV1> {
    let metadata = fs::metadata(path).ok()?;
    if !metadata.is_file() || metadata.len() > MAX_FILE_BYTES {
        return None;
    }
    let bytes = fs::read(path).ok()?;
    let file: HotRequestsV1 = serde_json::from_slice(&bytes).ok()?;
    (file.contract == HOT_REQUESTS_CONTRACT && file.schema_version == 1).then_some(file)
}

fn expired(expires_at: &str, now: OffsetDateTime) -> bool {
    parse_wire(expires_at).is_none_or(|instant| instant <= now)
}

fn parse_wire(value: &str) -> Option<OffsetDateTime> {
    value
        .parse::<joshi_domain::UtcTimestamp>()
        .ok()
        .map(joshi_domain::UtcTimestamp::as_datetime)
}

fn wire_instant(value: OffsetDateTime) -> Result<String, HotRequestsError> {
    let nanosecond = value.nanosecond();
    let truncated = value
        .replace_nanosecond(nanosecond - nanosecond % 1_000)
        .map_err(|_| HotRequestsError::Clock)?;
    Ok(joshi_domain::UtcTimestamp::new(truncated)
        .map_err(|_| HotRequestsError::Clock)?
        .to_string())
}

fn ttl_seconds() -> i64 {
    i64::try_from(HOT_REQUEST_TTL.as_secs()).expect("the TTL constant fits an i64")
}

fn write_atomic(path: &Path, bytes: &[u8]) -> Result<(), HotRequestsError> {
    let temporary = path.with_extension("json.tmp");
    {
        let mut file = fs::File::create(&temporary)
            .map_err(|error| HotRequestsError::Io(error.to_string()))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt as _;
            file.set_permissions(fs::Permissions::from_mode(0o600))
                .map_err(|error| HotRequestsError::Io(error.to_string()))?;
        }
        file.write_all(bytes)
            .map_err(|error| HotRequestsError::Io(error.to_string()))?;
        file.sync_all()
            .map_err(|error| HotRequestsError::Io(error.to_string()))?;
    }
    fs::rename(&temporary, path).map_err(|error| HotRequestsError::Io(error.to_string()))
}

#[derive(Debug, Error)]
pub enum HotRequestsError {
    #[error("hot-requests file write failed: {0}")]
    Io(String),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("hot-requests path is a symlink or not a regular file")]
    UnsafeFile,
    #[error("system clock does not represent as a wire instant")]
    Clock,
}

#[cfg(test)]
mod tests {
    use super::*;
    use joshi_domain::UtcTimestamp;

    const MINT: &str = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump";
    const OTHER: &str = "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump";

    fn instant(value: &str) -> OffsetDateTime {
        value
            .parse::<UtcTimestamp>()
            .expect("instant")
            .as_datetime()
    }

    fn command_bytes(kind: &str, subject_kind: &str, subject_key: &str, payload: &str) -> Vec<u8> {
        format!(
            concat!(
                r#"{{"contract":"joshi.operator.command","schemaVersion":1,"#,
                r#""commandId":"command-hot-1","idempotencyKey":"retry-hot-1","#,
                r#""clientSessionId":"session-hot","clientCommandSeq":"1","#,
                r#""scene":{{"sceneId":"scene-hot-1","viewDigest":"sha256:{}"}},"#,
                r#""issuedAt":"2026-08-24T00:00:00.000000Z","#,
                r#""clientClock":{{"clockId":"hot-test-clock","monotonicNs":"1"}},"#,
                r#""commandKind":"{}","subject":{{"kind":"{}","key":"{}"}},"#,
                r#""payload":{},"#,
                r#""authorityClass":"evidence_only","effectCeiling":"observe_only"}}"#
            ),
            "a".repeat(64),
            kind,
            subject_kind,
            subject_key,
            payload,
        )
        .into_bytes()
    }

    fn context() -> &'static str {
        r#"{"uiLabel":"Test","uiLabelVersion":"1","confidencePpm":null,"urgency":null,"whyNow":null,"note":null}"#
    }

    #[test]
    fn a_hold_and_both_hot_scope_shapes_qualify_and_nothing_else_does() {
        let hold = ValidatedOperatorCommandV1::parse_exact(&command_bytes(
            "record_focus",
            "candidate",
            MINT,
            &format!(r#"{{"context":{},"dwellMilliseconds":null}}"#, context()),
        ))
        .expect("hold parses");
        assert_eq!(qualifying_hot_mint(&hold).as_deref(), Some(MINT));

        // The manual capture: candidate subject, mint restated in the scope payload.
        let manual = ValidatedOperatorCommandV1::parse_exact(&command_bytes(
            "request_hot_scope",
            "candidate",
            MINT,
            &format!(
                r#"{{"context":{},"scope":{{"family":"candidate-attention","subject":{{"kind":"mint","key":"{OTHER}"}}}}}}"#,
                context()
            ),
        ))
        .expect("manual hot scope parses");
        assert_eq!(qualifying_hot_mint(&manual).as_deref(), Some(OTHER));

        // The automatic inspect assertion: scene subject, mint only in the payload — the shape
        // that keeps it invisible to the selection instrument's candidate-named chosen set.
        let automatic = ValidatedOperatorCommandV1::parse_exact(&command_bytes(
            "request_hot_scope",
            "scene",
            "scene-hot-1",
            &format!(
                r#"{{"context":{},"scope":{{"family":"candidate-attention","subject":{{"kind":"mint","key":"{MINT}"}}}}}}"#,
                context()
            ),
        ))
        .expect("automatic hot scope parses");
        assert_eq!(qualifying_hot_mint(&automatic).as_deref(), Some(MINT));

        // A scene-subject focus (the F capture over a scene) names no coin.
        let scene_focus = ValidatedOperatorCommandV1::parse_exact(&command_bytes(
            "record_focus",
            "scene",
            "scene-hot-1",
            &format!(r#"{{"context":{},"dwellMilliseconds":null}}"#, context()),
        ))
        .expect("scene focus parses");
        assert!(qualifying_hot_mint(&scene_focus).is_none());

        // A fixture candidate id is not a plausible mint and stays out of the channel.
        let fixture = ValidatedOperatorCommandV1::parse_exact(&command_bytes(
            "record_focus",
            "candidate",
            "coin-a",
            &format!(r#"{{"context":{},"dwellMilliseconds":null}}"#, context()),
        ))
        .expect("fixture hold parses");
        assert!(qualifying_hot_mint(&fixture).is_none());
    }

    #[test]
    fn requests_are_deduped_ttl_refreshed_pruned_and_written_atomically() {
        let dir = tempfile::tempdir().expect("temp dir");
        let path = dir.path().join(HOT_REQUESTS_FILE_NAME);
        let t0 = instant("2026-08-24T10:00:00.000000Z");
        record_hot_request(&path, MINT, "record_focus", "command-1", "10", t0)
            .expect("first write");
        let file = read_requests(&path).expect("file reads back");
        assert_eq!(file.contract, HOT_REQUESTS_CONTRACT);
        assert_eq!(file.authority, HOT_REQUESTS_AUTHORITY);
        assert_eq!(file.requests.len(), 1);
        assert_eq!(file.requests[0].mint, MINT);
        assert_eq!(file.requests[0].expires_at, "2026-08-24T10:30:00.000000Z");
        assert!(
            !path.with_extension("json.tmp").exists(),
            "no temp file lingers"
        );

        // A later act on the same mint refreshes the TTL and keeps the first instant.
        let t1 = instant("2026-08-24T10:10:00.000000Z");
        record_hot_request(&path, MINT, "request_hot_scope", "command-2", "11", t1)
            .expect("refresh");
        let file = read_requests(&path).expect("file reads back");
        assert_eq!(file.requests.len(), 1, "same mint is deduped");
        assert_eq!(
            file.requests[0].first_requested_at,
            "2026-08-24T10:00:00.000000Z"
        );
        assert_eq!(file.requests[0].expires_at, "2026-08-24T10:40:00.000000Z");
        assert_eq!(file.requests[0].last_command_kind, "request_hot_scope");
        assert_eq!(file.requests[0].last_commit_seq, "11");

        // A second mint coexists; the first expires out on a later write.
        record_hot_request(&path, OTHER, "record_focus", "command-3", "12", t1)
            .expect("second mint");
        assert_eq!(read_requests(&path).expect("reads").requests.len(), 2);
        let past_first_expiry = instant("2026-08-24T10:41:00.000000Z");
        record_hot_request(
            &path,
            OTHER,
            "record_focus",
            "command-4",
            "13",
            past_first_expiry,
        )
        .expect("expiring write");
        let file = read_requests(&path).expect("reads");
        assert_eq!(file.requests.len(), 1, "the stale mint expired out");
        assert_eq!(file.requests[0].mint, OTHER);
    }

    #[test]
    fn a_malformed_file_is_rewritten_and_the_bound_drops_soonest_expiring_first() {
        let dir = tempfile::tempdir().expect("temp dir");
        let path = dir.path().join(HOT_REQUESTS_FILE_NAME);
        std::fs::write(&path, b"{ not json").expect("malformed seed");
        let t0 = instant("2026-08-24T10:00:00.000000Z");
        record_hot_request(&path, MINT, "record_focus", "command-1", "10", t0)
            .expect("recovery write");
        assert_eq!(read_requests(&path).expect("reads").requests.len(), 1);

        // Fill past the bound with staggered expiries; the freshest survive.
        for ordinal in 0..MAX_HOT_REQUESTS {
            let at = t0 + time::Duration::seconds(i64::try_from(ordinal).expect("small") + 1);
            let mint = format!("{}{:02}", &MINT[..MINT.len() - 2], ordinal);
            record_hot_request(&path, &mint, "record_focus", "command-n", "20", at).expect("fill");
        }
        let file = read_requests(&path).expect("reads");
        assert_eq!(file.requests.len(), MAX_HOT_REQUESTS, "the bound holds");
        assert!(
            !file.requests.iter().any(|request| request.mint == MINT),
            "the soonest-expiring entry was dropped first"
        );
    }
}
