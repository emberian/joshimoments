import { memo, useCallback, useEffect, useMemo, useRef, type KeyboardEvent as ReactKeyboardEvent } from "react";
// This feed reports three attention channels the shell accumulates per scene: the feed's active
// descendant reaching a row while the listbox holds focus (`onFocusCandidate` — the same
// "reading reached the row" claim that per-row DOM focus used to make, carried by
// `aria-activedescendant` now that the feed is a single tab stop), a row's pixels actually
// intersecting the visible scroll rectangle (`onScrollViewportChange` — computed from the
// virtualizer's own scroll geometry, so overscan-mounted rows that were never presented do NOT
// count), and the pointer entering a row (`onPointerCandidate`). The visible-rectangle channel
// was removed once on the belief that the operator was screen-reader-only and pixels were not
// reading; Ember corrected that directly — she is primarily visual — so it is restored.
// `operator/attention.ts` states exactly what each channel claims and refuses to claim.
import { defaultRangeExtractor, useVirtualizer, type Range } from "@tanstack/react-virtual";
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

/**
 * The DOM id `aria-activedescendant` names for a candidate's option row. Stable across scrolls
 * and re-renders because it is derived from the candidate's own id, never from a virtual index.
 */
export function candidateOptionDomId(candidateId: string): string {
  return `candidate-option-${candidateId}`;
}

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
   * with the keyboard or with a screen reader's own navigation is announced while the hold key
   * still acts on some other coin. That is a silent wrong-coin bug, and holding the wrong coin is
   * worse than not holding one. The feed is one tab stop (a listbox), so the observable reading
   * event is the active descendant reaching a row while the listbox holds focus — the exact claim
   * per-row DOM focus used to carry.
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
  const activeIndex = useMemo(
    () => sorted.findIndex((candidate) => candidate.id === selectedId),
    [selectedId, sorted],
  );
  const activeId = activeIndex >= 0 ? sorted[activeIndex]?.id : undefined;

  /**
   * Pin the active row into the mounted range. `aria-activedescendant` must never name an id
   * that is not in the DOM, and the virtualizer unmounts rows outside the measured window — so
   * the active option is kept mounted no matter where the scroll sits, rather than trying to
   * chase every scroll with a re-anchoring scroll of our own. A pinned off-window row is
   * position-absolute at its own virtual offset (invisible until scrolled to), and the
   * visible-rectangle channel still ignores it: mounted is not presented.
   */
  const rangeExtractor = useCallback((range: Range) => {
    const mounted = defaultRangeExtractor(range);
    if (activeIndex < 0 || mounted.includes(activeIndex)) return mounted;
    return [...mounted, activeIndex].sort((a, b) => a - b);
  }, [activeIndex]);

  const rowVirtualizer = useVirtualizer({
    count: sorted.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => (density === "comfortable" ? 156 : 126),
    overscan: 5,
    initialRect: { width: 440, height: 640 },
    getItemKey: (index) => sorted[index]?.id ?? index,
    rangeExtractor,
  });
  const virtualRows = rowVirtualizer.getVirtualItems();
  // The invariant, checked against what is actually mounted rather than assumed from the pin:
  // the listbox names an active descendant only while that row's element really exists.
  const activeRowMounted = activeId !== undefined
    && virtualRows.some((row) => sorted[row.index]?.id === activeId);

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

  /**
   * A reader announces the active descendant when it changes under a focused listbox — that is
   * the moment reading reaches the row, so it feeds the same channel per-row focus used to.
   * With focus elsewhere, a changed active descendant announces nothing and claims nothing
   * (J/K movement is attended separately by the selection gesture itself).
   */
  useEffect(() => {
    if (activeId === undefined) return;
    const element = scrollRef.current;
    if (!element || document.activeElement !== element) return;
    onFocusCandidate?.(activeId);
  }, [activeId, onFocusCandidate]);

  useEffect(() => {
    if (focusRequest === 0) return;
    const index = sorted.findIndex((candidate) => candidate.id === selectedId);
    if (index < 0) return;
    let focusFrame: number | undefined;
    const scrollFrame = requestAnimationFrame(() => {
      rowVirtualizer.scrollToIndex(index, { align: "center" });
      focusFrame = requestAnimationFrame(() => {
        scrollRef.current?.focus({ preventScroll: true });
      });
    });
    return () => {
      cancelAnimationFrame(scrollFrame);
      if (focusFrame !== undefined) cancelAnimationFrame(focusFrame);
    };
  }, [focusRequest, rowVirtualizer, selectedId, sorted]);

  /**
   * Focus arriving by pointer press lands on the row being clicked, and the click itself is the
   * honest attention event for that row — announcing the *previous* active descendant as "read"
   * would claim a row her click never touched. Keyboard focus (Tab into the feed) has no such
   * gesture, so there the active row really is what gets announced, and is attended.
   */
  const pointerFocusRef = useRef(false);
  const markPointerFocus = useCallback(() => {
    pointerFocusRef.current = true;
  }, []);
  const onListboxFocus = useCallback(() => {
    if (pointerFocusRef.current) {
      pointerFocusRef.current = false;
      return;
    }
    if (activeId !== undefined) onFocusCandidate?.(activeId);
  }, [activeId, onFocusCandidate]);

  const onListboxKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (sorted.length === 0) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const active = activeIndex >= 0 ? sorted[activeIndex] : undefined;
      if (active) onSelect(active.id);
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const target = event.key === "Home" ? sorted[0] : sorted[sorted.length - 1];
      if (target) onSelect(target.id);
    }
    // J/K and the arrow keys reach the shell's global handler by bubbling; it moves the
    // selection (and therefore the active descendant) and prevents the container scroll.
  }, [activeIndex, onSelect, sorted]);

  const boardRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const moveBoard = useCallback((fromIndex: number, direction: 1 | -1) => {
    const nextIndex = (fromIndex + direction + boards.length) % boards.length;
    const next = boards[nextIndex];
    if (!next) return;
    onBoardChange(next.id);
    boardRefs.current[nextIndex]?.focus();
  }, [onBoardChange]);

  const hasRows = sorted.length > 0;

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

      {/*
        A radiogroup with a roving tabindex: one tab stop for six mutually exclusive filters,
        instead of six stops she has to walk through to reach the feed. Arrow keys move and
        select within the group (and stop propagating, so the shell's arrow navigation does not
        also move the feed selection underneath her).
      */}
      <div className="board-tabs" role="radiogroup" aria-label="Filter attention feed">
        {boards.map((item, index) => (
          <button
            type="button"
            key={item.id}
            ref={(element) => { boardRefs.current[index] = element; }}
            role="radio"
            aria-checked={board === item.id}
            tabIndex={board === item.id ? 0 : -1}
            className="filter-button"
            onClick={() => onBoardChange(item.id)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                event.preventDefault();
                event.stopPropagation();
                moveBoard(index, 1);
              } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                event.preventDefault();
                event.stopPropagation();
                moveBoard(index, -1);
              }
            }}
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

      <p id="feed-keys-hint" className="sr-only">
        One tab stop: J and K or the arrow keys move through the candidates, Enter selects the
        active one, and semicolon holds it.
      </p>

      {/*
        The feed is a LISTBOX and its rows are options: one tab stop total, with
        `aria-activedescendant` naming the active row. Focusing the listbox also puts screen
        readers into focus mode over it, so the shell's letter keys reach the page instead of
        colliding with browse-mode quick-nav (six of the eight single-letter shortcuts do).
        Rows are never focusable, so mounting and unmounting under virtualization cannot add,
        remove, or reorder tab stops while she scrolls.
      */}
      <div
        ref={scrollRef}
        className="feed-scroll"
        role={hasRows ? "listbox" : undefined}
        tabIndex={hasRows ? 0 : undefined}
        aria-label={hasRows ? "Market candidates" : undefined}
        aria-describedby={hasRows ? "feed-keys-hint" : undefined}
        aria-activedescendant={activeRowMounted && activeId !== undefined ? candidateOptionDomId(activeId) : undefined}
        onKeyDown={hasRows ? onListboxKeyDown : undefined}
        onFocus={hasRows ? onListboxFocus : undefined}
      >
        {!hasRows ? (
          <div className="empty-state" role="status">
            <strong>No candidates match this view.</strong>
            <span>Change the board or clear search. This is not a zero-activity claim.</span>
          </div>
        ) : (
          <ul
            className="virtual-list"
            role="presentation"
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
                  id={candidateOptionDomId(candidate.id)}
                  role="option"
                  aria-selected={selectedId === candidate.id}
                  data-index={row.index}
                  data-candidate-id={candidate.id}
                  className="virtual-row"
                  style={{ transform: `translateY(${row.start}px)` }}
                  aria-setsize={sorted.length}
                  aria-posinset={row.index + 1}
                  aria-keyshortcuts=";"
                  onClick={() => {
                    // A press on an already-focused listbox produces no focus event to consume
                    // the guard, so the click clears it: the guard must only ever swallow the
                    // one focus event its own press caused.
                    pointerFocusRef.current = false;
                    onSelect(candidate.id);
                  }}
                  onPointerDown={markPointerFocus}
                  onMouseDown={markPointerFocus}
                  // Both enter flavors: pointerenter is the real channel in browsers, while
                  // mouseenter is what environments without PointerEvent (jsdom) deliver.
                  // The shell's note is idempotent, so a browser firing both records once.
                  onPointerEnter={() => onPointerCandidate?.(candidate.id)}
                  onMouseEnter={() => onPointerCandidate?.(candidate.id)}
                >
                  <div className="candidate-card">
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
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
});
