import { memo, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
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
import { Activity, ArrowDown, ArrowUp, Bookmark, FastForward, LayoutGrid, MessagesSquare, Radio, RefreshCw, Rows3 } from "lucide-react";

import type { Candidate, FlowWindow } from "../contract/v1";
import { basisPoints, candidateName, candidateSymbol, compactCount, compactUsd, duration, sentenceCase, signedTone } from "../format";
import { athProgress, chainReading, FLOW_WINDOWS, flowFor, providerClaimTitle, trueAgeSeconds } from "./candidateFacts";
import { candleGlyphSpec } from "./candleGlyph";
import { CoinArt } from "./CoinArt";
import { candidateHoverText, EVIDENCE_CLASS_GLYPH, evidenceClassesPresent, evidenceTitle, marketCapDisagreementNote } from "./provenance";
import { SORT_COLUMNS, type BoardSort, type SortColumnId } from "./boardSemantics";
import { SPARKLINE_HEIGHT, SPARKLINE_WIDTH, sparklineSpec } from "./sparkline";
import type { Density } from "../App";

export type BoardFilter = "all" | Candidate["board"];

/**
 * The two renderings of the hunt board itself, pump-parity's real toggle: `table` is the
 * dense sortable-column read, `grid` is the image-first card wall (the mobile-primary UX —
 * the coin art IS the card). Both are the SAME listbox, virtualizer, and attention channels;
 * the toggle changes what a row paints and how rows are laid out, never what "seen" means,
 * what a gesture binds to, or what lands durably.
 */
export type BoardLayout = "table" | "grid";

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
 * The table's sortable columns, in cell order. Every one is a labelled provider claim the
 * parity seam actually carries; there is deliberately NO per-window %-change column because
 * the movers wire asserts no per-window price change (the 5m move is the one served move).
 * `name` is the accessible sort name; `title` is the claim's hover sentence for the header.
 */
const TABLE_SORT_HEADERS: Array<{ sortId: SortColumnId; label: string; name: string; title: string }> = [
  {
    sortId: "age",
    label: "age",
    name: "true coin age",
    title: "True coin age: the scene's render clock minus the provider-claimed creation time. Distinct from evidence age.",
  },
  { sortId: "mcap", label: "mcap", name: "market cap", title: "Rendered USD market cap, a provider claim." },
  {
    sortId: "ath",
    label: "ath",
    name: "claimed all-time-high cap",
    title: "The provider's own recorded all-time-high USD cap; the bar is the current cap over that claimed high.",
  },
  { sortId: "move5m", label: "5m", name: "5-minute move", title: "Observed 5-minute move in this view." },
  { sortId: "vol1h", label: "1h vol", name: "claimed 1h volume", title: "Provider-claimed trailing 1-hour volume (USD), from the movers tap." },
  { sortId: "vol24h", label: "24h vol", name: "claimed 24h volume", title: "Provider-claimed trailing 24-hour volume (USD), from the movers tap." },
  { sortId: "txns24h", label: "txns", name: "claimed 24h trades", title: "Provider-claimed trailing 24-hour trade count, from the movers tap." },
  {
    sortId: "traders24h",
    label: "trdrs",
    name: "claimed 24h traders",
    title: "Provider-claimed trailing 24-hour unique traders, where the movers document stated one.",
  },
  { sortId: "replies", label: "replies", name: "claimed replies", title: "The provider's own reply counter for this coin." },
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
  layout = "table",
  onLayoutChange,
  sort = null,
  onSortChange,
  renderedAtUnixMs = null,
  trending,
  chainScope,
  onChainScopeChange,
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
  /** Table or image-first grid; board variant only, presentation only. */
  layout?: BoardLayout;
  onLayoutChange?(layout: BoardLayout): void;
  /** The active column sort the shell applied over the tab's order, for the header state. */
  sort?: BoardSort | null;
  /** Cycle a column: absent → its default direction → the opposite → cleared. */
  onSortChange?(sort: BoardSort | null): void;
  /** The scene's render clock in epoch ms, the anchor for TRUE coin age. Null: no scene clock. */
  renderedAtUnixMs?: number | null;
  /**
   * The trending strip's candidates, already ranked by the shell (largest provider-claimed
   * 24h volume first, flow-carrying coins only). Absent or empty renders no strip — the
   * strip is a lens on served flow, never a fabricated chart position.
   */
  trending?: Candidate[];
  /**
   * The venue scope: Ember trades Solana pump.fun, so `venue` (the default) keeps coins the
   * provider positively claims on OTHER chains out of the hunt — they stay one explicit
   * click away under `all`, and a coin whose chain the view does not state always passes
   * (unknown is never assumed foreign, or Solana). The shell applies the filter; this is
   * only its visible control, rendered when the shell offers one.
   */
  chainScope?: "venue" | "all";
  onChainScopeChange?(scope: "venue" | "all"): void;
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
  const gridLayout = variant === "board" && layout === "grid";

  /**
   * How many card lanes the grid packs, measured from the scroll element's real width. In an
   * environment with no layout (jsdom's clientWidth is 0) the default stands and only decides
   * inline percentages nothing renders — the option list, order, and channels are identical
   * at any lane count, which is exactly the invariant the grid must keep.
   */
  const [laneCount, setLaneCount] = useState(3);
  useEffect(() => {
    if (!gridLayout) return;
    const element = scrollRef.current;
    if (!element) return;
    const measure = () => {
      const width = element.clientWidth;
      if (width > 0) setLaneCount(Math.max(2, Math.min(6, Math.floor(width / 200))));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [gridLayout]);

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

  /**
   * FIXED-SIZE virtualization, deliberately: every row height below is exact for its
   * (variant, layout, density), the row elements are clamped to that height by CSS, and the
   * rows carry NO `measureElement` ref. Dynamic measurement is what made the virtualizer
   * flushSync from inside React's own render at real board scale (measured: a 2095-candidate
   * live scene flooded "flushSync was called from inside a lifecycle method" 12 times over
   * one walk), and it bought nothing — fixed-height rows have nothing to measure. With exact
   * sizes, `row.start`/`row.end` are exact, so the visible-rectangle attention channel keeps
   * claiming precisely the pixels that intersect the viewport, the active-descendant pin
   * keeps its offsets, and nothing about "seen" changes.
   */
  const rowVirtualizer = useVirtualizer({
    count: sorted.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => (gridLayout
      ? (density === "comfortable" ? 324 : 300)
      : variant === "board"
        ? (density === "comfortable" ? 46 : 38)
        : (density === "comfortable" ? 118 : 100)),
    overscan: 5,
    initialRect: { width: 440, height: 640 },
    getItemKey: (index) => sorted[index]?.id ?? index,
    rangeExtractor,
    // The grid is the same virtualizer packing the same items into lanes: virtual items keep
    // their 1:1 mapping to candidates, so the pin, the active descendant, and the visible-
    // rectangle channel are literally the same code in both layouts.
    lanes: gridLayout ? laneCount : 1,
  });
  useEffect(() => {
    // Fixed sizes come from estimateSize alone, so a layout or density flip must drop the
    // cached sizes and re-estimate; nothing else ever changes a row's height.
    rowVirtualizer.measure();
  }, [density, gridLayout, laneCount, rowVirtualizer, variant]);
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

  /** One header click walks the honest cycle: default direction → the opposite → cleared. */
  const cycleSort = useCallback((columnId: SortColumnId) => {
    if (!onSortChange) return;
    const definition = SORT_COLUMNS[columnId];
    if (sort === null || sort.column !== columnId) {
      onSortChange({ column: columnId, direction: definition.defaultDirection });
    } else if (sort.direction === definition.defaultDirection) {
      onSortChange({
        column: columnId,
        direction: definition.defaultDirection === "descending" ? "ascending" : "descending",
      });
    } else {
      onSortChange(null);
    }
  }, [onSortChange, sort]);

  const hasRows = sorted.length > 0;

  return (
    <section className="panel attention-panel" data-variant={variant} aria-labelledby="attention-title">
      <div className="panel-header attention-header">
        <div>
          <p className="eyebrow">{variant === "board" ? "Live hunt" : "Broad surface"}</p>
          <h2 id="attention-title">{variant === "board" ? "Hunt board" : "Attention feed"}</h2>
        </div>
        {/*
          The table/grid toggle, pump-parity's real switch. Presentation only: both layouts
          are the same listbox and channels, so flipping it cannot change what "seen" means
          or which coin a gesture binds. One roving tab stop, like the filter tabs.
        */}
        {variant === "board" && onLayoutChange && (
          <div className="board-layout-toggle" role="radiogroup" aria-label="Board layout">
            {([
              { id: "table" as const, label: "Table", icon: <Rows3 aria-hidden="true" size={14} /> },
              { id: "grid" as const, label: "Grid", icon: <LayoutGrid aria-hidden="true" size={14} /> },
            ]).map((item) => (
              <button
                type="button"
                key={item.id}
                role="radio"
                aria-checked={layout === item.id}
                tabIndex={layout === item.id ? 0 : -1}
                className="filter-button layout-button"
                onClick={() => onLayoutChange(item.id)}
                onKeyDown={(event) => {
                  if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)) {
                    event.preventDefault();
                    event.stopPropagation();
                    onLayoutChange(item.id === "table" ? "grid" : "table");
                  }
                }}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </div>
        )}
        <output className="count-badge" aria-live="polite">
          {sorted.length} visible
        </output>
      </div>

      {/*
        The trending strip: art plus the coin's own thesis line, for the coins whose wire
        carries the largest provider-claimed 24h volume. Ranked by the shell over served flow
        (the hover states the basis); a scene in which nothing carries flow has no strip,
        because a strip with an invented ranking would be a chart position nobody served.
        One roving tab stop; a press is the same click-through a board row gets.
      */}
      {variant === "board" && trending !== undefined && trending.length > 0 && (
        <div
          className="trending-strip"
          role="toolbar"
          aria-label="Trending by claimed 24-hour volume"
          title={"Largest provider-claimed 24-hour volume (USD) first; only coins whose wire "
            + "carries a movers flow window. Provider claims, not endorsements."}
        >
          {trending.map((candidate, index) => {
            const volume24h = flowFor(candidate, "24h")?.volumeUsd ?? null;
            return (
              <button
                type="button"
                key={candidate.id}
                className="trending-item"
                tabIndex={index === 0 ? 0 : -1}
                title={candidate.description ?? candidateHoverText(candidate)}
                onClick={() => (onOpen ?? onSelect)(candidate.id)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                    event.preventDefault();
                    event.stopPropagation();
                    const strip = event.currentTarget.parentElement;
                    if (!strip) return;
                    const items = [...strip.querySelectorAll<HTMLButtonElement>(".trending-item")];
                    const next = items[(index + (event.key === "ArrowRight" ? 1 : -1) + items.length) % items.length];
                    next?.focus();
                  }
                }}
              >
                <CoinArt candidate={candidate} size="strip" />
                <span className="trending-copy">
                  <strong>{candidateSymbol(candidate.symbol, candidate.mint)}</strong>
                  <span className="trending-thesis">
                    {candidate.description ?? <span className="board-absent">— no thesis in this view</span>}
                  </span>
                </span>
                {volume24h !== null && (
                  <span className="trending-volume">
                    {compactUsd(volume24h)}
                    <span className="sr-only"> claimed 24-hour volume</span>
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/*
        The advance affordance, loud where the hunt actually happens. It stays an explicit
        operator act — this button and the palette entry run the same rebind, nothing swaps
        on its own — but it no longer hides in a palette: while she is scanning the board,
        "newer scenes exist" is exactly the fact that decides whether this board is still
        worth scanning.
      */}
      {variant === "board" && advanceNotice && (
        <div
          className="advance-notice"
          title={"Advancing is your act; this board never swaps on its own. "
            + "Held coins and the journal stay."}
        >
          <button type="button" className="advance-pill" onClick={advanceNotice.advance}>
            <FastForward aria-hidden="true" />
            {advanceNotice.count === null
              ? "Newer scenes exist — advance"
              : `${advanceNotice.count} newer scene${advanceNotice.count === 1 ? "" : "s"} — advance`}
          </button>
          <span className="advance-detail">Newest derived {advanceNotice.derivedAt.slice(11, 16)} UTC</span>
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
        The chain scope, beside the tabs on both variants: Solana is her venue and the
        default; the multichain coins pump now lists are one explicit switch away, never
        silently gone (the basis line counts what the scope hid). One roving tab stop.
      */}
      {chainScope !== undefined && onChainScopeChange && (
        <div className="chain-scope" role="radiogroup" aria-label="Chain scope">
          {([
            {
              id: "venue" as const,
              label: "Solana",
              title: "Her venue: coins the provider claims on Solana, plus coins whose chain this view does not state. JOSHI's instruments are Solana-only.",
            },
            {
              id: "all" as const,
              label: "All chains",
              title: "Every served coin, including other-chain pump listings. Non-Solana coins wear their chain chip; Solana-only instruments do not apply to them.",
            },
          ]).map((item) => (
            <button
              type="button"
              key={item.id}
              role="radio"
              aria-checked={chainScope === item.id}
              tabIndex={chainScope === item.id ? 0 : -1}
              className="filter-button chain-scope-button"
              title={item.title}
              onClick={() => onChainScopeChange(item.id)}
              onKeyDown={(event) => {
                if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)) {
                  event.preventDefault();
                  event.stopPropagation();
                  onChainScopeChange(item.id === "venue" ? "all" : "venue");
                }
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}

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
        The table's column headers. Sortable columns are real buttons in one roving-tabindex
        toolbar (one tab stop for nine sorts); clicking cycles default direction → opposite →
        cleared, and the applied rule is always restated in words by the basis line above.
        Non-sortable labels stay decorative (aria-hidden): every cell below carries its own
        screen-reader words, so those labels would only be announced twice.
      */}
      {variant === "board" && layout === "table" && hasRows && (
        <div className="board-columns" role="toolbar" aria-label="Sort the board by a column">
          <span aria-hidden="true">#</span>
          <span aria-hidden="true" className="board-col-art" />
          <span aria-hidden="true">coin</span>
          <span aria-hidden="true" className="board-col-spark">path</span>
          {TABLE_SORT_HEADERS.map((header, index) => {
            const active = sort !== null && sort.column === header.sortId;
            const definition = SORT_COLUMNS[header.sortId];
            const stateWords = active ? definition.words[sort.direction] : null;
            return (
              <button
                type="button"
                key={header.sortId}
                className="board-sort-button board-col-number"
                data-col={header.sortId}
                data-active={active || undefined}
                tabIndex={(active || (sort === null && index === 0)) ? 0 : -1}
                aria-pressed={active}
                aria-label={`Sort by ${header.name}${stateWords ? `, currently ${stateWords}` : ""}`}
                title={header.title}
                onClick={() => cycleSort(header.sortId)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                    event.preventDefault();
                    event.stopPropagation();
                    const toolbar = event.currentTarget.parentElement;
                    if (!toolbar) return;
                    const items = [...toolbar.querySelectorAll<HTMLButtonElement>(".board-sort-button")];
                    const at = items.indexOf(event.currentTarget);
                    items[(at + (event.key === "ArrowRight" ? 1 : -1) + items.length) % items.length]?.focus();
                  }
                }}
              >
                {header.label}
                {active && (sort.direction === "descending"
                  ? <ArrowDown aria-hidden="true" size={11} />
                  : <ArrowUp aria-hidden="true" size={11} />)}
              </button>
            );
          })}
          {/*
            The DEFAULT order's own header, in the badges slot: pump's Movers shape over what
            the wire actually serves (claimed 24h volume, then market cap, then the 5-minute
            move). It is a real sort — active on landing, direction-flippable, clearable to
            the tab's served order — never an invisible hand.
          */}
          {(() => {
            const moversActive = sort !== null && sort.column === "movers";
            const moversWords = moversActive ? SORT_COLUMNS.movers.words[sort.direction] : null;
            return (
              <button
                type="button"
                className="board-sort-button board-col-badges"
                data-col="movers"
                data-active={moversActive || undefined}
                tabIndex={moversActive ? 0 : -1}
                aria-pressed={moversActive}
                aria-label={`Sort by movers${moversWords ? `, currently ${moversWords}` : ""}`}
                title={"The default hunt order — pump's Movers shape over served claims: largest "
                  + "claimed 24h volume first; coins without flow follow by market cap, then by "
                  + "5-minute move magnitude; coins with none of these keep served order."}
                onClick={() => cycleSort("movers")}
                onKeyDown={(event) => {
                  if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                    event.preventDefault();
                    event.stopPropagation();
                    const toolbar = event.currentTarget.parentElement;
                    if (!toolbar) return;
                    const items = [...toolbar.querySelectorAll<HTMLButtonElement>(".board-sort-button")];
                    const at = items.indexOf(event.currentTarget);
                    items[(at + (event.key === "ArrowRight" ? 1 : -1) + items.length) % items.length]?.focus();
                  }
                }}
              >
                movers
                {moversActive && (sort.direction === "descending"
                  ? <ArrowDown aria-hidden="true" size={11} />
                  : <ArrowUp aria-hidden="true" size={11} />)}
              </button>
            );
          })()}
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
                  // Deliberately NO measureElement ref: rows are fixed-height (the exact
                  // estimateSize above) and clamped by CSS, so the dynamic-measurement path —
                  // and its flushSync-during-render at thousand-row scale — never runs.
                  id={candidateOptionDomId(candidate.id)}
                  role="option"
                  aria-selected={selectedId === candidate.id}
                  data-index={row.index}
                  data-candidate-id={candidate.id}
                  className={gridLayout ? "virtual-row virtual-card" : "virtual-row"}
                  style={gridLayout
                    ? {
                        transform: `translateY(${row.start}px)`,
                        height: `${row.size}px`,
                        left: `${(row.lane / laneCount) * 100}%`,
                        width: `${100 / laneCount}%`,
                      }
                    : { transform: `translateY(${row.start}px)`, height: `${row.size}px` }}
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
                    gridLayout
                      ? <GridCard candidate={candidate} rank={rank} renderedAtUnixMs={renderedAtUnixMs} />
                      : <BoardRow candidate={candidate} rank={rank} renderedAtUnixMs={renderedAtUnixMs} />
                  ) : (
                    <ColumnCard candidate={candidate} rank={rank} density={density} />
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

/**
 * The compact epistemic chips a card face carries instead of sentences: the ticker absence,
 * the provider's own market-cap disagreement, and the claims glyph. Each chip's hover title
 * carries the full derivation-authored sentence verbatim; the face carries only the flag.
 * Shared by both variants so a fact cannot be a chip on one lens and a paragraph on the other.
 */
function EpistemicChips({ candidate }: { candidate: Candidate }) {
  const classes = evidenceClassesPresent(candidate.evidence);
  const capsNote = marketCapDisagreementNote(candidate);
  return (
    <>
      {candidate.symbol === null && (
        <span
          className="board-chip chip-absent"
          title="No ticker or name was observed for this mint; its leading characters stand in."
        >
          no ticker
        </span>
      )}
      {capsNote !== null && (
        <span className="board-chip chip-warn" title={capsNote}>
          2 caps differ
        </span>
      )}
      <span className="board-chip chip-evidence" title={evidenceTitle(candidate.evidence)}>
        <span aria-hidden="true">{classes.map((cls) => EVIDENCE_CLASS_GLYPH[cls]).join("·")}</span>
        <span className="sr-only">evidence: {classes.join(", ")}</span>
      </span>
    </>
  );
}

/** A flow-window figure cell: the claim's value with its evidence one hover away, or a dash. */
function FlowCell({ candidate, window, field, what, col, render }: {
  candidate: Candidate;
  window: FlowWindow["window"];
  field: "volumeUsd" | "txns" | "traders";
  what: string;
  col: SortColumnId;
  render(value: string): string;
}) {
  const entry = flowFor(candidate, window);
  const value = entry?.[field] ?? null;
  if (value === null) return <span className="board-cell board-number" data-col={col}><AbsentValue what={what} /></span>;
  return (
    <span className="board-cell board-number" data-col={col} title={providerClaimTitle(candidate, "flow", `Claimed ${what}`)}>
      {render(value)}
      <span className="sr-only"> claimed {what}</span>
    </span>
  );
}

/**
 * The ATH cell: the provider's claimed all-time-high cap with a compact progress bar of
 * current over claimed high. Both figures are provider claims; the ratio is presentation
 * (a bar, like a sparkline's normalization), and a current cap above the claimed high says
 * so on hover instead of silently pinning the bar.
 */
function AthCell({ candidate }: { candidate: Candidate }) {
  if (candidate.athMarketCapUsd === undefined) {
    return <span className="board-cell board-number" data-col="ath"><AbsentValue what="claimed all-time-high cap" /></span>;
  }
  const progress = athProgress(candidate);
  const title = providerClaimTitle(candidate, "athMarketCapUsd", "Claimed all-time-high cap")
    + (progress === null
      ? "\nNo rendered market cap exists to compare against it."
      : progress.aboveClaimedAth
        ? "\nThe rendered market cap exceeds the provider's own recorded high; the bar is pinned full."
        : `\nThe bar is the rendered market cap over this claimed high (${Math.round(progress.ratio * 100)}%).`);
  return (
    <span className="board-cell board-number board-ath" data-col="ath" title={title}>
      <span>
        {compactUsd(candidate.athMarketCapUsd)}
        <span className="sr-only"> claimed all-time-high cap</span>
      </span>
      {progress !== null && (
        <span className="ath-bar" aria-hidden="true" data-above={progress.aboveClaimedAth || undefined}>
          <span style={{ width: `${Math.round(progress.ratio * 100)}%` }} />
        </span>
      )}
    </span>
  );
}

/** The TRUE-age cell: render clock minus the provider's claimed creation clock, or a dash. */
function TrueAgeCell({ candidate, renderedAtUnixMs }: {
  candidate: Candidate;
  renderedAtUnixMs: number | null;
}) {
  const age = trueAgeSeconds(candidate, renderedAtUnixMs);
  if (age === null) return <span className="board-cell board-number" data-col="age"><AbsentValue what="provider-claimed creation time" /></span>;
  return (
    <span
      className="board-cell board-number"
      data-col="age"
      title={providerClaimTitle(candidate, "createdAtUnixMs", "True coin age")
        + "\nAnchored to this scene's render clock, so a replayed scene states the age as of the scene."}
    >
      {duration(age)}
      <span className="sr-only"> since the claimed creation time</span>
    </span>
  );
}

/**
 * One hunt-board row: the pump.fun-shaped glance — art, ticker (or mint prefix when no
 * ticker was observed), name, price path, TRUE age, market cap, claimed ATH with its
 * progress bar, the 5-minute move colored by sign, and the movers-tap volume/trade/trader
 * claims — with the epistemics COLLAPSED to chips instead of paragraphs. Nothing is
 * deleted: the attention reason and social summary ride the row's hover title verbatim,
 * the field-by-field provenance rides the claims glyph's title, and the whole evidence
 * workbench stays one lens switch away. Cells that the view does not observe render
 * `AbsentValue`, never a fabricated zero. No sentence renders inline: the derivation's
 * attention "reason" on a live surface is a provenance paragraph, and a row that must scan
 * in under a second has no line to spend on it.
 */
function BoardRow({ candidate, rank, renderedAtUnixMs }: {
  candidate: Candidate;
  rank: Candidate["rank"];
  renderedAtUnixMs: number | null;
}) {
  const spark = sparklineSpec(candidate.candles);
  const { marketCapUsd, change5mBps } = candidate.metrics;
  return (
    <div className="board-row" title={candidateHoverText(candidate)}>
      <span
        className="board-rank"
        data-absent={rank === null}
        aria-label={rank === null ? "This view states no rank for this candidate" : `Rank ${rank}`}
      >
        {rank ?? "—"}
      </span>
      <CoinArt candidate={candidate} size="row" />
      <span className="board-identity">
        <span className="board-title">
          <strong className="board-ticker">{candidateSymbol(candidate.symbol, candidate.mint)}</strong>
          {candidate.name !== null && <span className="board-name">{candidate.name}</span>}
        </span>
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
      <TrueAgeCell candidate={candidate} renderedAtUnixMs={renderedAtUnixMs} />
      <span className="board-cell board-number" data-col="mcap">
        {marketCapUsd === null ? <AbsentValue what="market cap" /> : <>{compactUsd(marketCapUsd)}<span className="sr-only"> market cap</span></>}
      </span>
      <AthCell candidate={candidate} />
      <span className={`board-cell board-number board-move value-${signedTone(change5mBps)}`} data-col="move5m">
        {change5mBps === null ? <AbsentValue what="5-minute move" /> : <>{basisPoints(change5mBps)}<span className="sr-only"> in 5 minutes</span></>}
      </span>
      <FlowCell candidate={candidate} window="1h" field="volumeUsd" what="1h volume" col="vol1h" render={compactUsd} />
      <FlowCell candidate={candidate} window="24h" field="volumeUsd" what="24h volume" col="vol24h" render={compactUsd} />
      <FlowCell candidate={candidate} window="24h" field="txns" what="24h trades" col="txns24h" render={compactCount} />
      <FlowCell candidate={candidate} window="24h" field="traders" what="24h traders" col="traders24h" render={compactCount} />
      <span className="board-cell board-number" data-col="replies">
        {candidate.replyCount === undefined
          ? <AbsentValue what="claimed reply count" />
          : (
            <span title={providerClaimTitle(candidate, "replyCount", "Claimed replies")}>
              {compactCount(candidate.replyCount)}
              <span className="sr-only"> claimed replies</span>
            </span>
          )}
      </span>
      <span className="board-badges">
        {candidate.watched === true && (
          <span className="icon-label" title="Watched">
            <Bookmark aria-hidden="true" size={13} />
            <span className="sr-only">Watched</span>
          </span>
        )}
        <span className={`board-chip lifecycle-${candidate.lifecycle}`}>{sentenceCase(candidate.lifecycle)}</span>
        <ChainChip candidate={candidate} />
        <ProviderFlagChips candidate={candidate} />
        <EpistemicChips candidate={candidate} />
      </span>
    </div>
  );
}

/**
 * The chain claim as a chip, from the provider's verbatim `chainId`. A NON-Solana coin gets
 * a loud chip carrying the chainId's namespace — pump went multichain, and every one of
 * JOSHI's instruments (venue floor, curve, tape) is Solana-only, so "different venue" must
 * read at a glance, never as a broken Solana coin. A Solana claim is a subtle mark (or
 * nothing where space is tight); an absent chainId renders nothing, because unknown is an
 * absence and this cockpit never assumes Solana. The verbatim chainId rides the hover.
 */
function ChainChip({ candidate, subtle = true }: { candidate: Candidate; subtle?: boolean }) {
  const chain = chainReading(candidate);
  if (chain.kind === "unknown") return null;
  if (chain.kind === "solana") {
    if (!subtle) return null;
    return (
      <span
        className="board-chip chip-sol"
        title={`Provider chain claim: ${chain.chainId}\nA Solana coin: JOSHI's venue, curve, and tape instruments can apply.`}
      >
        sol
      </span>
    );
  }
  return (
    <span
      className="board-chip chip-chain"
      title={`Provider chain claim: ${chain.chainId}\nA ${chain.family} coin — a different venue. JOSHI's Solana-only instruments (venue floor, curve, tape) do not apply to it.`}
    >
      {chain.family}
    </span>
  );
}

/**
 * The provider's boolean flags as compact chips, each a labelled claim with its sentence on
 * hover. Rendered only when the wire carries the flag as true — an absent flag is an absence,
 * and a `false` claim earns no chip because the chip row is for facts that change a glance.
 * `graduated` deliberately has no chip here: the lifecycle chip already states graduation as
 * the derivation's own field, and two chips asserting one fact would invite them to disagree.
 */
function ProviderFlagChips({ candidate }: { candidate: Candidate }) {
  return (
    <>
      {candidate.currentlyLive === true && (
        <span className="board-chip chip-live" title={providerClaimTitle(candidate, "currentlyLive", "Live now")}>
          <span className="live-dot" aria-hidden="true" />live
        </span>
      )}
      {candidate.verified === true && (
        <span className="board-chip chip-verified" title={providerClaimTitle(candidate, "verified", "Verified")}>
          verified
        </span>
      )}
      {candidate.nsfw === true && (
        <span className="board-chip chip-nsfw" title={providerClaimTitle(candidate, "nsfw", "NSFW")}>
          nsfw
        </span>
      )}
    </>
  );
}

/**
 * One image-first grid card: the coin art IS the card (pump's mobile-primary shape), with
 * the identity, market cap, TRUE age, claimed replies, the coin's own thesis line, and —
 * Ember's explicit ask — CANDLES plotted on the card where the candidate carries a price
 * path. Where only movers flow exists the card plots the claimed volume by window instead
 * (labelled as volume — it must never read as a price path), and where neither exists the
 * chart slot is a dash. Same honesty rules as the table: absences are dashes with their
 * sentences on hover, chips carry claims, and the hover prose is verbatim derivation text.
 */
function GridCard({ candidate, rank, renderedAtUnixMs }: {
  candidate: Candidate;
  rank: Candidate["rank"];
  renderedAtUnixMs: number | null;
}) {
  const age = trueAgeSeconds(candidate, renderedAtUnixMs);
  const { marketCapUsd } = candidate.metrics;
  return (
    <div className="grid-card" title={candidateHoverText(candidate)}>
      <span className="grid-card-art">
        <CoinArt candidate={candidate} size="card" />
        <span className="grid-card-overlay">
          {rank !== null && <span className="board-chip grid-rank" aria-label={`Rank ${rank}`}>#{rank}</span>}
          {candidate.watched === true && (
            <span className="icon-label" title="Watched">
              <Bookmark aria-hidden="true" size={13} />
              <span className="sr-only">Watched</span>
            </span>
          )}
          <ChainChip candidate={candidate} subtle={false} />
          <ProviderFlagChips candidate={candidate} />
        </span>
      </span>
      <span className="grid-card-body">
        <span className="grid-card-title">
          <strong className="board-ticker">{candidateSymbol(candidate.symbol, candidate.mint)}</strong>
          {candidate.name !== null && <span className="board-name">{candidate.name}</span>}
        </span>
        <span className="grid-card-facts">
          {marketCapUsd === null
            ? <AbsentValue what="market cap" />
            : <span title="Rendered USD market cap, a provider claim.">{compactUsd(marketCapUsd)}<span className="sr-only"> market cap</span></span>}
          {age === null
            ? <AbsentValue what="provider-claimed creation time" />
            : (
              <span title={providerClaimTitle(candidate, "createdAtUnixMs", "True coin age")}>
                {duration(age)}
                <span className="sr-only"> since the claimed creation time</span>
              </span>
            )}
          {candidate.replyCount !== undefined && (
            <span className="grid-replies" title={providerClaimTitle(candidate, "replyCount", "Claimed replies")}>
              <MessagesSquare aria-hidden="true" size={12} />
              {compactCount(candidate.replyCount)}
              <span className="sr-only"> claimed replies</span>
            </span>
          )}
        </span>
        {candidate.description !== undefined
          ? (
            <span className="grid-thesis" title={providerClaimTitle(candidate, "description", "The coin's own thesis line")}>
              {candidate.description}
            </span>
          )
          : (
            <span className="grid-thesis grid-thesis-absent" title="This view does not observe a thesis line for this coin.">
              <span aria-hidden="true">—</span>
              <span className="sr-only">thesis not observed</span>
            </span>
          )}
        <GridChart candidate={candidate} />
        <span className="grid-card-chips">
          <span className={`board-chip lifecycle-${candidate.lifecycle}`}>{sentenceCase(candidate.lifecycle)}</span>
          <EpistemicChips candidate={candidate} />
        </span>
      </span>
    </div>
  );
}

const GRID_CHART_WIDTH = 148;
const GRID_CHART_HEIGHT = 44;

/**
 * The grid card's chart slot, in strict preference order of what the wire actually carries:
 * candles (plotted as candles on their own bar clocks — a provider-omitted silence stays a
 * visible hole, never interpolated), else the movers-tap volume by window (bars labelled as
 * volume), else a dash. Nothing is invented to fill the slot.
 */
function GridChart({ candidate }: { candidate: Candidate }) {
  const glyph = candleGlyphSpec(candidate.candles, GRID_CHART_WIDTH, GRID_CHART_HEIGHT);
  if (glyph !== null) {
    return (
      <span className="grid-chart" data-kind="candles">
        <svg
          className="candle-glyph"
          viewBox={`0 0 ${GRID_CHART_WIDTH} ${GRID_CHART_HEIGHT}`}
          preserveAspectRatio="none"
          aria-hidden="true"
          focusable="false"
        >
          <title>
            {`Served candles over their own bar clocks; no interval or unit is stated.`
              + (glyph.omittedIntervals > 0
                ? ` ${glyph.omittedIntervals} interval(s) in which nothing traded are omitted by the provider and stay visibly empty.`
                : "")}
          </title>
          {glyph.bars.map((bar, index) => (
            <g key={index} className={`candle value-${bar.tone}`}>
              <line x1={bar.x} x2={bar.x} y1={bar.wickY1} y2={bar.wickY2} stroke="currentColor" strokeWidth="0.75" />
              <rect
                x={bar.x - glyph.barWidth / 2}
                y={bar.bodyY}
                width={glyph.barWidth}
                height={bar.bodyHeight}
                fill="currentColor"
              />
            </g>
          ))}
        </svg>
        <span className="sr-only">served candle path</span>
      </span>
    );
  }
  if (candidate.flow !== undefined) return <FlowVolumeGlyph candidate={candidate} />;
  return (
    <span className="grid-chart" data-kind="absent">
      <AbsentValue what="price path" />
    </span>
  );
}

/**
 * Claimed volume by trailing window, for a card whose coin carries movers flow but no price
 * path. Bars are scaled to the largest present window's USD volume; an absent window is an
 * empty labelled slot, never a zero-height claim. Explicitly NOT a price path, and it says so.
 */
function FlowVolumeGlyph({ candidate }: { candidate: Candidate }) {
  const entries = FLOW_WINDOWS.map((window) => ({ window, entry: flowFor(candidate, window) }));
  const volumes = entries.map(({ entry }) => (entry === null ? null : Number(entry.volumeUsd)));
  const max = Math.max(...volumes.filter((value): value is number => value !== null && Number.isFinite(value)), 0);
  const title = "Provider-claimed volume by trailing window (USD) — not a price path:\n"
    + entries
      .map(({ window, entry }) => `${window}: ${entry === null ? "not claimed" : compactUsd(entry.volumeUsd)}`)
      .join(" · ");
  return (
    <span className="grid-chart flow-glyph" data-kind="flow" title={title}>
      {entries.map(({ window, entry }, index) => {
        const volume = volumes[index] ?? null;
        const height = entry === null || max <= 0 || volume === null || !Number.isFinite(volume)
          ? 0
          : Math.max(8, Math.round((volume / max) * 100));
        return (
          <span key={window} className="flow-slot" data-absent={entry === null || undefined}>
            {entry === null
              ? <span className="flow-absent" aria-hidden="true">—</span>
              : <span className="flow-bar" style={{ height: `${height}%` }} aria-hidden="true" />}
            <small aria-hidden="true">{window}</small>
          </span>
        );
      })}
      <span className="sr-only">claimed volume by window; no price path was observed</span>
    </span>
  );
}

/**
 * One evidence-column card, beside the workbench on the inspect lens. Same discipline as the
 * board row: identity, the observed figures (an `AbsentValue` dash where the view carries
 * none), and the epistemics as chips — the derivation's attention and social sentences ride
 * the card's hover title verbatim and never render inline. The full field-by-field prose
 * stays one affordance away in the workbench's provenance drawer and the source panel.
 */
function ColumnCard({ candidate, rank, density }: {
  candidate: Candidate;
  rank: Candidate["rank"];
  density: Density;
}) {
  const { ageSeconds, marketCapUsd, change5mBps } = candidate.metrics;
  return (
    <div className="candidate-card" title={candidateHoverText(candidate)}>
      <span
        className="candidate-rank"
        data-absent={rank === null}
        aria-label={rank === null ? "This view states no rank for this candidate" : `Rank ${rank}`}
      >
        {rank ?? "—"}
      </span>
      <CoinArt candidate={candidate} size="row" />
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
        <span className="candidate-facts">
          {marketCapUsd === null
            ? <AbsentValue what="market cap" />
            : <span>{compactUsd(marketCapUsd)}<span className="sr-only"> market cap</span></span>}
          {change5mBps === null
            ? <AbsentValue what="5-minute move" />
            : (
              <span className={`value-${signedTone(change5mBps)}`}>
                {basisPoints(change5mBps)} · 5m
              </span>
            )}
          {ageSeconds === null
            ? <AbsentValue what="coin age" />
            : <span>{duration(ageSeconds)} old</span>}
        </span>
        {density === "comfortable" && (
          <span className="candidate-context">
            <span>
              <Activity aria-hidden="true" size={15} />
              {sentenceCase(candidate.metrics.activity)}
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
        <ChainChip candidate={candidate} />
        <EpistemicChips candidate={candidate} />
      </span>
    </div>
  );
}
