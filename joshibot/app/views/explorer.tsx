import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import { Explain, Figure } from "@/components/figure";
import { Absent, Field, Lamp, Panel, StatusPill } from "@/components/instrument";
import { useNow } from "@/components/now";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  HUNCH_COINS_PATH,
  HUNCH_HEALTH_PATH,
  HUNCH_PATH,
  HUNCH_POSITIONS_PATH,
  HUNCH_TAPE_PATH,
  ZAP_PATH,
  coinsPath,
  isMint,
  isSighted,
  load,
  loadCoins,
  loadHunchHealth,
  loadHunchTape,
  loadPositions,
  loadReadout,
  loadResolution,
  postHunch,
  postZap,
  readoutPath,
  resolvePath,
  type CoinCard,
  type CoinList,
  type CoinSort,
  type HunchHealth,
  type HunchKind,
  type HunchReceipt,
  type HunchTape,
  type Loaded,
  type MaybeCard,
  type Position,
  type PositionList,
  type Readout,
  type ReadoutPayload,
  type Resolution,
  type ZapReceipt,
} from "@/lib/hunch";
import {
  cn,
  decimals,
  formatSpan,
  fractionAsPct,
  relativeAge,
  shortAddress,
  sol,
  usd,
} from "@/lib/format";
import {
  clockOf,
  fromNullable,
  observed,
  unwatched,
  type Clock,
  type Measured,
  type Origin,
} from "@/lib/measure";

/**
 * THE COIN EXPLORER — see it, click it.
 *
 * This is the click-shaped, early form of `design/glass.md` §4: the operator points at a
 * coin and the gesture is recorded, verbatim, with the instrument reading attached. It
 * replaces a browsing loop that currently runs on somebody else's site and ends in a
 * copy-pasted contract address.
 *
 * BOUNDARY, restated because this is a new surface: DISPLAY LOGIC ONLY. Every number here
 * was computed by `shitcoims_paperdesk/glass.py` with the same estimators the desk marks
 * its book with. Nothing in this file thresholds, ranks, scores, or derives — the sorts are
 * query parameters the server applies, the gates are served pre-evaluated and inert, and
 * the warnings after a click are the server's own words.
 *
 * It also talks ONLY to `/hunch/*`. The sentinel is usually down and that is irrelevant
 * here: this view never touches `useDesk()` or the snapshot, so a dead 8787 costs it
 * nothing.
 */

/** Two boards-poll cycles' worth of list churn. Fast enough to feel live, slow enough to read. */
const REFRESH_MS = 6_000;
/** Chrome only — the health strip never reshuffles a card, so it polls through a pause. */
const HEALTH_MS = 10_000;
/** The floor on clipboard reads. Never tighter than this. */
const CLIPBOARD_MS = 2_500;
/** Backoff once the browser has refused a clipboard read; focus still retries immediately. */
const CLIPBOARD_RETRY_MS = 20_000;
const TAPE_MS = 12_000;
/** The exit strip. Faster than the grid and never paused — a stale exit costs money. */
const POSITIONS_MS = 4_000;

const SORTS: { id: CoinSort; label: string; hint: string }[] = [
  { id: "recent", label: "recent", hint: "Freshest board sighting first." },
  {
    id: "callout",
    label: "callout",
    hint: "Most recently posted about first; coins nobody named go last. Sorted by the server over the whole index, not over the page. The callout feed's measured verdict is that it locates VOLATILITY, not direction — it tells you where people are looking, not which way to lean.",
  },
  {
    id: "wiggle",
    label: "wiggle",
    hint: "The wiggle book's own candidate ordering — two-sidedness then swing count. It is the RULE's taste, offered as a lens, and this surface exists to be disagreed with.",
  },
  { id: "drawdown", label: "drawdown", hint: "Furthest below its all-time high first. Coins with no served ATH sort last, not as zero." },
  { id: "mcap", label: "mcap", hint: "Largest served USD market cap first." },
  { id: "age", label: "age", hint: "Youngest first. Coins with no creation stamp sort last." },
];

// ---------------------------------------------------------------------- provenance

function cardClock(card: CoinCard, receivedAt: string | null): Clock {
  return clockOf(card.t_seen, receivedAt);
}

const T_SEEN_NOTE =
  "t_seen is the COLLECTOR's ingest stamp for the freshest board row on this coin, not a chain or block time. Do not read a latency from it.";

/**
 * Lift one served card field into a `Measured<T>`.
 *
 * A `null` from this producer means NOT MEASURED, and the card's `absent` map names the
 * reason — which is carried straight into the provenance popover. That pairing is the whole
 * contract between `glass.py` and this file: the server never sends a zero it did not
 * measure, and this function never invents one.
 */
function cardFigure<T>(
  card: CoinCard,
  field: string,
  value: T | null | undefined,
  receivedAt: string | null,
  extra: Partial<Origin> = {},
): Measured<T> {
  const reason = card.absent[field];
  const origin: Origin = {
    source: HUNCH_COINS_PATH,
    path: `items[].${field}`,
    kind: "served",
    clock: cardClock(card, receivedAt),
    ...extra,
    note: reason ?? extra.note ?? T_SEEN_NOTE,
  };
  return fromNullable(value, origin);
}

/** The same lift for the slower per-mint instrument, which carries its own `absent` map. */
function readoutFigure<T>(
  readout: Readout,
  field: string,
  value: T | null | undefined,
  receivedAt: string | null,
  extra: Partial<Origin> = {},
): Measured<T> {
  const reason = readout.absent[field];
  const origin: Origin = {
    source: `${readoutPath(readout.mint)} → readout`,
    path: field,
    kind: "served",
    clock: clockOf(null, receivedAt),
    ...extra,
    note: reason ?? extra.note,
  };
  return fromNullable(value, origin);
}

/**
 * Callout recency, and the one figure on the card with a genuine THREE-way absence.
 *
 * `absent.callout` present means the intelligence store could not be read: nothing was
 * watching, so silence here carries no information at all — `unwatched`. A plain `null`
 * means the store WAS read and nobody named this mint in the last hour — `unobserved`.
 * Collapsing those two would turn "we could not look" into "nobody is talking about it",
 * which is the single most misleading thing this feed could say.
 */
function calloutRecency(card: CoinCard, receivedAt: string | null): Measured<number> {
  const clock = cardClock(card, receivedAt);
  const base = {
    source: HUNCH_COINS_PATH,
    path: "items[].callout_last_s",
    kind: "served" as const,
    clock,
  };
  const unreadable = card.absent.callout ?? card.absent.callouts;
  if (unreadable) return unwatched({ ...base, note: unreadable });
  return fromNullable(card.callout_last_s, {
    ...base,
    note:
      card.callout_last_s === null
        ? "The intelligence store was read and nobody named this mint in the last hour. Presence and recency only — this feed dedupes by mint, so there is never a count."
        : "Seconds since the most recent post naming this mint. Presence and recency, not a count. This feed locates volatility, not direction.",
  });
}

/** `load()` never yields "loading", but the type admits it; name that rather than cast. */
function errorText<T>(loaded: Loaded<T>): string {
  return loaded.state === "error" ? loaded.error : "the request never completed";
}

/** Sample size, in the same visual register as the rate it belongs to. Never a tooltip. */
function SampleN({ n }: { n: number }) {
  return <span className="ml-1.5 font-mono text-[11px] text-muted-foreground">n={n}</span>;
}

// ---------------------------------------------------------------------- the view

type Capture =
  | { state: "posting" }
  | { state: "captured"; receipt: HunchReceipt }
  | { state: "failed"; error: string };

type ZapState =
  | { state: "zapping" }
  | { state: "zapped"; receipt: ZapReceipt }
  | { state: "failed"; error: string };

type ClipState =
  | { kind: "idle" }
  | { kind: "off"; reason: string }
  | { kind: "resolving"; query: string }
  | { kind: "refused"; resolution: Resolution }
  | { kind: "error"; query: string; error: string }
  | {
      kind: "pinned";
      card: MaybeCard;
      resolution: Resolution | null;
      readout: Readout | null;
      receivedAt: string;
    };

export function Explorer() {
  const now = useNow();

  const [sort, setSort] = useState<CoinSort>("recent");
  const [board, setBoard] = useState<string | null>(null);
  const [freshOnly, setFreshOnly] = useState(true);
  const [list, setList] = useState<Loaded<CoinList>>({ state: "loading", source: HUNCH_COINS_PATH });
  const [health, setHealth] = useState<Loaded<HunchHealth>>({
    state: "loading",
    source: HUNCH_HEALTH_PATH,
  });
  const [tape, setTape] = useState<Loaded<HunchTape>>({ state: "loading", source: HUNCH_TAPE_PATH });
  const [boards, setBoards] = useState<string[]>([]);

  const [expanded, setExpanded] = useState<string | null>(null);
  const [readouts, setReadouts] = useState<Record<string, Loaded<ReadoutPayload>>>({});
  const [typing, setTyping] = useState(false);
  const [captures, setCaptures] = useState<Record<string, Capture>>({});
  const [clip, setClip] = useState<ClipState>({ kind: "idle" });
  const [positions, setPositions] = useState<Loaded<PositionList>>({
    state: "loading",
    source: HUNCH_POSITIONS_PATH,
  });
  const [zaps, setZaps] = useState<Record<string, ZapState>>({});

  const posting = useMemo(
    () => Object.values(captures).some((capture) => capture.state === "posting"),
    [captures],
  );

  /**
   * A list that reshuffles under a click is a misfire, and a misfired hunch is a corrupt
   * datum — it records the operator pointing at a coin they were not looking at. So the
   * poll stops entirely while they are typing a note, reading an expanded card, or waiting
   * on a capture. Nothing here degrades gracefully; it stops.
   */
  const paused = typing || expanded !== null || posting;

  const refreshCoins = useCallback(async () => {
    const next = await load(
      () => loadCoins({ limit: 60, sort, board, freshOnly }),
      coinsPath({ limit: 60, sort, board, freshOnly }),
    );
    setList(next);
    if (next.state === "ok") {
      const seen = next.fetched.data.items
        .map((item) => item.board)
        .filter((name): name is string => Boolean(name));
      setBoards((previous) => {
        const merged = new Set([...previous, ...seen]);
        return [...merged].sort();
      });
    }
  }, [sort, board, freshOnly]);

  useEffect(() => {
    void refreshCoins();
  }, [refreshCoins]);

  useEffect(() => {
    if (paused) return;
    const timer = window.setInterval(() => void refreshCoins(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refreshCoins, paused]);

  useEffect(() => {
    const tick = async () => setHealth(await load(loadHunchHealth, HUNCH_HEALTH_PATH));
    void tick();
    const timer = window.setInterval(() => void tick(), HEALTH_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const tick = async () => setTape(await load(() => loadHunchTape(24), HUNCH_TAPE_PATH));
    void tick();
    const timer = window.setInterval(() => void tick(), TAPE_MS);
    return () => window.clearInterval(timer);
  }, []);

  /**
   * The rail polls on its own clock and is NOT paused with the grid. "Always lets me" is
   * the requirement, and a stale exit strip is the one thing on this screen that costs
   * money. Row order is by holding time, which only ever grows, so rows do not reshuffle
   * under a finger — the order changes only when a position opens or closes.
   */
  useEffect(() => {
    const tick = async () => setPositions(await load(loadPositions, HUNCH_POSITIONS_PATH));
    void tick();
    const timer = window.setInterval(() => void tick(), POSITIONS_MS);
    return () => window.clearInterval(timer);
  }, []);

  /**
   * One click, straight through. No confirm, no optimistic lie: the button shows "…" while
   * the request is open and the server's own receipt when it lands. The row is already
   * fsynced by then, which is exactly why there is no undo offered anywhere near this.
   */
  const zap = useCallback(
    async (position: Position, reason: string) => {
      setZaps((previous) => ({ ...previous, [position.mint]: { state: "zapping" } }));
      try {
        const receipt = await postZap({
          mint: position.mint,
          position_id: position.position_id,
          reason: reason.trim() || undefined,
          surface: "glass:zap-rail",
          context: {
            view: "explorer",
            panel: "zap-rail",
            sort,
            board,
            fresh_only: freshOnly,
            armed_on_screen: position.armed,
            reason_typed: reason.trim().length > 0,
          },
          // The desk's own row as the operator was shown it, declared rather than measured.
          position: { position_id: position.position_id, decision_id: position.decision_id },
        });
        setZaps((previous) => ({ ...previous, [position.mint]: { state: "zapped", receipt } }));
      } catch (error) {
        setZaps((previous) => ({
          ...previous,
          [position.mint]: {
            state: "failed",
            error: error instanceof Error ? error.message : "the desk did not answer",
          },
        }));
      }
    },
    [sort, board, freshOnly],
  );

  const items = list.state === "ok" ? list.fetched.data.items : [];
  const receivedAt = list.state === "ok" ? list.fetched.receivedAt : null;

  const openReadout = useCallback(async (mint: string) => {
    setReadouts((previous) => ({
      ...previous,
      [mint]: { state: "loading", source: readoutPath(mint) },
    }));
    const next = await load(() => loadReadout(mint), readoutPath(mint));
    setReadouts((previous) => ({ ...previous, [mint]: next }));
  }, []);

  // The fetch is kept OUT of the state updater on purpose: StrictMode invokes updaters
  // twice, and this one polls a live vendor under a 2s deadline. A double poll per click
  // is a real cost, not a dev-only cosmetic.
  const toggleExpand = useCallback(
    (mint: string) => {
      if (expanded === mint) {
        setExpanded(null);
        return;
      }
      setExpanded(mint);
      void openReadout(mint);
    },
    [expanded, openReadout],
  );

  /**
   * The click. Fire-and-render: the row is already fsynced on the desk by the time this
   * resolves, so the response is a receipt, and its `warnings` go on the card that produced
   * the gesture. They are never reconstructed here — a warning the browser wrote would be a
   * warning about a card, not about what was captured.
   */
  const capture = useCallback(
    async (card: MaybeCard, kind: HunchKind, note: string, surface: string) => {
      const mint = card.mint;
      setCaptures((previous) => ({ ...previous, [mint]: { state: "posting" } }));
      try {
        const receipt = await postHunch({
          mint,
          kind,
          note: note.trim() || undefined,
          surface,
          // Declared by the surface, kept by the server in its own labelled key. Only
          // facts about the SCREEN belong here — what was measured is the server's own
          // `evidence.card`, and this repo does not sum measured with attested.
          context: {
            view: "explorer",
            sort,
            board,
            fresh_only: freshOnly,
            list_received_at: receivedAt,
            card_expanded: expanded === mint,
            note_typed: note.trim().length > 0,
            seconds_since_seen_on_screen: isSighted(card) ? card.seconds_since_seen : null,
          },
        });
        setCaptures((previous) => ({ ...previous, [mint]: { state: "captured", receipt } }));
      } catch (error) {
        setCaptures((previous) => ({
          ...previous,
          [mint]: {
            state: "failed",
            error: error instanceof Error ? error.message : "the desk did not answer",
          },
        }));
      }
    },
    [sort, board, freshOnly, receivedAt, expanded],
  );

  const clipboard = useClipboardBridge({ items, setClip, clip });

  const deskAlive = health.state === "ok" ? health.fetched.data.desk.alive : null;
  const index = health.state === "ok" ? health.fetched.data.index : null;
  const hunchCount = health.state === "ok" ? health.fetched.data.hunches.total : null;

  return (
    <div className="space-y-3">
      <ZapRail
        loaded={positions}
        now={now}
        zaps={zaps}
        onZap={(position, reason) => void zap(position, reason)}
        onTyping={setTyping}
      />

      <Panel
        title="Coin explorer"
        source={`${HUNCH_COINS_PATH} · ${HUNCH_PATH}`}
        clock={
          list.state === "ok"
            ? clockOf(list.fetched.data.generated_at, list.fetched.receivedAt)
            : clockOf(null, null)
        }
        now={now}
        actions={
          <>
            {health.state === "error" ? (
              <StatusPill
                label="hunch api down"
                tone="bad"
                help={`${health.error}. Start it with: uv run python -m shitcoims_paperdesk glass --warm`}
              />
            ) : (
              <>
                <span className="flex items-center gap-1.5">
                  <Lamp
                    tone={deskAlive === null ? "idle" : deskAlive ? "ok" : "bad"}
                    live={deskAlive === true}
                  />
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {deskAlive === null ? "desk ?" : deskAlive ? "desk alive" : "desk dead"}
                  </span>
                </span>
                {index && (
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {index.coins} indexed
                  </span>
                )}
                {hunchCount !== null && (
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {hunchCount} hunches on tape
                  </span>
                )}
              </>
            )}
            <StatusPill
              label="no key"
              tone="idle"
              help="This surface talks only to the paper desk on 8790 — a process with no key, no RPC client and no broadcast path. It appends to state/hunches.jsonl and does nothing else. The sentinel's port is not reachable from this view at all."
            />
            <StatusPill
              label={paused ? "poll paused" : "live 6s"}
              tone={paused ? "warn" : "ok"}
              help={
                paused
                  ? "The list is frozen because you are typing, reading an expanded card, or a capture is in flight. A grid that reshuffles under your finger records a hunch about the wrong coin."
                  : "Refreshing every 6 seconds. It pauses the moment you touch a note field or open a card."
              }
            />
          </>
        }
        note={
          <>
            Click a coin and the gesture is on the tape, verbatim, with the instrument reading
            attached. <strong>wiggle</strong> is the only kind that opens a paper position (in the
            OPERATOR book); <strong>down</strong> and <strong>watch</strong> are claims that get
            scored at a horizon and trade nothing. The note is optional — clicking with an empty
            note is the normal path, and an empty utterance is honest: you pointed.
          </>
        }
      >
        <Controls
          sort={sort}
          onSort={setSort}
          board={board}
          boards={boards}
          onBoard={setBoard}
          freshOnly={freshOnly}
          onFreshOnly={setFreshOnly}
          nShown={items.length}
          nIndexed={list.state === "ok" ? list.fetched.data.n_indexed : null}
        />
      </Panel>

      <ClipboardPin
        clip={clip}
        watching={clipboard.watching}
        onRecheck={clipboard.recheck}
        onDismiss={clipboard.dismiss}
        onPick={clipboard.pick}
        now={now}
        capture={capture}
        captures={captures}
        onTyping={setTyping}
        expanded={expanded}
        onToggle={toggleExpand}
        readouts={readouts}
      />

      {list.state === "error" ? (
        <Panel title="Coins" source={list.source} tone="alert">
          <Absent
            reason="error"
            detail={
              <>
                <p className="font-mono">{list.error}</p>
                <p className="mt-2">
                  The hunch API is not answering on 8790. It is a separate process from the
                  sentinel and has to be running on its own:{" "}
                  <code className="font-mono">
                    uv run python -m shitcoims_paperdesk glass --warm
                  </code>
                </p>
              </>
            }
          />
        </Panel>
      ) : list.state === "loading" ? (
        <Panel title="Coins" source={HUNCH_COINS_PATH}>
          <Absent reason="loading" />
        </Panel>
      ) : items.length === 0 ? (
        <Panel title="Coins" source={HUNCH_COINS_PATH}>
          <Absent
            reason="no-rows"
            detail={
              freshOnly
                ? "Nothing on the boards inside the freshness window. Turn off `fresh only` to see coins the collectors last saw longer ago."
                : "The index has no coin matching this filter."
            }
          />
        </Panel>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {items.map((card) => (
            <CoinCardView
              key={card.mint}
              card={card}
              receivedAt={receivedAt}
              now={now}
              expanded={expanded === card.mint}
              onToggle={() => toggleExpand(card.mint)}
              readout={readouts[card.mint]}
              capture={captures[card.mint]}
              onCapture={(kind, note) => capture(card, kind, note, "glass:explorer")}
              onTyping={setTyping}
            />
          ))}
        </div>
      )}

      <TapePanel tape={tape} now={now} />
    </div>
  );
}

// ---------------------------------------------------------------------- the zap rail

/**
 * THE ZAP RAIL — always on screen, one click, no dialog. Ever.
 *
 * The operator, verbatim: *"a dashboard view that always lets me zap out a position that i
 * decide i dont like. because that's basically what i do... i watch it closely, and pull
 * out the position whenever i feel like it."*
 *
 * So it is a sticky strip above everything else on this surface rather than a tab, because
 * "always lets me" is the requirement and a tab is a thing you have to be on. And there is
 * NO CONFIRMATION STEP on this path, by doctrine: arming is ceremony, stopping is instant.
 * A confirm dialog here would measure the dialog instead of the operator. There is also no
 * undo affordance, real or decorative — the row is fsynced before the response returns, so
 * an undo button would be a lie about a fact that is already on disk.
 *
 * WHY CAPTURING THIS MATTERS: the zap row carries the full instrument state and the recent
 * price path at the moment of the exit, which turns every gesture into a labelled
 * `(state, exit)` pair. That is the training set for a REACTIVE exit policy. Every exit
 * rule in this repo today is a function of a clock, and it is a function of a clock only
 * because a clock is the only thing anybody ever wrote down.
 */
function ZapRail({
  loaded,
  now,
  zaps,
  onZap,
  onTyping,
}: {
  loaded: Loaded<PositionList>;
  now: number;
  zaps: Record<string, ZapState>;
  onZap: (position: Position, reason: string) => void;
  onTyping: (value: boolean) => void;
}) {
  const data = loaded.state === "ok" ? loaded.fetched.data : null;
  const items = data?.items ?? [];
  const receivedAt = loaded.state === "ok" ? loaded.fetched.receivedAt : null;

  return (
    <section className="sticky top-0 z-30 rounded-lg border border-chart-2/40 bg-card/95 backdrop-blur">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border/70 px-3 py-2">
        <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em]">
          Open positions
        </h2>
        <code className="rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
          {HUNCH_POSITIONS_PATH} · {ZAP_PATH}
        </code>
        {/* Staleness is structural here, not incidental: the desk persists once a minute,
            so this strip is up to ~60s behind by construction and says so. */}
        {data?.state_age_s != null && (
          <StatusPill
            label={`desk state ${formatSpan(data.state_age_s)} old`}
            tone={data.state_age_s > 120 ? "warn" : "idle"}
            help="The desk writes its book to disk about once a minute, so this strip is up to that stale BY CONSTRUCTION. It is not a live feed and must not be read as one. Your zap is still recorded against the live coin, not against this snapshot."
          />
        )}
        {data?.awaiting != null && data.awaiting.length > 0 && (
          <StatusPill
            label={`${data.awaiting.length} awaiting fill`}
            tone="info"
            help="Hunches the desk has taken but not yet filled — each opens on its first observation of the coin. They are not positions yet, so there is nothing to zap."
          />
        )}
        {data?.expectations != null && data.expectations.length > 0 && (
          <StatusPill
            label={`${data.expectations.length} open claims`}
            tone="idle"
            help="Open down/up/watch claims. They are scored at their horizon and hold no position, so they never appear in this rail as something to exit."
          />
        )}
        <StatusPill
          label="no confirm"
          tone="info"
          help="One click exits. There is deliberately no confirmation dialog and no undo: arming is ceremony, stopping is instant. The row is on disk before the button finishes animating."
        />
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {items.length} open
        </span>
      </header>

      {/* The desk writes its sidecar every cycle. Silence means the daemon is gone, and a
          rail rendering a dead desk's last book as current is the worst thing this surface
          can do — so it says so across the whole strip rather than in a pill. */}
      {data?.absent?.positions && (
        <p className="border-b border-destructive/50 bg-destructive/10 px-3 py-2 text-[11px] font-semibold leading-relaxed text-destructive">
          THE DESK IS NOT WRITING. {data.absent.positions}. Anything below is its last known
          book, not what it holds now, and a zap against it may be a zap against a position
          that has already closed.
        </p>
      )}

      {loaded.state === "error" ? (
        <p className="px-3 py-2 font-mono text-[11px] text-destructive">{loaded.error}</p>
      ) : items.length === 0 ? (
        <p className="px-3 py-2 text-[11px] text-muted-foreground">
          No open operator positions. A <span className="font-mono">wiggle</span> hunch below
          opens one, and it will appear here the moment the desk fills it.
        </p>
      ) : (
        <ul className="divide-y divide-border/40">
          {items.map((position) => (
            <ZapRow
              key={position.position_id ?? position.mint}
              position={position}
              now={now}
              receivedAt={receivedAt}
              zap={zaps[position.mint]}
              onZap={(reason) => onZap(position, reason)}
              onTyping={onTyping}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function ZapRow({
  position,
  now,
  receivedAt,
  zap,
  onZap,
  onTyping,
}: {
  position: Position;
  now: number;
  receivedAt: string | null;
  zap: ZapState | undefined;
  onZap: (reason: string) => void;
  onTyping: (value: boolean) => void;
}) {
  const [reason, setReason] = useState("");
  const armed = position.armed !== null;
  const busy = zap?.state === "zapping";

  /**
   * "Can the desk even see this coin right now?" — answered by the DESK, which publishes
   * `markable` against its own departure timeout. No threshold is invented here. Only when
   * the server declines to say does this fall back to the other server-decided facts (no
   * card at all, or the card's own freshness verdict); the browser never picks a number.
   */
  const unmarkable =
    position.markable === false ||
    (position.markable === undefined && (position.card === null || position.card.fresh === false));

  const origin = (path: string, note?: string): Origin => ({
    source: HUNCH_POSITIONS_PATH,
    path: `items[].${path}`,
    kind: "served",
    clock: clockOf(null, receivedAt),
    note,
  });

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2">
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          onZap(reason);
          setReason("");
        }}
        title="Exit now. No confirmation, no undo — the row is written the instant you click."
        className={cn(
          "rounded border px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-wider disabled:opacity-50",
          armed
            ? "border-chart-3/60 bg-chart-3/10 text-chart-3"
            : "border-destructive/60 bg-destructive/15 text-destructive hover:bg-destructive/25",
        )}
      >
        {busy ? "…" : "zap"}
      </button>

      <span className="font-mono text-xs font-semibold uppercase tracking-wider">
        {position.symbol || position.label || shortAddress(position.mint, 6, 4)}
      </span>
      <span className="font-mono text-[10px] text-muted-foreground select-none">
        {shortAddress(position.mint, 4, 4)}
      </span>

      {armed && (
        <StatusPill
          label={`exiting · ${position.armed}`}
          tone="warn"
          help="Already armed: the desk is exiting this on its next observation. Zapping again is recorded but changes nothing — the server logs it as zap_already_armed."
        />
      )}
      {unmarkable && (
        <StatusPill
          label="unobserved"
          tone="bad"
          help={
            position.card === null
              ? "No board is carrying this mint right now, so the desk has nothing to mark or fill against. A zap is still recorded — it is your intention, timestamped — but the exit cannot land until an observation arrives."
              : "The desk's own freshness verdict on this coin is stale. A zap fills on the NEXT observation, so if this stays stale the exit is not coming yet. The gesture is still captured."
          }
        />
      )}

      <span className="inline-flex items-baseline gap-1">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          pnl
        </span>
        <Figure
          m={fromNullable(
            position.unrealised_return,
            origin(
              "unrealised_return",
              "Mark against entry. Absent when the position is unmarkable — which is not a flat position, and must never read as 0%.",
            ),
          )}
          format={(value) => fractionAsPct(value, 2)}
          className={
            position.unrealised_return != null && position.unrealised_return < 0
              ? "text-destructive"
              : position.unrealised_return != null
                ? "text-lamp-ok"
                : undefined
          }
        />
      </span>

      <span className="inline-flex items-baseline gap-1">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          off peak
        </span>
        <Figure
          m={fromNullable(position.drawdown_from_peak, origin("drawdown_from_peak"))}
          format={(value) => fractionAsPct(value, 1)}
        />
      </span>

      <span className="inline-flex items-baseline gap-1">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          held
        </span>
        <Figure
          m={observed(position.held_s, origin("held_s"))}
          format={(value) => formatSpan(value)}
        />
        {position.observations != null && <SampleN n={position.observations} />}
      </span>

      <span className="inline-flex items-baseline gap-1">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          <Explain of={<span>backstop</span>}>
            The 20-40 minute backstop, which closes the position as{" "}
            <span className="font-mono">backstop_expired</span>. It is what happens when you do
            NOT act — the intended exit on this book is your zap, not this clock.
          </Explain>
        </span>
        <Figure
          m={observed(position.backstop_in_s, origin("backstop_in_s"))}
          format={(value) => (value > 0 ? `in ${formatSpan(value)}` : `${formatSpan(-value)} over`)}
        />
      </span>

      <span className="inline-flex items-baseline gap-1">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          last seen
        </span>
        <Figure
          m={observed(
            position.seconds_since_observed,
            origin(
              "seconds_since_observed",
              "How long since the desk observed this coin. A zap arms on the next cycle and fills on the first observation after it, so this is the delay your exit is actually waiting on.",
            ),
          )}
          format={(value) => `${formatSpan(value)} ago`}
        />
      </span>

      <Input
        value={reason}
        placeholder="why (optional)"
        onChange={(event) => setReason(event.target.value)}
        onFocus={() => onTyping(true)}
        onBlur={() => onTyping(false)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            onZap(reason);
            setReason("");
          }
          if (event.key === "Escape") event.currentTarget.blur();
        }}
        className="h-7 min-w-[8rem] max-w-[16rem] flex-1 font-mono text-[11px]"
      />

      {zap?.state === "zapped" && (
        <span className="font-mono text-[10px] text-chart-2">
          recorded {relativeAge(zap.receipt.recorded_at, now)} · {zap.receipt.state_features} path
          points captured · {zap.receipt.next}
        </span>
      )}
      {zap?.state === "failed" && (
        <span className="font-mono text-[10px] text-destructive">not recorded: {zap.error}</span>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------- controls

function Controls({
  sort,
  onSort,
  board,
  boards,
  onBoard,
  freshOnly,
  onFreshOnly,
  nShown,
  nIndexed,
}: {
  sort: CoinSort;
  onSort: (value: CoinSort) => void;
  board: string | null;
  boards: string[];
  onBoard: (value: string | null) => void;
  freshOnly: boolean;
  onFreshOnly: (value: boolean) => void;
  nShown: number;
  nIndexed: number | null;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
      <div className="flex flex-wrap items-center gap-1">
        <span className="mr-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          sort
        </span>
        {SORTS.map((option) => (
          <button
            key={option.id}
            type="button"
            onClick={() => onSort(option.id)}
            title={option.hint}
            className={cn(
              "rounded border px-2 py-1 font-mono text-[11px] uppercase tracking-wider",
              option.id === sort
                ? "border-primary/60 bg-primary/15 text-primary"
                : "text-muted-foreground hover:bg-muted",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          board
        </span>
        <select
          value={board ?? ""}
          onChange={(event) => onBoard(event.target.value || null)}
          className="rounded border bg-background px-2 py-1 font-mono text-[11px]"
        >
          <option value="">all boards</option>
          {boards.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      <button
        type="button"
        onClick={() => onFreshOnly(!freshOnly)}
        className={cn(
          "rounded border px-2 py-1 font-mono text-[11px] uppercase tracking-wider",
          freshOnly
            ? "border-primary/60 bg-primary/15 text-primary"
            : "text-muted-foreground hover:bg-muted",
        )}
      >
        fresh only {freshOnly ? "on" : "off"}
      </button>

      <span className="ml-auto font-mono text-[10px] text-muted-foreground">
        showing {nShown}
        {nIndexed !== null && ` of ${nIndexed} indexed`}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------- the card

function CoinCardView({
  card,
  receivedAt,
  now,
  expanded,
  onToggle,
  readout,
  capture,
  onCapture,
  onTyping,
  pinned = false,
}: {
  card: CoinCard;
  receivedAt: string | null;
  now: number;
  expanded: boolean;
  onToggle: () => void;
  readout: Loaded<ReadoutPayload> | undefined;
  capture: Capture | undefined;
  onCapture: (kind: HunchKind, note: string) => void;
  onTyping: (value: boolean) => void;
  pinned?: boolean;
}) {
  const label = card.symbol || card.name || shortAddress(card.mint, 6, 4);
  const rateOrigin: Partial<Origin> = {
    sample: { n: card.sightings, window: "boards sightings, last hour" },
  };

  return (
    <section
      className={cn(
        "flex min-w-0 flex-col rounded-lg border bg-card/60",
        card.ghost_town && "border-destructive/50 bg-destructive/5",
        pinned && "border-primary/60 bg-primary/5",
      )}
    >
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border/70 px-3 py-2">
        <button
          type="button"
          onClick={onToggle}
          className="font-mono text-xs font-semibold uppercase tracking-wider hover:text-primary"
        >
          {label}
        </button>
        {/* Truncated and non-copyable. A live poisoning campaign targets this operator
            with leading-and-trailing vanity matches; a feed address is never offered
            whole and never offered for copying. */}
        <span className="font-mono text-[10px] text-muted-foreground select-none">
          {shortAddress(card.mint, 4, 4)}
        </span>
        {card.name && card.symbol && (
          <span className="truncate text-[11px] text-muted-foreground">{card.name}</span>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-1">
          {card.held && (
            <StatusPill
              label="held"
              tone="info"
              help="The sentinel or the paper desk is already in this bag. A wiggle hunch on a mint already held is recorded but does not open a second position."
            />
          )}
          {card.ghost_town && (
            <StatusPill
              label="ghost town"
              tone="bad"
              help="Thin and/or not recently traded. At this depth there may be no exit at the quoted price at all — your own clip moves the price. The desk will still take your call and tag it."
            />
          )}
          {card.complete && (
            <StatusPill
              label="graduated"
              tone="warn"
              help="This mint has left the bonding curve. The desk marks on the curve, so a position may resolve as GRADUATED rather than on its clock."
            />
          )}
          {card.callout_last_s !== null && (
            <StatusPill
              label={`called ${formatSpan(card.callout_last_s)}`}
              tone="info"
              help={
                <>
                  Somebody posted about this mint {formatSpan(card.callout_last_s)} ago
                  {card.callout_author ? ` (@${card.callout_author})` : ""}. This is PRESENCE and
                  recency, not a count — the feed dedupes by mint. Its measured verdict is that it
                  locates volatility, never direction: it says people are looking here, and nothing
                  at all about which way.
                </>
              }
            />
          )}
          {card.hunched && (
            <StatusPill
              label={`hunched ${card.hunched.n}x`}
              tone="info"
              help={`last: ${card.hunched.last_kind ?? "?"} ${
                card.hunched.last_at ? relativeAge(card.hunched.last_at, now) : ""
              }`}
            />
          )}
          <Badge variant={card.fresh ? "default" : "outline"} className="font-mono">
            {formatSpan(card.seconds_since_seen)} ago
          </Badge>
          {card.board && (
            <span className="font-mono text-[10px] text-muted-foreground">{card.board}</span>
          )}
        </div>
      </header>

      <div className="grid grid-cols-2 gap-x-3 gap-y-2 px-3 py-2 sm:grid-cols-4">
        <Field
          label="drawdown"
          hint="Fraction below the vendor's all-time high. Absent means the vendor served no ATH for this coin — which is NOT the same as being at its high."
        >
          <Figure
            m={cardFigure(card, "drawdown_from_ath", card.drawdown_from_ath, receivedAt)}
            format={(value) => fractionAsPct(value, 1)}
          />
        </Field>
        <Field label="age" hint="Time from the coin's creation stamp to the sighting.">
          <Figure
            m={cardFigure(card, "age_s", card.age_s, receivedAt)}
            format={(value) => formatSpan(value)}
          />
        </Field>
        <Field label="mcap" hint="The vendor's served USD market cap.">
          <Figure
            m={cardFigure(card, "usd_market_cap", card.usd_market_cap, receivedAt)}
            format={(value) => usd(value, 0)}
          />
        </Field>
        <Field label="depth" hint="SOL in the bonding curve. This is what your exit has to move.">
          <Figure
            m={cardFigure(card, "sol_in_curve", card.sol_in_curve, receivedAt)}
            format={(value) => sol(value, 1)}
          />
        </Field>

        <Field
          label={`own exit @ ${decimals(card.clip_lamports / 1e9, 2)} SOL`}
          hint="How far your OWN exit moves the price at the desk's clip. An impact number without a size is not a number, so the size is in the label."
        >
          <Figure
            m={cardFigure(card, "own_exit_impact", card.own_exit_impact, receivedAt)}
            format={(value) => fractionAsPct(value, 2)}
            className={card.ghost_town ? "text-destructive" : undefined}
          />
        </Field>
        <Field label="last trade" hint="Age of the vendor's last-trade stamp at the sighting.">
          <Figure
            m={cardFigure(card, "trade_recency_s", card.trade_recency_s, receivedAt)}
            format={(value) => formatSpan(value)}
          />
        </Field>
        <Field
          label="two-sided"
          hint="Fraction of observed moves that reversed. Needs at least 3 sightings before it means anything; below that it is absent, not zero."
        >
          <span className="inline-flex items-baseline">
            <Figure
              m={cardFigure(card, "two_sided_frac", card.two_sided_frac, receivedAt, rateOrigin)}
              format={(value) => fractionAsPct(value, 0)}
            />
            <SampleN n={card.sightings} />
          </span>
        </Field>
        <Field
          label="wiggle"
          hint="Swings the desk's own estimator counted, at this coin's own round-trip cost as the zigzag threshold."
        >
          <span className="inline-flex items-baseline">
            <Figure
              m={cardFigure(card, "wiggle_n", card.wiggle_n, receivedAt, rateOrigin)}
              format={(value) => `${value}`}
            />
            <SampleN n={card.sightings} />
          </span>
        </Field>
      </div>

      {/* Its own row, because a social fact and a market measurement are different kinds
          of thing and this repo does not mix them into one register. Rendered even when
          empty: "nobody posted about this" is information, and dropping the row would make
          absence invisible. */}
      <div className="flex flex-wrap items-baseline gap-x-2 border-t border-border/50 px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          <Explain of={<span>callout</span>}>
            The most recent post naming this mint, from the intelligence store&apos;s last hour.
            PRESENCE AND RECENCY, NOT A COUNT — the feed dedupes by mint, so there is no number of
            callouts to show. Measured verdict: it locates <strong>volatility</strong>, not
            direction.
          </Explain>
        </span>
        <Figure m={calloutRecency(card, receivedAt)} format={(value) => `${formatSpan(value)} ago`} />
        {card.callout_kind && (
          <span className="font-mono text-[11px] text-muted-foreground">
            {card.callout_kind}
            {card.callout_author ? ` @${card.callout_author}` : ""}
          </span>
        )}
      </div>

      {card.gates_would_veto.length > 0 && (
        <p className="border-t border-border/50 px-3 py-1.5 text-[11px] text-muted-foreground">
          <Explain of={<span>the rule would refuse</span>}>
            These are the wiggle book&apos;s entry gates, evaluated at the middle of its jitter box
            and <strong>logged, not enforced</strong>. Nothing on this surface gates anything: the
            list is here so you can see which rule disagrees with you at the moment you overrule
            it, and the disagreement is what makes the comparison worth measuring.
          </Explain>
          : <span className="font-mono">{card.gates_would_veto.join(", ")}</span>
        </p>
      )}

      <HunchButtons
        onCapture={onCapture}
        onTyping={onTyping}
        capture={capture}
        busy={capture?.state === "posting"}
      />

      {capture?.state === "captured" && <Warnings receipt={capture.receipt} now={now} />}
      {capture?.state === "failed" && (
        <p className="border-t border-destructive/40 bg-destructive/5 px-3 py-2 font-mono text-[11px] text-destructive">
          not captured: {capture.error}
        </p>
      )}

      <button
        type="button"
        onClick={onToggle}
        className="border-t border-border/50 px-3 py-1 text-left font-mono text-[10px] uppercase tracking-wider text-muted-foreground hover:bg-muted"
      >
        {expanded ? "− collapse" : "+ full instrument"}
      </button>

      {expanded && <ReadoutView loaded={readout} mint={card.mint} />}
    </section>
  );
}

/**
 * The buttons.
 *
 * The note NEVER blocks the click. It is optional context and it sits beside the actions
 * rather than in front of them, because the normal path is a bare click and the whole
 * premise of this surface is that the operator stops typing hunches.
 */
function HunchButtons({
  onCapture,
  onTyping,
  capture,
  busy,
}: {
  onCapture: (kind: HunchKind, note: string) => void;
  onTyping: (value: boolean) => void;
  capture: Capture | undefined;
  busy: boolean;
}) {
  const [note, setNote] = useState("");
  const captured = capture?.state === "captured";

  const fire = (kind: HunchKind) => {
    onCapture(kind, note);
    setNote("");
  };

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border/50 px-3 py-2">
      <button
        type="button"
        disabled={busy}
        onClick={() => fire("wiggle")}
        className="rounded border border-primary/60 bg-primary/15 px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-primary hover:bg-primary/25 disabled:opacity-50"
      >
        {busy ? "…" : "wiggle"}
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => fire("down")}
        className="rounded border px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground hover:bg-muted disabled:opacity-50"
      >
        down
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => fire("watch")}
        className="rounded border px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground hover:bg-muted disabled:opacity-50"
      >
        watch
      </button>
      <Input
        value={note}
        placeholder="optional — in your own words"
        onChange={(event) => setNote(event.target.value)}
        onFocus={() => onTyping(true)}
        onBlur={() => onTyping(false)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            fire("wiggle");
          }
          if (event.key === "Escape") event.currentTarget.blur();
        }}
        className="h-7 min-w-[10rem] flex-1 font-mono text-[11px]"
      />
      {captured && (
        <StatusPill
          label="captured"
          tone="ok"
          help="The row is fsynced on the desk's tape. Nothing below can un-capture it."
        />
      )}
    </div>
  );
}

/** The server's own words about what was just captured. Loud, and never rewritten here. */
function Warnings({ receipt, now }: { receipt: HunchReceipt; now: number }) {
  const loud = receipt.warnings.filter((warning) => /^GHOST TOWN/.test(warning));
  const quiet = receipt.warnings.filter((warning) => !/^GHOST TOWN/.test(warning));
  return (
    <div className="space-y-1.5 border-t border-chart-3/40 bg-chart-3/5 px-3 py-2">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        captured {relativeAge(receipt.recorded_at, now)} ·{" "}
        <span className="normal-case">{receipt.hunch_id}</span>
      </p>
      {loud.map((warning) => (
        <p
          key={warning}
          className="rounded border border-destructive/50 bg-destructive/10 px-2 py-1 text-[11px] font-semibold leading-relaxed text-destructive"
        >
          {warning}
        </p>
      ))}
      {quiet.map((warning) => (
        <p key={warning} className="text-[11px] leading-relaxed text-chart-3">
          {warning}
        </p>
      ))}
      <p className="text-[11px] text-muted-foreground">{receipt.next}</p>
    </div>
  );
}

// ---------------------------------------------------------------------- the instrument

function ReadoutView({ loaded, mint }: { loaded: Loaded<ReadoutPayload> | undefined; mint: string }) {
  if (!loaded || loaded.state === "loading") {
    return (
      <div className="border-t border-border/50">
        <Absent reason="loading" detail="Polling the live vendor (hard deadline 2s)." />
      </div>
    );
  }
  if (loaded.state === "error") {
    return (
      <div className="border-t border-border/50">
        <Absent reason="error" detail={<p className="font-mono">{loaded.error}</p>} />
      </div>
    );
  }
  const readout = loaded.fetched.data.readout;
  const at = loaded.fetched.receivedAt;
  const vetoes = Object.entries(readout.gate_legs)
    .filter(([, ok]) => !ok)
    .map(([leg]) => leg)
    .sort();

  return (
    <div className="border-t border-border/50 bg-muted/20">
      <div className="grid grid-cols-2 gap-x-3 gap-y-2 px-3 py-2 sm:grid-cols-4">
        <Field label="price" hint="SOL per token off the curve reserves.">
          <Figure
            m={readoutFigure(readout, "price_sol", readout.price_sol, at)}
            format={(value) => value.toExponential(3)}
          />
        </Field>
        <Field label="round trip" hint="What a full in-and-out costs at the desk's clip on this coin.">
          <Figure
            m={readoutFigure(readout, "round_trip_cost", readout.round_trip_cost, at)}
            format={(value) => fractionAsPct(value, 2)}
          />
        </Field>
        <Field label="wiggle amp" hint="Log amplitude of the counted swings, at this coin's own round-trip cost.">
          <Figure
            m={readoutFigure(readout, "wiggle_amp", readout.wiggle_amp, at)}
            format={(value) => fractionAsPct(value, 1)}
          />
        </Field>
        <Field
          label="trade marks/h"
          hint="A LOWER BOUND. We only learn a trade happened by sampling after it, so a coin trading faster than the boards poll reads as the poll rate."
        >
          <span className="inline-flex items-baseline">
            <Figure
              m={readoutFigure(readout, "trade_marks_per_hour", readout.trade_marks_per_hour, at, {
                caveats: [
                  {
                    kind: "unbounded",
                    note: "Lower bound only: bounded above by the boards poll rate, not by the market.",
                  },
                ],
              })}
              format={(value) => decimals(value, 0)}
            />
            {readout.observations !== null && <SampleN n={readout.observations} />}
          </span>
        </Field>

        <Field label="observations" hint="Sightings of this mint on the boards in the last hour.">
          <Figure
            m={readoutFigure(readout, "observations", readout.observations, at)}
            format={(value) => `${value}`}
          />
        </Field>
        <Field label="obs / min">
          <Figure
            m={readoutFigure(readout, "obs_per_min", readout.obs_per_min, at)}
            format={(value) => decimals(value, 2)}
          />
        </Field>
        <Field
          label="callout"
          hint="Newest post naming this mint in the last hour. Presence and recency, not a count. An unreadable store renders as NOT WATCHING, which is a different thing from nobody having posted."
        >
          <Figure
            m={
              readout.absent.callouts
                ? unwatched<number>({
                    source: `${readoutPath(readout.mint)} → readout`,
                    path: "callout_last_s",
                    kind: "served",
                    clock: clockOf(null, at),
                    note: readout.absent.callouts,
                  })
                : readoutFigure(readout, "callout_last_s", readout.callout_last_s, at, {
                    note: "No post named this mint in the last hour. The callout feed's measured verdict is that it locates volatility, not direction.",
                  })
            }
            format={(value) => `${formatSpan(value)} ago`}
            suffix={
              readout.callout_kind ? (
                <span className="ml-1 text-[10px] text-muted-foreground">
                  {readout.callout_kind}
                  {readout.callout_author ? ` @${readout.callout_author}` : ""}
                </span>
              ) : undefined
            }
          />
        </Field>
        <Field
          label="crime cohort"
          hint="An offline LOOKUP, not a live screen: studies/crime_signatures.py labels on hourly candles with a 24h breakdown lag, so it can never speak about right now."
        >
          <Figure
            m={readoutFigure(readout, "crime_peak_mcap", readout.crime_peak_mcap, at, {
              kind: "config",
              note: "24h-lagged cohort label. Not a live verdict on this coin.",
            })}
            format={(value) => `peak ${usd(value, 0)}`}
          />
        </Field>
      </div>

      <p className="border-t border-border/50 px-3 py-1.5 text-[11px] text-muted-foreground">
        {vetoes.length > 0 ? (
          <>
            the rule would refuse: <span className="font-mono">{vetoes.join(", ")}</span> — advisory,
            at the middle of the jitter box. Nothing here gates.
          </>
        ) : (
          <>the wiggle rule would have taken this one too.</>
        )}
        {Object.keys(readout.absent).length > 0 && (
          <>
            {" · "}
            <span className="font-mono">
              absent: {Object.keys(readout.absent).sort().join(", ")}
            </span>
          </>
        )}
        {" · "}
        <span className="font-mono">
          {decimals(readout.elapsed_s * 1000, 0)} ms · {shortAddress(mint, 4, 4)}
        </span>
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------- clipboard bridge

/**
 * The transition-period affordance.
 *
 * The habit is: browse pump.fun, copy a contract address, paste it somewhere else. So when
 * this window regains focus — and on a slow poll while it holds focus — we look at the
 * clipboard, and if what is there DECODES to a 32-byte Solana address we resolve it and
 * pin that coin's card at the top with the buttons ready.
 *
 * Two rules, both load-bearing:
 *
 * 1. **Validate before requesting.** The decode happens client-side first (`isMint`), so a
 *    random copied sentence never becomes a query. And it is a decode, not a regex: this
 *    operator is targeted by an address-poisoning campaign, and base58 is case-sensitive —
 *    a lowercased address names a different account, which a charset test would wave
 *    through.
 * 2. **Never act.** The card appears, ready to click. Nothing is captured, nothing is
 *    opened. Show, don't trade.
 */
function useClipboardBridge({
  items,
  clip,
  setClip,
}: {
  items: CoinCard[];
  clip: ClipState;
  setClip: Dispatch<SetStateAction<ClipState>>;
}) {
  const lastText = useRef<string | null>(null);
  // The pin path wants whatever the grid last rendered without re-creating the poller
  // every 6 seconds — the clipboard cadence must not be coupled to the list cadence.
  const itemsRef = useRef(items);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const pin = useCallback(
    async (mint: string, resolution: Resolution | null) => {
      const known = itemsRef.current.find((item) => item.mint === mint);
      if (known) {
        setClip({
          kind: "pinned",
          card: known,
          resolution,
          readout: null,
          receivedAt: new Date().toISOString(),
        });
        return;
      }
      const loaded = await load(() => loadReadout(mint), readoutPath(mint));
      if (loaded.state === "ok") {
        setClip({
          kind: "pinned",
          card: loaded.fetched.data.card,
          resolution,
          readout: loaded.fetched.data.readout,
          receivedAt: loaded.fetched.receivedAt,
        });
      } else {
        setClip({ kind: "error", query: mint, error: errorText(loaded) });
      }
    },
    [setClip],
  );

  // A failed read must not take a card off the screen: switching the watch off is a fact
  // about the browser's permissions, not about the coin the operator is looking at.
  const goOff = useCallback(
    (reason: string) =>
      setClip((current) =>
        current.kind === "pinned" || current.kind === "refused" ? current : { kind: "off", reason },
      ),
    [setClip],
  );

  const inspect = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.clipboard?.readText) {
      goOff("this browser exposes no clipboard read");
      return;
    }
    let text: string;
    try {
      text = await navigator.clipboard.readText();
    } catch {
      // Rejected without permission or a user gesture. Silent by design — a thrown
      // clipboard error is not an event worth interrupting anyone over.
      goOff("the browser refused a clipboard read here");
      return;
    }
    const trimmed = text.trim();
    // De-duplicate: the same address twice in a row is one intention, not two.
    if (!trimmed || trimmed === lastText.current) return;
    lastText.current = trimmed;
    if (!isMint(trimmed)) return; // not an address; not our business
    setClip({ kind: "resolving", query: trimmed });
    const loaded = await load(() => loadResolution(trimmed), resolvePath(trimmed));
    if (loaded.state !== "ok") {
      setClip({ kind: "error", query: trimmed, error: errorText(loaded) });
      return;
    }
    const resolution = loaded.fetched.data;
    if (!resolution.mint) {
      setClip({ kind: "refused", resolution });
      return;
    }
    await pin(resolution.mint, resolution);
  }, [pin, setClip, goOff]);

  const off = clip.kind === "off";

  useEffect(() => {
    const onFocus = () => void inspect();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [inspect]);

  useEffect(() => {
    const timer = window.setInterval(
      () => {
        if (!document.hasFocus()) return;
        void inspect();
      },
      off ? CLIPBOARD_RETRY_MS : CLIPBOARD_MS,
    );
    return () => window.clearInterval(timer);
  }, [inspect, off]);

  const recheck = useCallback(() => {
    lastText.current = null;
    void inspect();
  }, [inspect]);

  const dismiss = useCallback(() => setClip({ kind: "idle" }), [setClip]);

  const pick = useCallback(
    (mint: string) => {
      setClip({ kind: "resolving", query: mint });
      void pin(mint, null);
    },
    [pin, setClip],
  );

  return { watching: !off, recheck, dismiss, pick };
}

function ClipboardPin({
  clip,
  watching,
  onRecheck,
  onDismiss,
  onPick,
  now,
  capture,
  captures,
  onTyping,
  expanded,
  onToggle,
  readouts,
}: {
  clip: ClipState;
  watching: boolean;
  onRecheck: () => void;
  onDismiss: () => void;
  onPick: (mint: string) => void;
  now: number;
  capture: (card: MaybeCard, kind: HunchKind, note: string, surface: string) => void;
  captures: Record<string, Capture>;
  onTyping: (value: boolean) => void;
  expanded: string | null;
  onToggle: (mint: string) => void;
  readouts: Record<string, Loaded<ReadoutPayload>>;
}) {
  const actions = (
    <>
      <StatusPill
        label={watching ? "clipboard watch on" : "clipboard watch off"}
        tone={watching ? "ok" : "idle"}
        help={
          watching
            ? "When this window has focus we look at the clipboard every 2.5s. Only text that DECODES to a 32-byte base58 address is ever sent anywhere, and finding one only shows the card — it never captures or trades."
            : clip.kind === "off"
              ? clip.reason
              : "Not reading the clipboard."
        }
      />
      <button
        type="button"
        onClick={onRecheck}
        className="rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider hover:bg-muted"
      >
        re-check
      </button>
      {clip.kind !== "idle" && clip.kind !== "off" && (
        <button
          type="button"
          onClick={onDismiss}
          className="rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider hover:bg-muted"
        >
          dismiss
        </button>
      )}
    </>
  );

  if (clip.kind === "idle" || clip.kind === "off") {
    return (
      <Panel title="From the clipboard" source={resolvePath("<address>")} actions={actions}>
        <p className="px-3 py-2 text-[11px] text-muted-foreground">
          Copy a contract address anywhere — pump.fun, a chat, a chart — and come back to this
          window. If it decodes to a real 32-byte address its card appears here with the buttons
          ready. Nothing is captured until you click.
        </p>
      </Panel>
    );
  }

  if (clip.kind === "resolving") {
    return (
      <Panel title="From the clipboard" source={resolvePath(clip.query)} actions={actions}>
        <Absent reason="loading" detail={`resolving ${shortAddress(clip.query, 6, 6)}`} />
      </Panel>
    );
  }

  if (clip.kind === "error") {
    return (
      <Panel title="From the clipboard" source={resolvePath(clip.query)} tone="alert" actions={actions}>
        <Absent reason="error" detail={<p className="font-mono">{clip.error}</p>} />
      </Panel>
    );
  }

  if (clip.kind === "refused") {
    return (
      <Panel
        title="From the clipboard — refused"
        source={resolvePath(clip.resolution.query)}
        tone="warn"
        actions={actions}
        note={
          <>
            The resolver <strong>refused rather than guessed</strong>. Pick the one you meant; it
            will not choose for you.
          </>
        }
      >
        <p className="px-3 pt-2 text-[11px] text-muted-foreground">{clip.resolution.reason}</p>
        {clip.resolution.candidates.length === 0 ? (
          <Absent reason="no-rows" detail="No source has seen anything matching that." />
        ) : (
          <ul className="flex flex-wrap gap-2 p-3">
            {clip.resolution.candidates.map((candidate) => (
              <li key={candidate.mint}>
                <button
                  type="button"
                  onClick={() => onPick(candidate.mint)}
                  className="rounded border px-2 py-1 text-left font-mono text-[11px] hover:bg-muted"
                >
                  <span className="font-semibold">
                    {candidate.symbol || candidate.name || shortAddress(candidate.mint, 6, 4)}
                  </span>
                  <span className="ml-2 text-muted-foreground">
                    {shortAddress(candidate.mint, 4, 4)} · {candidate.source}
                    {candidate.detail ? ` (${candidate.detail})` : ""}
                    {candidate.seconds_since_seen !== null
                      ? ` · ${formatSpan(candidate.seconds_since_seen)} ago`
                      : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    );
  }

  const card = clip.card;
  const mint = card.mint;
  return (
    <Panel
      title="From the clipboard"
      source={clip.resolution ? resolvePath(clip.resolution.query) : readoutPath(mint)}
      actions={actions}
      note={
        clip.resolution?.reason ? (
          <span className="text-chart-3">{clip.resolution.reason}</span>
        ) : undefined
      }
    >
      {isSighted(card) ? (
        <div className="p-3">
          <CoinCardView
            card={card}
            receivedAt={clip.receivedAt}
            now={now}
            expanded={expanded === mint}
            onToggle={() => onToggle(mint)}
            readout={readouts[mint]}
            capture={captures[mint]}
            onCapture={(kind, note) => capture(card, kind, note, "glass:clipboard")}
            onTyping={onTyping}
            pinned
          />
        </div>
      ) : (
        <UnsightedCardView
          card={card}
          readout={clip.readout}
          receivedAt={clip.receivedAt}
          now={now}
          capture={captures[mint]}
          onCapture={(kind, note) => capture(card, kind, note, "glass:clipboard")}
          onTyping={onTyping}
        />
      )}
    </Panel>
  );
}

/**
 * An address the operator supplied that no board has shown us.
 *
 * Deliberately still clickable: the resolver accepts a valid address whether or not our
 * tapes have seen it, because refusing an address the operator pasted would be the tool
 * substituting its own coverage for their knowledge. What it will not do is fill the empty
 * card with numbers — every figure here is absent, with the reason.
 */
function UnsightedCardView({
  card,
  readout,
  receivedAt,
  now,
  capture,
  onCapture,
  onTyping,
}: {
  card: { mint: string; absent: Record<string, string> };
  readout: Readout | null;
  receivedAt: string;
  now: number;
  capture: Capture | undefined;
  onCapture: (kind: HunchKind, note: string) => void;
  onTyping: (value: boolean) => void;
}) {
  const reasons = Object.entries(card.absent);
  return (
    <div className="space-y-2 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs font-semibold uppercase tracking-wider">
          {readout?.symbol || shortAddress(card.mint, 6, 4)}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground select-none">
          {shortAddress(card.mint, 4, 4)}
        </span>
        <StatusPill
          label="not on a board"
          tone="warn"
          help="This address is valid and accepted, but the collectors have no sighting of it in the index window. Every card figure is therefore absent — not zero."
        />
      </div>
      {reasons.map(([field, reason]) => (
        <p key={field} className="text-[11px] text-muted-foreground">
          <span className="font-mono">{field}</span>: {reason}
        </p>
      ))}
      {readout && (
        <div className="rounded border border-border/70">
          <ReadoutView
            loaded={{
              state: "ok",
              fetched: {
                data: { generated_at: receivedAt, card, readout },
                source: readoutPath(card.mint),
                receivedAt,
                latencyMs: 0,
              },
            }}
            mint={card.mint}
          />
        </div>
      )}
      <div className="rounded border border-border/70">
        <HunchButtons
          onCapture={onCapture}
          onTyping={onTyping}
          capture={capture}
          busy={capture?.state === "posting"}
        />
        {capture?.state === "captured" && <Warnings receipt={capture.receipt} now={now} />}
        {capture?.state === "failed" && (
          <p className="border-t border-destructive/40 bg-destructive/5 px-3 py-2 font-mono text-[11px] text-destructive">
            not captured: {capture.error}
          </p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------- the tape

const OUTCOME_TONE: Record<string, "ok" | "warn" | "bad" | "idle" | "info"> = {
  pending: "idle",
  accepted_awaiting_first_observation: "info",
  decided: "info",
  closed: "ok",
  recorded: "info",
  resolved: "ok",
  censored: "warn",
  falsifier_tripped: "bad",
  expired_before_the_desk_saw_it: "warn",
  never_observed_no_position_opened: "warn",
  already_holding_this_mint: "warn",
};

function TapePanel({ tape, now }: { tape: Loaded<HunchTape>; now: number }) {
  if (tape.state !== "ok") {
    return (
      <Panel title="Your tape" source={HUNCH_TAPE_PATH}>
        <Absent
          reason={tape.state === "error" ? "error" : "loading"}
          detail={tape.state === "error" ? <p className="font-mono">{tape.error}</p> : undefined}
        />
      </Panel>
    );
  }
  const rows = tape.fetched.data.items;
  const at = tape.fetched.receivedAt;
  return (
    <Panel
      title={`Your tape (${rows.length})`}
      source={HUNCH_TAPE_PATH}
      clock={clockOf(tape.fetched.data.generated_at, at)}
      now={now}
      note="Newest first, LIVE rows only. The state is what the OPERATOR book did with the gesture, joined off the ledger — a hunch with no answer yet is pending, never a zero-outcome row. The tape on disk is append-only: a retracted hunch disappears from this view and is still on the file, so a row leaving this list is not a deletion."
    >
      {rows.length === 0 ? (
        <Absent reason="no-rows" detail="No hunches on the tape yet. Click a coin above." />
      ) : (
        <ul className="divide-y divide-border/40">
          {rows.map((row) => (
            <li key={row.hunch_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5">
              <span className="font-mono text-[11px] font-semibold uppercase tracking-wider">
                {row.kind}
              </span>
              <span className="font-mono text-[11px]">
                {row.scope.symbol || shortAddress(row.scope.mint, 6, 4)}
              </span>
              <span className="font-mono text-[10px] text-muted-foreground select-none">
                {shortAddress(row.scope.mint, 4, 4)}
              </span>
              <span className="font-mono text-[10px] text-muted-foreground">
                {formatSpan(row.seconds_ago)} ago
              </span>
              <StatusPill
                label={row.outcome.state}
                tone={OUTCOME_TONE[row.outcome.state] ?? "idle"}
                help={row.outcome.censor_reason ?? row.outcome.exit_reason ?? undefined}
              />
              {row.outcome.net_return != null && (
                <Figure
                  m={observed(row.outcome.net_return, {
                    source: HUNCH_TAPE_PATH,
                    path: `items[].outcome.net_return`,
                    kind: "served",
                    clock: clockOf(row.t_event, at),
                    note: "Net of friction, off the operator book's close row.",
                  })}
                  format={(value) => fractionAsPct(value, 2)}
                  className={row.outcome.net_return >= 0 ? "text-lamp-ok" : "text-destructive"}
                />
              )}
              {row.utterance ? (
                <span className="truncate text-[11px] italic text-muted-foreground">
                  “{row.utterance}”
                </span>
              ) : (
                <span className="text-[11px] text-muted-foreground/60">
                  (no utterance — you pointed)
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
