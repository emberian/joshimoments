//! Exact, human-readable rendering of a surface derived from committed catalog rows.
//!
//! [`readback`](crate::readback) removes the caller from the *input* side of a cut: population,
//! facts, gaps and both clocks come from rows a real single-writer store committed. This module is
//! the *output* side. It turns one [`DerivedSurfaceV1`] into the two things a rendered surface has
//! to be at once:
//!
//! * **a body a person reads** -- line-oriented UTF-8 text naming every eligible subject, every
//!   count, the cutoff, every derived cell, and every coverage gap with the exact window the
//!   producer authored; and
//! * **an exact artifact** -- those same bytes under a sha256 body digest, plus a small
//!   [`SurfaceRenderHeadV1`] that names the body digest, the cut, and the derivation it came from.
//!
//! # Determinism
//!
//! The body is a pure function of the derived surface. It contains no wall clock of its own, no
//! process identity, no path, no locale-dependent formatting and no iteration over an unordered
//! collection: every list it walks is already ordered by the DTO that carries it. Rendering the
//! same cut in another process, on another day, produces byte-identical output, which is what
//! makes the restart proof in `render_tests` a statement about the data rather than about one
//! process.
//!
//! # Digest domains
//!
//! Two digests, deliberately different in kind:
//!
//! * [`SurfaceRenderHeadV1::body_digest`] is the plain sha256 of the exact body bytes, with no
//!   domain tag and no envelope, so that anybody holding the rendered file can check it with
//!   `sha256sum` and get the same hex. This matches how the catalog identifies retained provider
//!   bytes (`blob.blob_id`) and how `joshi-publication` identifies prepared artifact bytes.
//! * [`SurfaceRenderHeadV1::head_digest`] is the sha256 of a canonical JSON material whose first
//!   field is the constant [`SURFACE_RENDER_HEAD_DOMAIN`]. The head is a small object of digests
//!   and counts that would otherwise be structurally interchangeable with other JOSHI receipts, so
//!   it is domain-separated the same way [`SurfaceDerivationReceiptV1`] separates its own material.
//!
//! # What this module refuses
//!
//! A render is not an opportunity to restate the data. Every value in the body is copied from the
//! cut or its derivation receipt; nothing is recomputed differently, summarized, rounded, or
//! filled in. The one class of text that is not copied from the data is the fixed `CEILING` block
//! and the explicit absence notes, which state what the artifact *is* -- bounded by one catalog,
//! recomputed at a cutoff, and silent about anything no row mentions -- so that an empty section
//! can never be read as evidence that nothing happened.

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    DerivedSurfaceV1, FieldState, READ_ONLY_AUTHORITY, SurfaceCutV1, SurfaceDerivationReceiptV1,
    SurfaceError, SurfaceGapBoundaryV1, SurfaceMembership, SurfaceObservationV1, SurfaceOpenGapV1,
};

/// Contract discriminator for a rendered surface head.
pub const SURFACE_RENDER_CONTRACT: &str = "joshi.surface.render.v1";
/// Wire schema version of [`SurfaceRenderHeadV1`].
pub const SURFACE_RENDER_SCHEMA_VERSION: u16 = 1;
/// Media type of the rendered body bytes.
pub const SURFACE_RENDER_MEDIA_TYPE: &str = "text/plain; charset=utf-8";
/// Domain tag mixed into [`SurfaceRenderHeadV1::head_digest`].
pub const SURFACE_RENDER_HEAD_DOMAIN: &str = "joshi.surface.render.head.v1";

/// Exact identity of one rendered surface: what was rendered, from which cut, into which bytes.
///
/// Every field is derived from the cut and its derivation receipt. Nothing here is a caller
/// projection, including the counts, which are copied from values the readback adapter recomputed
/// from committed rows.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SurfaceRenderHeadV1 {
    /// Contract discriminator; always [`SURFACE_RENDER_CONTRACT`].
    pub contract: StableString,
    /// Wire schema version.
    pub schema_version: u16,
    /// Media type of the body bytes.
    pub media_type: StableString,
    /// Highest applied catalog migration at derivation time.
    pub catalog_schema_version: WireU64,
    /// Durable knowledge order the cut was taken at.
    pub cutoff_commit_seq: WireU64,
    /// Wall time of that exact commit, read from the catalog.
    pub cutoff: UtcTimestamp,
    /// Approved profile the cut closes against.
    pub profile_digest: ValueDigest,
    /// Exact identity of the reduced cut.
    pub reducer_digest: ValueDigest,
    /// Exact identity of the derivation that produced the cut.
    pub derivation_digest: ValueDigest,
    /// Exact identity of the eligible population.
    pub eligible_digest: ValueDigest,
    /// Size of the eligible population at the cutoff.
    pub eligible_count: WireU64,
    /// Rendered fact rows in the body.
    pub rendered_rows: WireU64,
    /// Subjects the body renders, in body order. A subject with several surface rows appears once.
    pub rendered_subjects: Vec<StableString>,
    /// Eligible subjects the body reports as omitted, with a reason, rather than rendered.
    pub omitted_subjects: WireU64,
    /// Coverage gaps open at the cutoff, each rendered with its exact window.
    pub open_gaps: WireU64,
    /// Inputs the derivation could not resolve from the catalog.
    pub unresolved_inputs: WireU64,
    /// Exact byte length of the body.
    pub body_length: WireU64,
    /// Plain sha256 of the exact body bytes.
    pub body_digest: ValueDigest,
    /// Read-only authority carried by every reduced artifact.
    pub authority: StableString,
    /// Domain-separated exact identity digest over every field above.
    pub head_digest: ValueDigest,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct HeadMaterial<'a> {
    domain: &'static str,
    contract: &'a StableString,
    schema_version: u16,
    media_type: &'a StableString,
    catalog_schema_version: WireU64,
    cutoff_commit_seq: WireU64,
    cutoff: &'a UtcTimestamp,
    profile_digest: &'a ValueDigest,
    reducer_digest: &'a ValueDigest,
    derivation_digest: &'a ValueDigest,
    eligible_digest: &'a ValueDigest,
    eligible_count: WireU64,
    rendered_rows: WireU64,
    rendered_subjects: &'a [StableString],
    omitted_subjects: WireU64,
    open_gaps: WireU64,
    unresolved_inputs: WireU64,
    body_length: WireU64,
    body_digest: &'a ValueDigest,
    authority: &'a StableString,
}

impl SurfaceRenderHeadV1 {
    /// Recompute the head's domain-separated identity digest.
    ///
    /// # Errors
    ///
    /// Returns an error if the material cannot be encoded or digested.
    pub fn computed_digest(&self) -> Result<ValueDigest, SurfaceError> {
        let bytes = serde_json::to_vec(&HeadMaterial {
            domain: SURFACE_RENDER_HEAD_DOMAIN,
            contract: &self.contract,
            schema_version: self.schema_version,
            media_type: &self.media_type,
            catalog_schema_version: self.catalog_schema_version,
            cutoff_commit_seq: self.cutoff_commit_seq,
            cutoff: &self.cutoff,
            profile_digest: &self.profile_digest,
            reducer_digest: &self.reducer_digest,
            derivation_digest: &self.derivation_digest,
            eligible_digest: &self.eligible_digest,
            eligible_count: self.eligible_count,
            rendered_rows: self.rendered_rows,
            rendered_subjects: &self.rendered_subjects,
            omitted_subjects: self.omitted_subjects,
            open_gaps: self.open_gaps,
            unresolved_inputs: self.unresolved_inputs,
            body_length: self.body_length,
            body_digest: &self.body_digest,
            authority: &self.authority,
        })?;
        digest(&bytes)
    }

    /// Validate the head contract and its self-declared exact digest.
    ///
    /// # Errors
    ///
    /// Returns [`SurfaceError::Contract`] for a wrong contract, schema, media type or authority,
    /// and [`SurfaceError::DigestMismatch`] when the declared digest is not the computed one.
    pub fn validate(&self) -> Result<(), SurfaceError> {
        if self.contract.as_str() != SURFACE_RENDER_CONTRACT
            || self.schema_version != SURFACE_RENDER_SCHEMA_VERSION
            || self.media_type.as_str() != SURFACE_RENDER_MEDIA_TYPE
            || self.authority.as_str() != READ_ONLY_AUTHORITY
        {
            return Err(SurfaceError::Contract);
        }
        if self.computed_digest()? != self.head_digest {
            return Err(SurfaceError::DigestMismatch);
        }
        Ok(())
    }

    /// Compact canonical head bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the head does not validate or cannot be encoded.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, SurfaceError> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }
}

/// Parse strict canonical render-head bytes produced by this module.
///
/// # Errors
///
/// Returns [`SurfaceError::DigestMismatch`] when the input is not byte-for-byte the canonical
/// encoding of the value it decodes to.
pub fn parse_surface_render_head(bytes: &[u8]) -> Result<SurfaceRenderHeadV1, SurfaceError> {
    let head: SurfaceRenderHeadV1 = serde_json::from_slice(bytes)?;
    head.validate()?;
    if head.canonical_bytes()? != bytes {
        return Err(SurfaceError::DigestMismatch);
    }
    Ok(head)
}

/// One rendered surface: exact body bytes and the head that names them.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RenderedSurfaceV1 {
    head: SurfaceRenderHeadV1,
    body: String,
}

impl RenderedSurfaceV1 {
    /// Exact identity of this render.
    #[must_use]
    pub const fn head(&self) -> &SurfaceRenderHeadV1 {
        &self.head
    }

    /// Exact rendered bytes. This is the artifact a person opens and a digest covers.
    #[must_use]
    pub fn body(&self) -> &[u8] {
        self.body.as_bytes()
    }

    /// Exact rendered text. The body is UTF-8 by construction.
    #[must_use]
    pub fn body_text(&self) -> &str {
        &self.body
    }

    /// Revalidate the head and recompute the body length and digest from the bytes themselves.
    ///
    /// # Errors
    ///
    /// Returns [`SurfaceError::DigestMismatch`] when the head does not name these exact bytes.
    pub fn validate(&self) -> Result<(), SurfaceError> {
        self.head.validate()?;
        let length = u64::try_from(self.body.len()).map_err(|_| SurfaceError::DigestFormat)?;
        if self.head.body_length != WireU64::new(length)
            || self.head.body_digest != digest(self.body.as_bytes())?
        {
            return Err(SurfaceError::DigestMismatch);
        }
        Ok(())
    }
}

/// Render one derived surface into exact bytes plus their head.
///
/// The caller supplies neither a count, a cutoff, a subject, a gap window nor a digest: every one
/// of them is copied from the derived cut and its derivation receipt, both of which are revalidated
/// here before a byte is written.
///
/// # Errors
///
/// Returns [`SurfaceError::Contract`] when the cut and the derivation receipt do not describe the
/// same occurrence, and propagates any cut, receipt, encoding or digest failure.
pub fn render_surface(derived: &DerivedSurfaceV1) -> Result<RenderedSurfaceV1, SurfaceError> {
    derived.cut.validate()?;
    derived.derivation.validate()?;
    let cut = &derived.cut;
    let receipt = &derived.derivation;
    // A cut and a receipt that do not describe the same occurrence would render a body whose
    // counts and whose rows came from two different cutoffs.
    if cut.cutoff != receipt.cutoff
        || cut.profile_digest != receipt.profile_digest
        || cut.universe.eligible_count != receipt.eligible_count
    {
        return Err(SurfaceError::Contract);
    }

    let body = body_text(cut, receipt)?;
    let body_length = u64::try_from(body.len()).map_err(|_| SurfaceError::DigestFormat)?;
    let mut rendered_subjects: Vec<StableString> = Vec::new();
    for row in &cut.rendered {
        if !rendered_subjects.contains(&row.subject) {
            rendered_subjects.push(row.subject.clone());
        }
    }
    let mut head = SurfaceRenderHeadV1 {
        contract: stable(SURFACE_RENDER_CONTRACT)?,
        schema_version: SURFACE_RENDER_SCHEMA_VERSION,
        media_type: stable(SURFACE_RENDER_MEDIA_TYPE)?,
        catalog_schema_version: receipt.catalog_schema_version,
        cutoff_commit_seq: receipt.cutoff_commit_seq,
        cutoff: cut.cutoff,
        profile_digest: cut.profile_digest.clone(),
        reducer_digest: cut.reducer_digest.clone(),
        derivation_digest: receipt.derivation_digest.clone(),
        eligible_digest: cut.universe.eligible_digest.clone(),
        eligible_count: cut.universe.eligible_count,
        rendered_rows: WireU64::new(count(cut.rendered.len())?),
        rendered_subjects,
        omitted_subjects: WireU64::new(count(cut.omissions.len())?),
        open_gaps: WireU64::new(count(receipt.open_gaps.len())?),
        unresolved_inputs: WireU64::new(count(receipt.unresolved.len())?),
        body_length: WireU64::new(body_length),
        body_digest: digest(body.as_bytes())?,
        authority: stable(READ_ONLY_AUTHORITY)?,
        head_digest: digest(b"placeholder")?,
    };
    head.head_digest = head.computed_digest()?;
    let rendered = RenderedSurfaceV1 { head, body };
    rendered.validate()?;
    Ok(rendered)
}

/// Accumulates the body one whole line at a time, so no partial line can ever be emitted.
struct Body(String);

impl Body {
    fn line(&mut self, value: &str) {
        self.0.push_str(value);
        self.0.push('\n');
    }

    fn blank(&mut self) {
        self.0.push('\n');
    }
}

#[allow(clippy::too_many_lines)] // One rendered document, in the order a person reads it.
fn body_text(
    cut: &SurfaceCutV1,
    receipt: &SurfaceDerivationReceiptV1,
) -> Result<String, SurfaceError> {
    let mut body = Body(String::new());

    body.line("JOSHI SURFACE RENDER");
    body.line(&format!("contract {SURFACE_RENDER_CONTRACT}"));
    body.line(&format!("schemaVersion {SURFACE_RENDER_SCHEMA_VERSION}"));
    body.line(&format!("authority {}", cut.authority));
    body.line(&format!("mediaType {SURFACE_RENDER_MEDIA_TYPE}"));
    body.line(&format!(
        "catalogSchemaVersion {}",
        receipt.catalog_schema_version.get()
    ));
    body.line(&format!(
        "cutoffCommitSeq {}",
        receipt.cutoff_commit_seq.get()
    ));
    body.line(&format!("cutoff {}", cut.cutoff));
    body.line(&format!("profileDigest {}", cut.profile_digest));
    body.line(&format!("reducerDigest {}", cut.reducer_digest));
    body.line(&format!("derivationDigest {}", receipt.derivation_digest));
    body.line(&format!("eligibleDigest {}", cut.universe.eligible_digest));
    // What the population claims about itself. A reader who is about to divide by
    // `eligibleSubjects` has to be told here, not in a footnote, whether it is a denominator.
    body.line(&format!("universeClosed {}", yes_no(cut.universe.closed)));
    body.line(&format!(
        "universeSampleOnly {}",
        yes_no(cut.universe.sample_only)
    ));
    body.line(&format!(
        "orderingPolicy {}",
        quoted(cut.ordering_policy.as_str())?
    ));

    body.blank();
    body.line("COUNTS");
    body.line(&format!(
        "declaredSubjects {}",
        receipt.declared_subjects.get()
    ));
    body.line(&format!(
        "observedSubjects {}",
        receipt.observed_subjects.get()
    ));
    body.line(&format!(
        "eligibleSubjects {}",
        cut.universe.eligible_count.get()
    ));
    body.line(&format!(
        "committedObservations {}",
        receipt.committed_observations.get()
    ));
    body.line(&format!(
        "observationsNamingNoSubject {}",
        receipt.observations_without_subject.get()
    ));
    body.line(&format!("factRows {}", receipt.fact_rows.get()));
    body.line(&format!(
        "fieldAssertionRows {}",
        receipt.field_assertion_rows.get()
    ));
    body.line(&format!("renderedRows {}", cut.rendered.len()));
    body.line(&format!("omittedSubjects {}", cut.omissions.len()));
    body.line(&format!("fieldCells {}", cut.source_states.len()));
    body.line(&format!("openGaps {}", receipt.open_gaps.len()));
    body.line(&format!("unresolvedInputs {}", receipt.unresolved.len()));

    body.blank();
    body.line(&format!("SOURCES {}", receipt.bindings.len()));
    for binding in &receipt.bindings {
        let catalog = match &binding.catalog_source_id {
            Some(value) => quoted(value.as_str())?,
            None => "unregistered".to_owned(),
        };
        body.line(&format!(
            "source surface={} declared={} catalog={catalog}",
            quoted(binding.surface_id.as_str())?,
            quoted(binding.declared_source.as_str())?
        ));
    }

    body.blank();
    body.line(&format!(
        "SUBJECTS {}",
        cut.universe.eligible_subjects.len()
    ));
    if cut.universe.eligible_subjects.is_empty() {
        body.line(
            "no subject is eligible at this cutoff: that is the absence of a declared or \
             observed subject row, not evidence that the market was empty",
        );
    }
    for subject in &cut.universe.eligible_subjects {
        let rows = cut
            .rendered
            .iter()
            .filter(|row| &row.subject == subject)
            .count();
        if rows > 0 {
            // The memberships are on the subject line, not only on the rows below it, because
            // `observed_undeclared` and `denominator_only` are the two facts a reader most needs
            // to keep apart: a subject that was seen and was never in a denominator, against a
            // subject that was in the denominator and was never seen.
            let mut memberships: Vec<&'static str> = Vec::new();
            for row in cut.rendered.iter().filter(|row| &row.subject == subject) {
                for value in &row.memberships {
                    let name = membership_name(*value);
                    if !memberships.contains(&name) {
                        memberships.push(name);
                    }
                }
            }
            body.line(&format!(
                "subject {} rendered rows={rows} memberships={}",
                quoted(subject.as_str())?,
                memberships.join(",")
            ));
            continue;
        }
        match cut
            .omissions
            .iter()
            .find(|omission| &omission.subject == subject)
        {
            Some(omission) => body.line(&format!(
                "subject {} omitted membership={} reason={}",
                quoted(subject.as_str())?,
                membership_name(omission.membership),
                quoted(omission.reason.as_str())?
            )),
            // An open cut carries no omission for a subject it did not render. Naming it is the
            // only honest option: silently dropping it would shrink the visible denominator.
            None => body.line(&format!(
                "subject {} neither_rendered_nor_omitted",
                quoted(subject.as_str())?
            )),
        }
    }

    body.blank();
    body.line(&format!("ROWS {}", cut.rendered.len()));
    if cut.rendered.is_empty() {
        body.line(
            "no eligible subject carries a committed observation at this cutoff: that is the \
             absence of an observation row, not evidence that nothing was observable",
        );
    }
    for row in &cut.rendered {
        body.line(&row_line(row)?);
    }

    body.blank();
    body.line(&format!("CELLS {}", cut.source_states.len()));
    for state in &cut.source_states {
        body.line(&format!(
            "cell surface={} source={} subject={} field={} {}",
            quoted(state.surface_id.as_str())?,
            quoted(state.source_id.as_str())?,
            quoted(state.subject.as_str())?,
            quoted(state.field.as_str())?,
            field_state(&state.state)?
        ));
    }

    body.blank();
    body.line(&format!("GAPS {}", receipt.open_gaps.len()));
    if receipt.open_gaps.is_empty() {
        body.line(
            "no coverage gap row is open at this cutoff: that is the absence of a gap record, \
             not evidence that coverage was complete",
        );
    }
    for gap in &receipt.open_gaps {
        body.line(&gap_line(gap)?);
    }

    body.blank();
    body.line(&format!("UNRESOLVED {}", receipt.unresolved.len()));
    for input in &receipt.unresolved {
        body.line(&format!("unresolved {}", input.name()));
    }

    body.blank();
    body.line("CEILING");
    body.line(
        "the eligible population is bounded by this catalog at this commit sequence, never by \
         the world",
    );
    body.line(
        "a population that is not closed is not a denominator: a subject can enter it by being \
         observed, so its size is not the bottom of a coverage ratio",
    );
    body.line("every count above was recomputed from committed rows at this cutoff");
    body.line(
        "an absent row is an absent record and is not evidence that the thing did not happen",
    );

    Ok(body.0)
}

fn row_line(row: &SurfaceObservationV1) -> Result<String, SurfaceError> {
    let memberships = row
        .memberships
        .iter()
        .map(|value| membership_name(*value))
        .collect::<Vec<_>>()
        .join(",");
    let supersedes = match &row.supersedes_event_id {
        Some(value) => quoted(value.as_str())?,
        None => "none".to_owned(),
    };
    Ok(format!(
        "row subject={} surface={} source={} memberships={memberships} observedAt={} knownAt={} \
         evidenceDigest={} eventId={} supersedes={supersedes} orderKey={}",
        quoted(row.subject.as_str())?,
        quoted(row.surface_id.as_str())?,
        quoted(row.source_id.as_str())?,
        row.observed_at,
        row.known_at,
        row.evidence_digest,
        quoted(row.event_id.as_str())?,
        quoted(row.order_key.as_str())?
    ))
}

fn gap_line(gap: &SurfaceOpenGapV1) -> Result<String, SurfaceError> {
    let subject = match &gap.subject {
        Some(value) => quoted(value.as_str())?,
        // A gap with no subject is scoped to the whole source, which is a wider claim, not a
        // missing field.
        None => "source_wide".to_owned(),
    };
    let upper = match &gap.window_upper {
        Some(value) => boundary(value)?,
        // The producer wrote no upper boundary: the gap is not bounded above by anything the
        // source said, and this render will not close it on the source's behalf.
        None => "open".to_owned(),
    };
    Ok(format!(
        "gap gapId={} source={} subject={subject} windowLower={} windowUpper={upper} \
         durableSince={} severity={} cause={} expressedInCut={}",
        quoted(gap.gap_id.as_str())?,
        quoted(gap.catalog_source_id.as_str())?,
        boundary(&gap.window_lower)?,
        gap.since,
        quoted(gap.severity.as_str())?,
        quoted(gap.cause.as_str())?,
        if gap.expressed_in_cut { "yes" } else { "no" }
    ))
}

fn boundary(value: &SurfaceGapBoundaryV1) -> Result<String, SurfaceError> {
    Ok(match value {
        SurfaceGapBoundaryV1::Wall { value } => format!("wall:{value}"),
        SurfaceGapBoundaryV1::Commit { value } => format!("commit:{}", value.get()),
        SurfaceGapBoundaryV1::SourceCursor { value } => {
            format!("cursor:{}", quoted(value.as_str())?)
        }
        SurfaceGapBoundaryV1::Unknown { reason } => {
            format!("unknown:{}", quoted(reason.as_str())?)
        }
        SurfaceGapBoundaryV1::Unrecognized { stored } => {
            format!("unrecognized:{}", quoted(stored.as_str())?)
        }
    })
}

fn field_state(state: &FieldState) -> Result<String, SurfaceError> {
    Ok(match state {
        FieldState::Covered { observed_at } => format!("state=covered observedAt={observed_at}"),
        FieldState::Gap { gap_id, since } => {
            format!("state=gap gapId={} since={since}", quoted(gap_id.as_str())?)
        }
        FieldState::Stale {
            observed_at,
            age_seconds,
        } => format!(
            "state=stale observedAt={observed_at} ageSeconds={}",
            age_seconds.get()
        ),
        FieldState::Refused { reason } => {
            format!("state=refused reason={}", quoted(reason.as_str())?)
        }
        FieldState::Unknown { reason } => {
            format!("state=unknown reason={}", quoted(reason.as_str())?)
        }
    })
}

const fn membership_name(value: SurfaceMembership) -> &'static str {
    match value {
        SurfaceMembership::Census => "census",
        SurfaceMembership::Warm => "warm",
        SurfaceMembership::Hot => "hot",
        SurfaceMembership::Episode => "episode",
        SurfaceMembership::ColdControl => "cold_control",
        SurfaceMembership::DenominatorOnly => "denominator_only",
        SurfaceMembership::ObservedUndeclared => "observed_undeclared",
    }
}

/// Renders one stored string as a JSON string literal.
///
/// Identifiers on this wire are [`StableString`]s, so they cannot contain a control character and
/// cannot break the line structure. They can still contain the separators this format uses, so
/// every one of them is quoted and escaped rather than pasted in raw: a subject named `a b` must
/// not be able to look like two fields.
fn quoted(value: &str) -> Result<String, SurfaceError> {
    Ok(serde_json::to_string(value)?)
}

const fn yes_no(value: bool) -> &'static str {
    if value { "yes" } else { "no" }
}

fn stable(value: &str) -> Result<StableString, SurfaceError> {
    StableString::new(value).map_err(|_| SurfaceError::Contract)
}

fn count(value: usize) -> Result<u64, SurfaceError> {
    u64::try_from(value).map_err(|_| SurfaceError::Contract)
}

fn digest(bytes: &[u8]) -> Result<ValueDigest, SurfaceError> {
    let mut hash = Sha256::new();
    hash.update(bytes);
    ValueDigest::new(format!("sha256:{:x}", hash.finalize()))
        .map_err(|_| SurfaceError::DigestFormat)
}
