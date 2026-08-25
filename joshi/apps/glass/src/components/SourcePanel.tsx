import { AlertTriangle, CheckCircle2, Database, Eye, RadioTower } from "lucide-react";

import type { AsOfVector, Candidate, ReplayMode, SourceHealth } from "../contract/v1";
import { candidateSymbol, clock, instantOrAbsent, sentenceCase } from "../format";

// Only `fresh` is a healthy delivery. `fixture` is a source whose bytes were authored rather
// than observed, and it must never render with the same mark as a live source.
function HealthIcon({ status }: { status: SourceHealth["status"] }) {
  if (status === "fresh") return <CheckCircle2 aria-hidden="true" />;
  return <AlertTriangle aria-hidden="true" />;
}

export function SourcePanel({
  sources,
  candidate,
  expanded,
  onExpandedChange,
  asOf,
  snapshotDigest,
  mode,
}: {
  sources: SourceHealth[];
  candidate: Candidate;
  expanded: boolean;
  onExpandedChange(expanded: boolean): void;
  asOf: AsOfVector;
  snapshotDigest: string;
  mode: ReplayMode;
}) {
  const gapCount = sources.filter((source) => source.status === "gap" || source.status === "degraded").length;
  const fixtureCount = sources.filter((source) => source.status === "fixture").length;
  const freshCount = sources.filter((source) => source.status === "fresh").length;
  return (
    <section className="panel source-panel" aria-labelledby="source-title">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Coverage &amp; lineage</p>
          <h2 id="source-title">Source health</h2>
        </div>
        <button
          type="button"
          className="disclosure-button"
          aria-expanded={expanded}
          aria-controls="provenance-details"
          onClick={() => onExpandedChange(!expanded)}
        >
          <Database aria-hidden="true" size={17} />
          {expanded ? "Hide provenance" : "Show provenance"}
          <kbd>P</kbd>
        </button>
      </div>
      <div className={`health-summary ${freshCount < sources.length ? "health-warning" : "health-good"}`} role="status">
        <RadioTower aria-hidden="true" />
        <span>
          <strong>{freshCount} of {sources.length} source{sources.length === 1 ? "" : "s"} report fresh delivery</strong>
          {gapCount} explicit coverage gap{gapCount === 1 ? "" : "s"}.
          {fixtureCount > 0 && <strong className="fixture-warning">{fixtureCount} of these source{fixtureCount === 1 ? " is" : "s are"} fixture-backed: its bytes were authored, not observed.</strong>}
        </span>
      </div>
      <dl className="asof-grid" aria-label="Snapshot as-of vector summary">
        <div><dt>Mode</dt><dd>{sentenceCase(mode)}</dd></div>
        <div><dt>Catalog commit</dt><dd>{asOf.catalogCommit}</dd></div>
        <div><dt>Rendered</dt><dd>{clock(asOf.renderedAt)}Z</dd></div>
        <div title={snapshotDigest}><dt>View digest</dt><dd>{snapshotDigest.slice(0, 18)}…</dd></div>
      </dl>
      <ul className="source-list">
        {sources.map((source) => {
          const watermark = asOf.sources.find((item) => item.sourceId === source.id);
          return <li key={source.id} data-status={source.status}>
            <HealthIcon status={source.status} />
            <span><strong>{source.label}</strong><small>{sentenceCase(source.status)} · delivered commit {watermark?.deliveredThrough ?? "unobserved"}</small></span>
          </li>;
        })}
      </ul>

      {expanded && (
        <div id="provenance-details" className="provenance-details">
          <h3>{candidateSymbol(candidate.symbol, candidate.mint)} field provenance</h3>
          <p>Separate clocks and evidence classes are preserved. Equal numbers do not imply equal truth conditions.</p>
          <div className="evidence-list">
            {candidate.evidence.map((item) => (
              <article key={item.id}>
                <header>
                  <span className={`evidence-class evidence-${item.evidenceClass}`}>{sentenceCase(item.evidenceClass)}</span>
                  <strong>{item.field}</strong>
                </header>
                <dl>
                  <div><dt>Source</dt><dd>{item.sourceId}</dd></div>
                  <div><dt>Observed</dt><dd>{instantOrAbsent(item.observedAt)}</dd></div>
                  <div><dt>Ingested</dt><dd>{clock(item.ingestedAt)}Z</dd></div>
                  <div><dt>Known</dt><dd>{clock(item.knownAt)}Z</dd></div>
                </dl>
                <p><Eye aria-hidden="true" size={14} /> {item.note}</p>
              </article>
            ))}
          </div>
          <details className="source-details">
            <summary>Read full source coverage notes</summary>
            {sources.map((source) => (
              <article key={source.id}>
                <h4>{source.label}</h4>
                <p>{source.coverage}</p>
                <small>{source.note}</small>
              </article>
            ))}
          </details>
          <details className="source-details">
            <summary>Read the full as-of vector</summary>
            <article>
              <h4>Chain watermark</h4>
              <p>{asOf.chain ? `${asOf.chain.cluster} · slot ${asOf.chain.slot} · ${asOf.chain.finality}` : "No chain watermark"}</p>
            </article>
            {asOf.sources.map((source) => (
              <article key={source.sourceId}>
                <h4>{source.sourceId}</h4>
                <p>Delivered through commit {source.deliveredThrough}; {source.cursors.length} scoped cursor{source.cursors.length === 1 ? "" : "s"}; received {instantOrAbsent(source.receivedThrough)}.</p>
                {source.cursors.map((cursor) => (
                  <small className="cursor-line" key={`${cursor.family}:${cursor.subject ?? ""}:${cursor.cursorKind}`}>
                    {cursor.family} / {cursor.subject ?? "all subjects (null)"} / {cursor.cursorKind}: {cursor.value} through {cursor.advancedThrough}
                  </small>
                ))}
              </article>
            ))}
            {asOf.projections.map((projection) => (
              <article key={projection.name}>
                <h4>{projection.name} projection · v{projection.version}</h4>
                <p className="digest-line">{projection.stateDigest}</p>
              </article>
            ))}
          </details>
        </div>
      )}
    </section>
  );
}
