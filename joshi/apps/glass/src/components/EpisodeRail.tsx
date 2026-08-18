import { Eye, Layers3, PauseCircle, Target } from "lucide-react";

import type { Candidate, Episode } from "../contract/v1";
import { sentenceCase, sol } from "../format";

export function EpisodeRail({
  episodes,
  candidates,
  selectedId,
  onFocus,
  onRecordGesture,
}: {
  episodes: Episode[];
  candidates: Candidate[];
  selectedId: string;
  onFocus(candidateId: string): void;
  onRecordGesture(candidateId: string, episodeId: string, gestureLabel: string): void;
}) {
  return (
    <aside className="panel episode-rail" aria-labelledby="episodes-title">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Persistent memory</p>
          <h2 id="episodes-title">Exposure &amp; episodes</h2>
        </div>
        <span className="read-only-badge"><Eye aria-hidden="true" size={15} /> Observe</span>
      </div>
      <p className="rail-intro">Exits do not erase the story. Flat watches stay visible beside retained runners.</p>
      <div className="episode-list">
        {episodes.map((episode) => {
          const candidate = candidates.find((item) => item.id === episode.candidateId);
          if (!candidate) return null;
          const flat = episode.state === "watching_flat";
          return (
            <article
              className="episode-card"
              data-selected={selectedId === candidate.id}
              key={episode.id}
            >
              <header>
                <span className={`episode-state state-${flat ? "flat" : "open"}`}>
                  {flat ? <PauseCircle aria-hidden="true" /> : <Layers3 aria-hidden="true" />}
                  {flat ? "Flat · watching" : sentenceCase(episode.state)}
                </span>
                <strong>${candidate.symbol}</strong>
              </header>
              <span className="episode-disposition">{episode.disposition}</span>
              <p>{episode.latestNote}</p>
              <dl className="episode-accounting">
                <div><dt>Current exposure</dt><dd>{sol(episode.accounting.currentExposureSol, 5)}</dd></div>
                <div><dt>Realized net</dt><dd>{sol(episode.accounting.realizedNetSol, 5)}</dd></div>
                <div><dt>Observed liquidation</dt><dd>{sol(episode.accounting.executableLiquidationSol, 5)}</dd></div>
                <div><dt>Inventory intervals</dt><dd>{episode.clips.length}</dd></div>
              </dl>
              <div className="next-attention">
                <Target aria-hidden="true" size={16} />
                <span><strong>Next attention</strong>{episode.nextAttention}</span>
              </div>
              <button type="button" className="focus-button" onClick={() => onFocus(candidate.id)}>
                Focus ${candidate.symbol}
              </button>
              {selectedId === candidate.id && (
                <details className="episode-recording-actions">
                  <summary>Record episode meaning</summary>
                  <div>
                    <button type="button" onClick={() => onRecordGesture(candidate.id, episode.id, "partial recognition observed outside Joshi")}>Record partial recognition</button>
                    <button type="button" onClick={() => onRecordGesture(candidate.id, episode.id, "remainder treated as runner")}>Record runner meaning</button>
                    <button type="button" onClick={() => onRecordGesture(candidate.id, episode.id, "continue watching while flat")}>Record flat-watch continuation</button>
                    <button type="button" onClick={() => onRecordGesture(candidate.id, episode.id, "re-entry observed outside Joshi")}>Record external re-entry</button>
                  </div>
                  <small>These are operator claims, not fills or client-side PnL facts.</small>
                </details>
              )}
            </article>
          );
        })}
      </div>
    </aside>
  );
}
