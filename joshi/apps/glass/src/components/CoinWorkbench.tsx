import { lazy, memo, Suspense } from "react";
import { AlertTriangle, Anchor, CircleDot, Clock3, Eye, Megaphone, NotebookPen, Radio } from "lucide-react";

import type { Candidate, Episode, SocialEvent } from "../contract/v1";
import { basisPoints, candidateName, candidateSymbol, clock, compactUsd, instantOrAbsent, priceSol, sentenceCase, sol } from "../format";
import type { ChartAnchor } from "../operator/contract";
import type { VenueReadoutAnswer } from "../venue/contract";
import { marketCapDisagreementNote } from "./provenance";
import { VenueAndClip } from "./VenueReadoutBlock";

/**
 * The lineage this exact view carries for one metric field, or an explicit absence. Nothing here
 * names a provider, a projection or a fixture that the served evidence list does not name.
 *
 * The knowledge clock travels with the number: a rendered value whose age is hidden reads as
 * current, and this project has measured double-digit basis points of drift inside 30 seconds.
 */
function fieldLineage(candidate: Candidate, field: string): string {
  const reference = candidate.evidence.find((item) => item.field === field);
  if (!reference) return "This view carries no lineage for this field";
  return `${sentenceCase(reference.evidenceClass)} · ${reference.sourceId} · known ${clock(reference.knownAt)}Z`;
}

const MarketChart = lazy(() => import("./MarketChart").then((module) => ({ default: module.MarketChart })));

/**
 * Compact faces for the derivation's machine-readable tags. The wire tag is the identity and
 * stays on the chip's hover; the face gets a label short enough to scan in a chip row. A tag
 * this map does not know renders sentence-cased rather than being hidden.
 */
const TAG_FACE: Record<string, string> = {
  chain_observed: "chain-observed",
  ticker_unobserved: "no ticker",
  no_price_observed: "no price",
  gap_compressed_path: "gapped path",
  provider_asserted_price: "provider price",
  unit_request_stated: "unit stated",
  unit_unstated: "unit unstated",
  subject_request_resolved: "tap resolved",
  subject_operator_attested: "operator-attested",
  coin_metadata_observed: "metadata observed",
  market_cap_from_usd_market_cap: "cap: usd_market_cap",
  market_cap_fields_disagree: "2 caps differ",
  schema_unpromoted: "schema unpromoted",
};

/**
 * The live microstructure instruments this page will carry, each slot honest about whether a
 * live derivation exists yet. The corpus behind them is docs/microstructure/trades_quotes_prices
 * (venue floor & clip, signature volatility, flow decomposition, tier-latency workability); the
 * venue slot is measured on request through the core's venue-readout route, and the rest state
 * their absence rather than a number — a slot that fabricated one would poison the whole page.
 */
const INSTRUMENT_SLOTS: Array<{ name: string; why: string }> = [
  {
    name: "Signature volatility",
    why: "The corpus instrument exists (signature plots by price kind and lag); no live derivation over the retained 1-second path is mounted yet. Absence, not zero.",
  },
  {
    name: "Flow decomposition",
    why: "Signed-flow persistence and splitting-versus-herding live in the corpus over retained trade tapes; trades are retained for hot coins but no live decomposition reaches a scene yet.",
  },
  {
    name: "Tier-latency workability",
    why: "The workability census runs offline over the seam corpus; no live tier/latency verdict is computed for this coin. This slot states that instead of guessing.",
  },
];

export const CoinWorkbench = memo(function CoinWorkbench({
  candidate,
  episode,
  socialEvents,
  onAnnotate,
  onHold,
  onOpenJournal,
  held = false,
  venueAnswer = null,
}: {
  candidate: Candidate;
  episode: Episode | undefined;
  socialEvents: SocialEvent[];
  onAnnotate(anchor: ChartAnchor): void;
  /** The same one-keystroke hold the `;` key commits, offered where she is already looking. */
  onHold?(): void;
  /** Moves focus to the journal composer; words land against this scene, in her own words. */
  onOpenJournal?(): void;
  /** Whether this session already holds this coin, so the button states it instead of re-arming. */
  held?: boolean;
  /**
   * The venue-and-clip answer for THIS coin: measured, a stated absence, or null when this
   * cockpit has no venue source attached at all. Rendered by the shared block the held rail
   * uses, so the venue truth cannot fork between surfaces.
   */
  venueAnswer?: VenueReadoutAnswer | null;
}) {
  const visibleSocial = socialEvents.filter((event) => event.candidateId === candidate.id);
  const mcapDisagreement = marketCapDisagreementNote(candidate);

  return (
    <section className="workbench" aria-labelledby="coin-title">
      <header className="coin-header panel">
        <div className="coin-identity">
          <span className="coin-mark" aria-hidden="true">
            {(candidate.symbol ?? candidate.mint).slice(0, 2)}
          </span>
          <div>
            <p className="eyebrow">Selected observation</p>
            <h1 id="coin-title">
              {candidateSymbol(candidate.symbol, candidate.mint)} <span>{candidateName(candidate.name)}</span>
            </h1>
            <p className="mint" title={candidate.mint}>{candidate.mint}</p>
            {candidate.symbol !== null && (
              <p className="identity-provenance">Ticker and name: {fieldLineage(candidate, "symbol")}</p>
            )}
          </div>
        </div>
        <div className="coin-header-edge">
          {/*
            The acts, where she is already looking: the same one-keystroke hold and the same
            journal composer the rails carry — no new act kinds, no new wire, just reach.
          */}
          {(onHold || onOpenJournal) && (
            <div className="coin-actions" role="group" aria-label="Acts on this coin">
              {onHold && (
                <button type="button" className="secondary-action" onClick={onHold} aria-keyshortcuts=";">
                  <Anchor aria-hidden="true" /> {held ? "Held — hold again" : "Hold"} <kbd>;</kbd>
                </button>
              )}
              {onOpenJournal && (
                <button type="button" className="secondary-action" onClick={onOpenJournal}>
                  <NotebookPen aria-hidden="true" /> Journal
                </button>
              )}
            </div>
          )}
          <div className="coin-tags" aria-label="Coin tags">
            <span className={`lifecycle lifecycle-${candidate.lifecycle}`}>
              <Radio aria-hidden="true" size={14} />
              {sentenceCase(candidate.lifecycle)}
            </span>
            {/* Compact faces; the wire tag itself (and, for the cap disagreement, the note
                naming both figures) stays verbatim on the chip's hover. */}
            {candidate.tags.map((tag) => (
              <span
                key={tag}
                className="tag"
                title={tag === "market_cap_fields_disagree" ? (mcapDisagreement ?? tag) : tag}
              >
                {TAG_FACE[tag] ?? tag}
              </span>
            ))}
          </div>
        </div>
      </header>

      {/*
        The provenance drawer: every sentence the card faces no longer carry, verbatim and
        expandable where she is already looking. The derivation-authored attention paragraph
        and social sentence land here in full, followed by each evidence row's own note with
        its class, status, source, and knowledge clock. Collapsed by default: the face stays
        scannable, the words stay one act away, and nothing is deleted.
      */}
      <details className="panel coin-provenance" data-testid="coin-provenance">
        <summary>Provenance — what this view claims, verbatim</summary>
        <p data-testid="provenance-attention">{candidate.attentionReason}</p>
        <p data-testid="provenance-social">{candidate.socialSummary}</p>
        <ul aria-label="Evidence rows in this view">
          {candidate.evidence.map((item) => (
            <li key={item.id}>
              <span className="provenance-line">
                <strong>{item.field}</strong> · {sentenceCase(item.evidenceClass)} ({item.status}) ·{" "}
                {item.sourceId} · observed {instantOrAbsent(item.observedAt)} · known {clock(item.knownAt)}Z
              </span>
              <p>{item.note}</p>
            </li>
          ))}
        </ul>
      </details>

      <div className="metric-grid" aria-label="Observed market values">
        {/* An absent figure is a dash with its absence stated in the line below — never the
            word-shaped value "Not observed" standing where a number would, and never a zero. */}
        <article className="metric-card">
          <span>Observed price</span>
          <strong>{candidate.metrics.priceSol === null ? "—" : priceSol(candidate.metrics.priceSol)}</strong>
          <small>{candidate.metrics.priceSol === null ? "No price was observed in this view" : fieldLineage(candidate, "metrics.priceSol")}</small>
        </article>
        <article className="metric-card">
          <span>
            Market cap
            {mcapDisagreement !== null && (
              <span className="board-chip chip-warn" title={mcapDisagreement}>
                2 caps differ
              </span>
            )}
          </span>
          <strong>{candidate.metrics.marketCapUsd === null ? "—" : compactUsd(candidate.metrics.marketCapUsd)}</strong>
          <small>{candidate.metrics.marketCapUsd === null ? "No market cap was observed in this view" : fieldLineage(candidate, "metrics.marketCapUsd")}</small>
        </article>
        <article className="metric-card">
          <span>5-minute move</span>
          <strong>{candidate.metrics.change5mBps === null ? "—" : basisPoints(candidate.metrics.change5mBps)}</strong>
          <small>{candidate.metrics.change5mBps === null
            ? `${sentenceCase(candidate.metrics.activity)} tape`
            : fieldLineage(candidate, "metrics.change5mBps")}</small>
        </article>
        <article className="metric-card quote-card">
          <span>Observed exit value</span>
          <strong>{candidate.metrics.executableExitSol === null ? "—" : sol(candidate.metrics.executableExitSol, 5)}</strong>
          <small>{candidate.metrics.executableExitSol === null
            ? "No observed inventory exit"
            : candidate.metrics.quoteSizeSol === null
              ? "This view carries no quote size for that exit"
              : `at the ${sol(candidate.metrics.quoteSizeSol, 2)} quote size this view carries`}</small>
        </article>
      </div>

      {episode?.state === "watching_flat" && (
        <div className="state-banner state-flat" role="note">
          <Eye aria-hidden="true" />
          <span>
            <strong>Watching while flat</strong>
            There is no current exposure. A later re-entry remains part of this episode, but no action is armed here.
          </span>
        </div>
      )}

      <section className="panel chart-panel" aria-labelledby="chart-title">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Observed history</p>
            <h2 id="chart-title">Chart and knowability</h2>
          </div>
          <span className="read-only-badge"><Eye aria-hidden="true" size={16} /> Read-only</span>
        </div>
        <Suspense fallback={<div className="chart-loading" role="status">Loading the accessible chart view…</div>}>
          <MarketChart candidate={candidate} onAnnotate={onAnnotate} />
        </Suspense>
        {candidate.candles.length === 0 && (
          <p
            className="chart-summary hot-tap-note"
            title={"Focusing in on a coin records the automatic inspect assertion (an ordinary "
              + "evidence command); when a keeper follows this catalog it starts tapping this "
              + "mint's 1-second candles within a couple of minutes. Scenes are immutable, so "
              + "bars can only arrive in a NEWER scene — the advance pill is where they show up. "
              + "This scene's bytes never change."}
          >
            Focus-in asked for this coin&rsquo;s 1-second candles; bars arrive only in a newer
            scene — watch the advance pill.
          </p>
        )}
      </section>

      <section className="panel social-panel" aria-labelledby="social-title">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Callouts &amp; social</p>
            <h2 id="social-title">Events in this lens</h2>
          </div>
          <span
            className="count-badge"
            title={"Social evidence is incomplete by construction; coverage gaps stay explicit. "
              + "Absent here does not mean nobody called it."}
          >
            {visibleSocial.length} events
          </span>
        </div>
        {visibleSocial.length === 0 ? (
          <div className="empty-state">
            <strong>No observed events for this coin.</strong>
            <span
              title={"The keeper retains callout bodies for hot coins (callout_top and the "
                + "community route), but no derivation renders them into a served scene yet, and "
                + "this lens fabricates nothing. Absent here does not mean nobody called it."}
            >
              Retained callouts are not yet derived into scenes.
            </span>
          </div>
        ) : (
          <ol className="timeline">
            {visibleSocial.map((event) => (
              <li key={event.id} className={event.kind === "gap" ? "timeline-gap" : undefined}>
                <span className="timeline-icon" aria-hidden="true">
                  {event.kind === "gap" ? <AlertTriangle /> : event.kind === "callout" ? <Megaphone /> : <CircleDot />}
                </span>
                <div>
                  <span className="timeline-meta">
                    <strong>{sentenceCase(event.kind)}</strong>
                    {event.author && <span>@{event.author}</span>}
                    <span><Clock3 aria-hidden="true" size={13} /> {clock(event.eventAt)}Z</span>
                  </span>
                  <p>{event.text}</p>
                  <small>Known {clock(event.knownAt)}Z · {sentenceCase(event.evidence.evidenceClass)}</small>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      {/*
        Where the live microstructure analysis lives on this page. One slot is real today —
        the venue readout, measured from retained venue bytes when the core mounts a capture —
        and the others are the corpus instruments this page is built to receive, each stating
        plainly that no live derivation feeds it yet. An empty slot that stated a number
        instead would be the one dishonesty this cockpit cannot afford.
      */}
      <section className="panel micro-panel" aria-labelledby="micro-title">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Microstructure</p>
            <h2 id="micro-title">Venue &amp; instruments</h2>
          </div>
        </div>
        <VenueAndClip answer={venueAnswer} headingLevel={3} />
        <ul className="micro-slots" aria-label="Live instrument slots">
          {INSTRUMENT_SLOTS.map((slot) => (
            <li key={slot.name} className="micro-slot" title={slot.why}>
              <span className="micro-slot-name">{slot.name}</span>
              <span className="board-chip chip-absent">not computed live</span>
            </li>
          ))}
        </ul>
      </section>
    </section>
  );
});
