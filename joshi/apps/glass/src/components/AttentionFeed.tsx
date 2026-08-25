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
import { Activity, Bookmark, FastForward, RefreshCw, Radio, Users } from "lucide-react";

import type { Candidate, EvidenceClass, EvidenceRef } from "../contract/v1";
import { basisPoints, candidateName, candidateSymbol, compactUsd, duration, sentenceCase, signedTone } from "../format";
import { SPARKLINE_HEIGHT, SPARKLINE_WIDTH, sparklineSpec } from "./sparkline";
import type { Density } from "../App";

export type BoardFilter = "all" | Candidate["board"];

/**
 * The two renderings of the same feed. `column` is the evidence-forward card column the
 * inspect workbench sits beside; `board` is the hunt board — dense single-glance rows, one
 * coin per line, sized for scanning seventy candidates while price scrolls by. The variants
 * differ ONLY in what a row paints: the listbox, `aria-activedescendant`, virtualizer, and
 * all three attention channels (scroll-rectangle visibility, active-descendant reach,
 * pointer entry) are the same lines of code, so what "seen" means cannot drift between them.
 */
export type FeedVariant = "column" | "board";

/**
 * Newer immutable scenes the shell knows about, rendered by the board as a loud pill at the
 * top. Advancing stays the operator's own explicit act — the pill runs the same `advance`
 * the command palette offers, nothing ever swaps on its own, and no single-letter shortcut
 * exists for it (six of the eight existing letters already collide with screen-reader
 * quick-nav). `count` is null when the feed lists scenes but the bound one is not among
 * them, so how many are strictly newer is not knowable and is not claimed.
 */
export type AdvanceNotice = {
  count: number | null;
  derivedAt: string;
  advance(): void;
};

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
  onOpen,
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
  variant = "column",
  boardBasis,
  advanceNotice = null,
}: {
  candidates: Candidate[];
  selectedId: string;
  onSelect(id: string): void;
  /**
   * The click-through, when the shell offers one: a row click or Enter OPENS this coin (the
   * hunt board passes the coin-page act here), while Space, J/K, and the arrows still only
   * move and select. Absent, click and Enter fall back to plain selection — the inspect
   * column's feed keeps its old meaning, where the workbench is already beside the rows.
   * Pointer motion never opens anything, exactly as it never selects.
   */
  onOpen?(id: string): void;
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
  variant?: FeedVariant;
  /** The sort or filter rule the current tab actually applied, stated under the tabs. */
  boardBasis?: string;
  /** Newer scenes exist; rendered as the loud advance pill by the board variant only. */
  advanceNotice?: AdvanceNotice | null;
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
    estimateSize: () => (variant === "board"
      ? (density === "comfortable" ? 58 : 40)
      : (density === "comfortable" ? 156 : 126)),
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
      if (!active) return;
      // Enter opens the coin when the shell offers a click-through; Space stays selection
      // only, so the keyboard keeps a way to mark a row without leaving the board.
      if (event.key === "Enter" && onOpen) onOpen(active.id);
      else onSelect(active.id);
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const target = event.key === "Home" ? sorted[0] : sorted[sorted.length - 1];
      if (target) onSelect(target.id);
    }
    // J/K and the arrow keys reach the shell's global handler by bubbling; it moves the
    // selection (and therefore the active descendant) and prevents the container scroll.
  }, [activeIndex, onOpen, onSelect, sorted]);

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
    <section className="panel attention-panel" data-variant={variant} aria-labelledby="attention-title">
      <div className="panel-header attention-header">
        <div>
          <p className="eyebrow">{variant === "board" ? "Live hunt" : "Broad surface"}</p>
          <h2 id="attention-title">{variant === "board" ? "Hunt board" : "Attention feed"}</h2>
        </div>
        <output className="count-badge" aria-live="polite">
          {sorted.length} visible
        </output>
      </div>

      {/*
        The advance affordance, loud where the hunt actually happens. It stays an explicit
        operator act — this button and the palette entry run the same rebind, nothing swaps
        on its own — but it no longer hides in a palette: while she is scanning the board,
        "newer scenes exist" is exactly the fact that decides whether this board is still
        worth scanning.
      */}
      {variant === "board" && advanceNotice && (
        <div className="advance-notice">
          <button type="button" className="advance-pill" onClick={advanceNotice.advance}>
            <FastForward aria-hidden="true" />
            {advanceNotice.count === null
              ? "Newer scenes exist — advance"
              : `${advanceNotice.count} newer scene${advanceNotice.count === 1 ? "" : "s"} — advance`}
          </button>
          <span className="advance-detail">
            Newest derived {advanceNotice.derivedAt.slice(11, 16)} UTC. Advancing is your act;
            this board never swaps on its own. Held coins and the journal stay.
          </span>
        </div>
      )}

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

      {/*
        What the current tab's order actually is, said out loud. A sorted tab names its sort;
        a tab whose metric no candidate carries says so rather than presenting the served
        order as a ranking (`boardSemantics.ts` builds the sentence with the sort itself).
      */}
      {boardBasis !== undefined && <p className="board-basis">{boardBasis}</p>}

      {orderUpdatePending && onAcceptOrderUpdate && (
        <div className="pending-order" role="status">
          <span><strong>Updated order available</strong>{pendingNewCount > 0 ? ` · ${pendingNewCount} new` : ""}. Cards stay fixed until you accept it.</span>
          <button type="button" onClick={onAcceptOrderUpdate}><RefreshCw aria-hidden="true" /> Accept updated order</button>
        </div>
      )}

      <p id="feed-keys-hint" className="sr-only">
        {onOpen
          ? "One tab stop: J and K or the arrow keys move through the candidates, Enter opens "
            + "the active coin's page, Space selects it without leaving the board, and "
            + "semicolon holds it."
          : "One tab stop: J and K or the arrow keys move through the candidates, Enter selects "
            + "the active one, and semicolon holds it."}
      </p>

      {/*
        Column labels for the board's aligned cells. Decorative for readers (aria-hidden):
        every cell below carries its own screen-reader words ("market cap", "old", "in 5
        minutes"), so the labels here would only be announced twice.
      */}
      {variant === "board" && hasRows && (
        <div className="board-columns" aria-hidden="true">
          <span>#</span>
          <span>coin</span>
          <span className="board-col-spark">path</span>
          <span className="board-col-number">age</span>
          <span className="board-col-number">mcap</span>
          <span className="board-col-number">5m</span>
          <span className="board-col-badges" />
        </div>
      )}

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
            <span>Change the board or clear search.</span>
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
                    (onOpen ?? onSelect)(candidate.id);
                  }}
                  onPointerDown={markPointerFocus}
                  onMouseDown={markPointerFocus}
                  // Both enter flavors: pointerenter is the real channel in browsers, while
                  // mouseenter is what environments without PointerEvent (jsdom) deliver.
                  // The shell's note is idempotent, so a browser firing both records once.
                  onPointerEnter={() => onPointerCandidate?.(candidate.id)}
                  onMouseEnter={() => onPointerCandidate?.(candidate.id)}
                >
                  {variant === "board" ? (
                    <BoardRow candidate={candidate} rank={rank} density={density} />
                  ) : (
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
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
});

/**
 * A served figure this view does not carry. The dash keeps the board scannable; the words
 * stay with it for readers and on hover, because a silent blank would be indistinguishable
 * from a zero and a number without its absence stated is a lie by omission.
 */
function AbsentValue({ what }: { what: string }) {
  return (
    <span className="board-absent" title={`This view does not observe a ${what} for this coin.`}>
      <span aria-hidden="true">—</span>
      <span className="sr-only">{what} not observed</span>
    </span>
  );
}

const EVIDENCE_CLASS_ORDER: EvidenceClass[] = ["observed", "derived", "attested", "interpreted", "unknown"];
const EVIDENCE_CLASS_GLYPH: Record<EvidenceClass, string> = {
  observed: "O",
  derived: "D",
  attested: "A",
  interpreted: "I",
  unknown: "?",
};

/** Which provenance classes this candidate's evidence carries, for the compact claims glyph. */
function evidenceClassesPresent(evidence: readonly EvidenceRef[]): EvidenceClass[] {
  return EVIDENCE_CLASS_ORDER.filter((cls) => evidence.some((ref) => ref.evidenceClass === cls));
}

/** The full field-by-field provenance, one hover away behind the glyph. */
function evidenceTitle(evidence: readonly EvidenceRef[]): string {
  return [
    "Field provenance in this view:",
    ...evidence.map((ref) => `${ref.field}: ${ref.evidenceClass} (${ref.status}) — ${ref.note}`),
  ].join("\n");
}

/**
 * One hunt-board row: the pump.fun-shaped glance — ticker (or mint prefix when no ticker
 * was observed), name, price path, age, market cap, and the 5-minute move colored by sign —
 * with the epistemics COLLAPSED to chips instead of paragraphs. Nothing is deleted: the
 * attention reason and social summary ride the row's hover title (and, in comfortable
 * density, one truncated line), the field-by-field provenance rides the claims glyph's
 * title, and the whole evidence workbench stays one lens switch away. Cells that the view
 * does not observe render `AbsentValue`, never a fabricated zero.
 */
function BoardRow({ candidate, rank, density }: {
  candidate: Candidate;
  rank: Candidate["rank"];
  density: Density;
}) {
  const spark = sparklineSpec(candidate.candles);
  const { ageSeconds, marketCapUsd, change5mBps } = candidate.metrics;
  const classes = evidenceClassesPresent(candidate.evidence);
  return (
    <div className="board-row" title={`${candidate.attentionReason}\n${candidate.socialSummary}`}>
      <span
        className="board-rank"
        data-absent={rank === null}
        aria-label={rank === null ? "This view states no rank for this candidate" : `Rank ${rank}`}
      >
        {rank ?? "—"}
      </span>
      <span className="board-identity">
        <span className="board-title">
          <strong className="board-ticker">{candidateSymbol(candidate.symbol, candidate.mint)}</strong>
          {candidate.name !== null && <span className="board-name">{candidate.name}</span>}
        </span>
        {density === "comfortable" && (
          <span className="board-reason">{candidate.attentionReason}</span>
        )}
      </span>
      <span className="board-cell board-spark">
        {spark && (
          <svg
            className={`sparkline value-${spark.tone}`}
            viewBox={`0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}`}
            aria-hidden="true"
            focusable="false"
          >
            {/* Hover honesty for the shape: it is the served path on its own bar clocks. */}
            <title>Served price path over its own bar clocks; no interval or unit is stated.</title>
            <polyline points={spark.points} fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        )}
      </span>
      <span className="board-cell board-number">
        {ageSeconds === null ? <AbsentValue what="coin age" /> : <>{duration(ageSeconds)}<span className="sr-only"> old</span></>}
      </span>
      <span className="board-cell board-number">
        {marketCapUsd === null ? <AbsentValue what="market cap" /> : <>{compactUsd(marketCapUsd)}<span className="sr-only"> market cap</span></>}
      </span>
      <span className={`board-cell board-number board-move value-${signedTone(change5mBps)}`}>
        {change5mBps === null ? <AbsentValue what="5-minute move" /> : <>{basisPoints(change5mBps)}<span className="sr-only"> in 5 minutes</span></>}
      </span>
      <span className="board-badges">
        {candidate.watched === true && (
          <span className="icon-label" title="Watched">
            <Bookmark aria-hidden="true" size={13} />
            <span className="sr-only">Watched</span>
          </span>
        )}
        <span className={`board-chip lifecycle-${candidate.lifecycle}`}>{sentenceCase(candidate.lifecycle)}</span>
        {candidate.symbol === null && (
          <span
            className="board-chip chip-absent"
            title="No ticker or name was observed for this mint; its leading characters stand in."
          >
            no ticker
          </span>
        )}
        <span className="board-chip chip-evidence" title={evidenceTitle(candidate.evidence)}>
          <span aria-hidden="true">{classes.map((cls) => EVIDENCE_CLASS_GLYPH[cls]).join("·")}</span>
          <span className="sr-only">evidence: {classes.join(", ")}</span>
        </span>
      </span>
    </div>
  );
}
