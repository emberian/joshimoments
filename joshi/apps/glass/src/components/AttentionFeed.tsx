import { memo, useEffect, useMemo, useRef } from "react";
// This feed reports three attention channels the shell accumulates per scene: a row receiving
// focus (`onFocusCandidate`), a row's pixels actually intersecting the visible scroll
// rectangle (`onScrollViewportChange` — computed from the virtualizer's own scroll geometry,
// so overscan-mounted rows that were never presented do NOT count), and the pointer entering
// a row (`onPointerCandidate`). The visible-rectangle channel was removed once on the belief
// that the operator was screen-reader-only and pixels were not reading; Ember corrected that
// directly — she is primarily visual — so it is restored. `operator/attention.ts` states
// exactly what each channel claims and refuses to claim.
import { useVirtualizer } from "@tanstack/react-virtual";
import { Activity, Bookmark, RefreshCw, Radio, Users } from "lucide-react";

import type { Candidate } from "../contract/v1";
import { basisPoints, candidateName, candidateSymbol, compactUsd, duration, sentenceCase, signedTone } from "../format";
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

export const AttentionFeed = memo(function AttentionFeed({
  candidates,
  selectedId,
  onSelect,
  onFocusCandidate,
  onScrollViewportChange,
  onPointerCandidate,
  board,
  onBoardChange,
  density,
  focusRequest,
  orderUpdatePending = false,
  pendingNewCount = 0,
  onAcceptOrderUpdate,
}: {
  candidates: Candidate[];
  selectedId: string;
  onSelect(id: string): void;
  /**
   * Keeps "what she is on" and "what a keystroke acts on" the same thing.
   *
   * Without it the app only learns about a candidate when the card is activated, so a row reached
   * with Tab or with a screen reader's own navigation is focused and read aloud while the hold
   * key still acts on some other coin. That is a silent wrong-coin bug, and holding the wrong
   * coin is worse than not holding one.
   */
  onFocusCandidate?(id: string): void;
  /**
   * Candidates whose pixels currently intersect the visible scroll rectangle — actual
   * visibility from the virtualizer's scroll geometry, never overscan mounting. Fired on every
   * change; the shell unions it into the scene's seen set.
   */
  onScrollViewportChange?(candidateIds: string[]): void;
  /**
   * The pointer entered this row. Ember points deliberately as an attention marker, so this
   * feeds both the seen set and its own `pointed` choice set. It never moves selection: hover
   * hijacking the act target would reintroduce the silent wrong-coin bug that focus-follows
   * selection exists to prevent.
   */
  onPointerCandidate?(id: string): void;
  board: BoardFilter;
  onBoardChange(board: BoardFilter): void;
  density: Density;
  focusRequest: number;
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

  // Actual visibility, not mounting: a virtual row is in the viewport only when its extent
  // overlaps the scroll element's REAL rectangle, read from the DOM at effect time. The
  // virtualizer's scrollOffset is observed from scroll events and is honest (and re-fires this
  // effect as she scrolls), but its scrollRect is deliberately not consulted — before
  // measurement it is the `initialRect` estimate, and asserting "she could see this row" from
  // an estimate would fabricate the set (in jsdom, where no screen exists, clientHeight is 0
  // and this channel honestly reports nothing at all).
  const scrollOffset = rowVirtualizer.scrollOffset ?? 0;
  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const viewportHeight = element.clientHeight;
    if (viewportHeight === 0) return;
    const visibleIds = virtualRows
      .filter((row) => row.end > scrollOffset && row.start < scrollOffset + viewportHeight)
      .map((row) => sorted[row.index]?.id)
      .filter((id): id is string => id !== undefined);
    if (visibleIds.length === 0) return;
    onScrollViewportChange?.(visibleIds);
  }, [onScrollViewportChange, scrollOffset, sorted, virtualRows]);

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
                    aria-keyshortcuts=";"
                    onFocus={() => onFocusCandidate?.(candidate.id)}
                    // Both enter flavors: pointerenter is the real channel in browsers, while
                    // mouseenter is what environments without PointerEvent (jsdom) deliver.
                    // The shell's note is idempotent, so a browser firing both records once.
                    onPointerEnter={() => onPointerCandidate?.(candidate.id)}
                    onMouseEnter={() => onPointerCandidate?.(candidate.id)}
                    onClick={() => onSelect(candidate.id)}
                  >
                    <span
                      className="candidate-rank"
                      data-absent={rank === null}
                      aria-label={rank === null ? "This view states no rank for this candidate" : `Rank ${rank}`}
                    >
                      {rank ?? "—"}
                    </span>
                    <span className="candidate-main">
                      <span className="candidate-title-row">
                        <strong>{candidateSymbol(candidate.symbol, candidate.mint)}</strong>
                        <span>{candidateName(candidate.name)}</span>
                        {candidate.watched === true && (
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
});
