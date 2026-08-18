import { useEffect, useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Activity, Bookmark, RefreshCw, Radio, Users } from "lucide-react";

import type { Candidate } from "../contract/v1";
import { basisPoints, compactUsd, duration, sentenceCase, signedTone } from "../format";
import type { Density } from "../App";

export type BoardFilter = "all" | Candidate["board"];

const boards: Array<{ id: BoardFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "new", label: "New" },
  { id: "trending", label: "Trending" },
  { id: "live", label: "Live" },
  { id: "callouts", label: "Callouts" },
  { id: "watch", label: "Watch" },
];

export function AttentionFeed({
  candidates,
  selectedId,
  onSelect,
  board,
  onBoardChange,
  density,
  focusRequest,
  onViewportChange,
  orderUpdatePending = false,
  pendingNewCount = 0,
  onAcceptOrderUpdate,
}: {
  candidates: Candidate[];
  selectedId: string;
  onSelect(id: string): void;
  board: BoardFilter;
  onBoardChange(board: BoardFilter): void;
  density: Density;
  focusRequest: number;
  onViewportChange(candidateIds: string[]): void;
  orderUpdatePending?: boolean;
  pendingNewCount?: number;
  onAcceptOrderUpdate?(): void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // The parent has already frozen the accepted display order. Re-sorting here would let a
  // newer rank move a card beneath the pointer or keyboard focus before explicit acceptance.
  const sorted = useMemo(() => candidates, [candidates]);
  const rowVirtualizer = useVirtualizer({
    count: sorted.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => (density === "comfortable" ? 156 : 126),
    overscan: 5,
    initialRect: { width: 440, height: 640 },
    getItemKey: (index) => sorted[index]?.id ?? index,
  });
  const virtualRows = rowVirtualizer.getVirtualItems();
  const scrollOffset = rowVirtualizer.scrollOffset ?? 0;
  const viewportHeight = rowVirtualizer.scrollRect?.height ?? 0;
  const viewportIds = virtualRows
    .filter((row) => viewportHeight === 0 || (row.end > scrollOffset && row.start < scrollOffset + viewportHeight))
    .map((row) => sorted[row.index]?.id)
    .filter((id): id is string => id !== undefined);
  const viewportKey = viewportIds.join("\0");

  useEffect(() => {
    onViewportChange(viewportIds);
  }, [onViewportChange, viewportKey]);

  useEffect(() => {
    const index = sorted.findIndex((candidate) => candidate.id === selectedId);
    if (index < 0) return;
    const frame = requestAnimationFrame(() => rowVirtualizer.scrollToIndex(index, { align: "auto" }));
    return () => cancelAnimationFrame(frame);
  }, [rowVirtualizer, selectedId, sorted]);

  useEffect(() => {
    if (focusRequest === 0) return;
    const index = sorted.findIndex((candidate) => candidate.id === selectedId);
    if (index < 0) return;
    let focusFrame: number | undefined;
    const scrollFrame = requestAnimationFrame(() => {
      rowVirtualizer.scrollToIndex(index, { align: "center" });
      focusFrame = requestAnimationFrame(() => {
        scrollRef.current
          ?.querySelector<HTMLButtonElement>(`[data-candidate-id='${selectedId}']`)
          ?.focus({ preventScroll: true });
      });
    });
    return () => {
      cancelAnimationFrame(scrollFrame);
      if (focusFrame !== undefined) cancelAnimationFrame(focusFrame);
    };
  }, [focusRequest, rowVirtualizer, selectedId, sorted]);

  return (
    <section className="panel attention-panel" aria-labelledby="attention-title">
      <div className="panel-header attention-header">
        <div>
          <p className="eyebrow">Broad surface</p>
          <h2 id="attention-title">Attention feed</h2>
        </div>
        <output className="count-badge" aria-live="polite">
          {sorted.length} visible
        </output>
      </div>

      <div className="board-tabs" role="toolbar" aria-label="Filter attention feed">
        {boards.map((item) => (
          <button
            type="button"
            key={item.id}
            className="filter-button"
            aria-pressed={board === item.id}
            onClick={() => onBoardChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {orderUpdatePending && onAcceptOrderUpdate && (
        <div className="pending-order" role="status">
          <span><strong>Updated order available</strong>{pendingNewCount > 0 ? ` · ${pendingNewCount} new` : ""}. Cards stay fixed until you accept it.</span>
          <button type="button" onClick={onAcceptOrderUpdate}><RefreshCw aria-hidden="true" /> Accept updated order</button>
        </div>
      )}

      <div
        ref={scrollRef}
        className="feed-scroll"
        tabIndex={0}
        aria-label="Scrollable candidate list. Use J and K or arrow keys to move."
      >
        {sorted.length === 0 ? (
          <div className="empty-state" role="status">
            <strong>No candidates match this view.</strong>
            <span>Change the board or clear search. This is not a zero-activity claim.</span>
          </div>
        ) : (
          <ul
            className="virtual-list"
            aria-label="Market candidates"
            style={{ height: `${rowVirtualizer.getTotalSize()}px` }}
          >
            {virtualRows.map((row) => {
              const candidate = sorted[row.index];
              if (!candidate) return null;
              const rank = candidate.rank;
              return (
                <li
                  key={candidate.id}
                  ref={rowVirtualizer.measureElement}
                  data-index={row.index}
                  className="virtual-row"
                  style={{ transform: `translateY(${row.start}px)` }}
                  aria-setsize={sorted.length}
                  aria-posinset={row.index + 1}
                >
                  <button
                    type="button"
                    className="candidate-card"
                    data-selected={selectedId === candidate.id}
                    data-candidate-id={candidate.id}
                    aria-current={selectedId === candidate.id ? "true" : undefined}
                    onClick={() => onSelect(candidate.id)}
                  >
                    <span className="candidate-rank" aria-label={`Rank ${rank}`}>
                      {rank}
                    </span>
                    <span className="candidate-main">
                      <span className="candidate-title-row">
                        <strong>${candidate.symbol}</strong>
                        <span>{candidate.name}</span>
                        {candidate.watched && (
                          <span className="icon-label" title="Watched">
                            <Bookmark aria-hidden="true" size={15} />
                            <span className="sr-only">Watched</span>
                          </span>
                        )}
                      </span>
                      <span className="candidate-reason">{candidate.attentionReason}</span>
                      <span className="candidate-facts">
                        <span>{compactUsd(candidate.metrics.marketCapUsd)}</span>
                        <span className={`value-${signedTone(candidate.metrics.change5mBps)}`}>
                          {basisPoints(candidate.metrics.change5mBps)} · 5m
                        </span>
                        <span>{duration(candidate.metrics.ageSeconds)} old</span>
                      </span>
                      {density === "comfortable" && (
                        <span className="candidate-context">
                          <span>
                            <Activity aria-hidden="true" size={15} />
                            {sentenceCase(candidate.metrics.activity)}
                          </span>
                          <span>
                            <Users aria-hidden="true" size={15} />
                            {candidate.socialSummary}
                          </span>
                        </span>
                      )}
                    </span>
                    <span className="candidate-edge">
                      <span className={`lifecycle lifecycle-${candidate.lifecycle}`}>
                        {candidate.lifecycle === "bonding" && <Radio aria-hidden="true" size={14} />}
                        {sentenceCase(candidate.lifecycle)}
                      </span>
                      <span className="source-chip">{candidate.board}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
