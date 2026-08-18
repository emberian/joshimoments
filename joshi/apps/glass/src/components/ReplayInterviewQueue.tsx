import { EyeOff, History, MessageSquareText } from "lucide-react";

import type { Candidate, Episode, ReplayMode } from "../contract/v1";
import type { CapturePreset } from "./OperatorCapture";
import type { JournalEntry } from "../operator/useOperatorJournal";

export function ReplayInterviewQueue({
  episodes,
  candidates,
  mode,
  onCapture,
  sceneEntries,
}: {
  episodes: Episode[];
  candidates: Candidate[];
  mode: ReplayMode;
  onCapture(preset: CapturePreset): void;
  sceneEntries: JournalEntry[];
}) {
  return (
    <section className="panel replay-queue" aria-labelledby="replay-queue-title">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Fourth persistent context</p>
          <h2 id="replay-queue-title">Replay &amp; interview queue</h2>
        </div>
        <span className="count-badge">{episodes.length} episode{episodes.length === 1 ? "" : "s"}</span>
      </div>
      <p className="rail-intro">Outcome-hidden reconstruction and outcome-aware reflection are separate records. Neither rewrites the immediate scene.</p>
      <ul className="replay-queue-list">
        {episodes.length === 0 && <li className="empty-state"><strong>No episode in this publication.</strong><span>No-trade attention can still be marked in the selected scene.</span></li>}
        {episodes.map((episode) => {
          const candidate = candidates.find((item) => item.id === episode.candidateId);
          if (!candidate) return null;
          const sourceCommandIds = sceneEntries.filter((entry) => {
            if (entry.status !== "committed" || entry.command.subject.key !== candidate.id) return false;
            const payload = entry.command.payload as { episodeRef?: { episodeId?: string } | null };
            return payload.episodeRef?.episodeId === episode.id;
          }).map((entry) => entry.command.commandId).sort();
          const linked = sourceCommandIds.length > 0;
          return (
            <li key={episode.id}>
              <div>
                <strong>${candidate.symbol}</strong>
                <span>{episode.state.replaceAll("_", " ")} · changed {episode.lastChangedAt}</span>
              </div>
              <div className="replay-queue-actions">
                <button type="button" disabled={mode === "retrospective" || !linked} onClick={() => onCapture({
                  type: "interview",
                  episodeId: episode.id,
                  sourceCommandIds,
                  defaultOutcomeVisibility: "hidden",
                })}>
                  <EyeOff aria-hidden="true" /> {!linked ? "Link an episode act first" : mode === "retrospective" ? "Return to witnessed lens to reconstruct" : "Reconstruct outcome-hidden"}
                </button>
                <button type="button" disabled={mode !== "retrospective" || !linked} onClick={() => onCapture({
                  type: "interview",
                  episodeId: episode.id,
                  sourceCommandIds,
                  defaultOutcomeVisibility: "aware",
                })}>
                  <History aria-hidden="true" /> {!linked ? "Link an episode act first" : mode === "retrospective" ? "Record retrospective reflection" : "Load later lens to reflect"}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
      <p className="operator-boundary"><MessageSquareText aria-hidden="true" /> An interview is an operator report with explicit outcome visibility and linked source acts, not recovered contemporaneous truth. Client timing/link labels remain unqualified until core derives them from durable commit order and episode/scene closure.</p>
    </section>
  );
}
