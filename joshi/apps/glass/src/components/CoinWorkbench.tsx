import { lazy, memo, Suspense } from "react";
import { AlertTriangle, CircleDot, Clock3, Eye, Radio, WalletCards } from "lucide-react";

import type { Candidate, Episode, SocialEvent } from "../contract/v1";
import { basisPoints, clock, compactUsd, priceSol, sentenceCase, sol } from "../format";
import type { ChartAnchor } from "../operator/contract";

const MarketChart = lazy(() => import("./MarketChart").then((module) => ({ default: module.MarketChart })));

export const CoinWorkbench = memo(function CoinWorkbench({
  candidate,
  episode,
  socialEvents,
  onAnnotate,
}: {
  candidate: Candidate;
  episode: Episode | undefined;
  socialEvents: SocialEvent[];
  onAnnotate(anchor: ChartAnchor): void;
}) {
  const visibleSocial = socialEvents.filter((event) => event.candidateId === candidate.id);

  return (
    <section className="workbench" aria-labelledby="coin-title">
      <header className="coin-header panel">
        <div className="coin-identity">
          <span className="coin-mark" aria-hidden="true">
            {candidate.symbol.slice(0, 2)}
          </span>
          <div>
            <p className="eyebrow">Selected observation</p>
            <h1 id="coin-title">
              ${candidate.symbol} <span>{candidate.name}</span>
            </h1>
            <p className="mint" title={candidate.mint}>{candidate.mint}</p>
          </div>
        </div>
        <div className="coin-tags" aria-label="Coin tags">
          <span className={`lifecycle lifecycle-${candidate.lifecycle}`}>
            <Radio aria-hidden="true" size={14} />
            {sentenceCase(candidate.lifecycle)}
          </span>
          {candidate.tags.map((tag) => <span key={tag} className="tag">{tag}</span>)}
        </div>
      </header>

      <div className="metric-grid" aria-label="Observed market values">
        <article className="metric-card">
          <span>Observed price</span>
          <strong>{priceSol(candidate.metrics.priceSol)}</strong>
          <small>Derived observation, not a quote</small>
        </article>
        <article className="metric-card">
          <span>Market cap</span>
          <strong>{compactUsd(candidate.metrics.marketCapUsd)}</strong>
          <small>Fixture projection</small>
        </article>
        <article className="metric-card">
          <span>5-minute move</span>
          <strong>{basisPoints(candidate.metrics.change5mBps)}</strong>
          <small>{sentenceCase(candidate.metrics.activity)} tape</small>
        </article>
        <article className="metric-card quote-card">
          <span>Observed exit value</span>
          <strong>{sol(candidate.metrics.executableExitSol, 5)}</strong>
          <small>{candidate.metrics.executableExitSol ? `at ${sol(candidate.metrics.quoteSizeSol, 2)} fixture size` : "No observed inventory exit"}</small>
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
      </section>

      <section className="panel social-panel" aria-labelledby="social-title">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Social context</p>
            <h2 id="social-title">Events in this lens</h2>
          </div>
          <span className="count-badge">{visibleSocial.length} events</span>
        </div>
        {visibleSocial.length === 0 ? (
          <div className="empty-state">
            <strong>No observed events for this coin.</strong>
            <span>This is not a claim that conversation was absent.</span>
          </div>
        ) : (
          <ol className="timeline">
            {visibleSocial.map((event) => (
              <li key={event.id} className={event.kind === "gap" ? "timeline-gap" : undefined}>
                <span className="timeline-icon" aria-hidden="true">
                  {event.kind === "gap" ? <AlertTriangle /> : <CircleDot />}
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
        <p className="coverage-note"><WalletCards aria-hidden="true" size={16} /> Social evidence is incomplete by construction; coverage gaps stay explicit.</p>
      </section>
    </section>
  );
});
