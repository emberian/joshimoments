import { useMemo, useState } from "react";

import { ClockPair, Figure } from "@/components/figure";
import {
  Absent,
  Copyable,
  Panel,
  Scroller,
  StatusPill,
  Table,
  Td,
  Th,
} from "@/components/instrument";
import { EVENTS_PATH, TRADES_PATH, type Loaded } from "@/lib/api";
import { loadedClock, originOf } from "@/lib/desk";
import { cn, decimals, lamportsToSol, shortAddress, stampUtc } from "@/lib/format";
import { observed, unobserved, type Measured } from "@/lib/measure";
import type { EventRow, Severity, TradeRow } from "@/lib/types";

type Entry =
  | { kind: "event"; at: string; row: EventRow }
  | { kind: "trade"; at: string; row: TradeRow };

const SEVERITIES: Severity[] = ["info", "warning", "critical"];

export function History({
  events: eventsLoad,
  trades: tradesLoad,
  now,
}: {
  events: Loaded<{ items: EventRow[] }>;
  trades: Loaded<{ items: TradeRow[] }>;
  now: number;
}) {
  const [severities, setSeverities] = useState<Set<Severity>>(new Set(SEVERITIES));
  const [showTrades, setShowTrades] = useState(true);
  const [query, setQuery] = useState("");

  const events = useMemo(
    () => (eventsLoad.state === "ok" ? eventsLoad.fetched.data.items : []),
    [eventsLoad],
  );
  const trades = useMemo(
    () => (tradesLoad.state === "ok" ? tradesLoad.fetched.data.items : []),
    [tradesLoad],
  );

  const entries = useMemo(() => {
    const all: Entry[] = [
      ...events.map((row) => ({ kind: "event" as const, at: row.timestamp, row })),
      ...(showTrades ? trades.map((row) => ({ kind: "trade" as const, at: row.timestamp, row })) : []),
    ];
    const needle = query.trim().toLowerCase();
    return all
      .filter((entry) => {
        if (entry.kind === "event" && !severities.has(entry.row.severity)) return false;
        if (!needle) return true;
        const haystack =
          entry.kind === "event"
            ? `${entry.row.message} ${entry.row.category} ${JSON.stringify(entry.row.context ?? {})}`
            : `${entry.row.name} ${entry.row.mint} ${entry.row.reason} ${entry.row.signature}`;
        return haystack.toLowerCase().includes(needle);
      })
      .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
  }, [events, trades, severities, showTrades, query]);

  const toggle = (severity: Severity) => {
    setSeverities((current) => {
      const next = new Set(current);
      if (next.has(severity)) next.delete(severity);
      else next.add(severity);
      return next;
    });
  };

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    for (const row of events) result[row.severity] = (result[row.severity] ?? 0) + 1;
    return result;
  }, [events]);

  return (
    <Panel
      title="Tape"
      source={`${EVENTS_PATH} + ${TRADES_PATH}`}
      clock={loadedClock(eventsLoad)}
      now={now}
      note={
        <>
          Events and executed trades on one timeline, newest first. Timestamps here are the
          sentinel&apos;s own event stamps; a trade&apos;s stamp is when the engine recorded the fill,
          not the block time of the transaction — open the signature on chain for that.
        </>
      }
      actions={
        <div className="flex flex-wrap items-center gap-1.5">
          {SEVERITIES.map((severity) => (
            <button
              key={severity}
              type="button"
              onClick={() => toggle(severity)}
              className={cn(
                "rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
                severities.has(severity)
                  ? severity === "critical"
                    ? "border-destructive/60 bg-destructive/15 text-destructive"
                    : severity === "warning"
                      ? "border-chart-3/60 bg-chart-3/15 text-chart-3"
                      : "border-border bg-muted text-foreground"
                  : "text-muted-foreground/50",
              )}
            >
              {severity} {counts[severity] ?? 0}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setShowTrades((value) => !value)}
            className={cn(
              "rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
              showTrades ? "border-primary/60 bg-primary/15 text-primary" : "text-muted-foreground/50",
            )}
          >
            trades {trades.length}
          </button>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="filter…"
            className="w-36 rounded border bg-background px-2 py-0.5 font-mono text-[11px]"
          />
        </div>
      }
    >
      {eventsLoad.state === "error" ? (
        <Absent reason="error" detail={<p className="font-mono">{eventsLoad.error}</p>} />
      ) : entries.length === 0 ? (
        <Absent
          reason="no-rows"
          detail={
            events.length + trades.length > 0
              ? "Every row is filtered out by the current selection."
              : "The journal answered with no rows."
          }
        />
      ) : (
        <Scroller>
          <Table>
            <thead>
              <tr>
                <Th>time (utc)</Th>
                <Th>kind</Th>
                <Th>category</Th>
                <Th>detail</Th>
                <Th align="right">value</Th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, index) =>
                entry.kind === "event" ? (
                  <EventLine
                    key={`e-${entry.row.timestamp}-${index}`}
                    row={entry.row}
                    now={now}
                    load={eventsLoad}
                  />
                ) : (
                  <TradeLine
                    key={`t-${entry.row.signature}`}
                    row={entry.row}
                    now={now}
                    load={tradesLoad}
                  />
                ),
              )}
            </tbody>
          </Table>
        </Scroller>
      )}
    </Panel>
  );
}

function EventLine({
  row,
  now,
  load,
}: {
  row: EventRow;
  now: number;
  load: Loaded<{ items: EventRow[] }>;
}) {
  const context = row.context ?? {};
  const keys = Object.keys(context);
  return (
    <tr className="hover:bg-muted/30">
      <Td>
        <span className="font-mono text-[11px]">{stampUtc(row.timestamp)}</span>
        <div className="text-[10px] text-muted-foreground">
          <ClockPair clock={loadedClock(load, row.timestamp)} now={now} compact />
        </div>
      </Td>
      <Td>
        <StatusPill
          label={row.severity}
          tone={row.severity === "critical" ? "bad" : row.severity === "warning" ? "warn" : "idle"}
        />
      </Td>
      <Td>
        <span className="font-mono text-[11px] text-muted-foreground">{row.category}</span>
      </Td>
      <Td>
        <span className="text-[11px]">{row.message}</span>
        {keys.length > 0 && (
          <div className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[10px] text-muted-foreground">
            {keys.map((key) => (
              <span key={key}>
                {key}={String(context[key]).slice(0, 60)}
              </span>
            ))}
          </div>
        )}
      </Td>
      <Td align="right">
        <span className="text-muted-foreground">—</span>
      </Td>
    </tr>
  );
}

function TradeLine({
  row,
  now,
  load,
}: {
  row: TradeRow;
  now: number;
  load: Loaded<{ items: TradeRow[] }>;
}) {
  const clock = loadedClock(load, row.timestamp);
  const proceeds = lamportsToSol(row.output_lamports);
  const measured: Measured<number> =
    proceeds == null
      ? unobserved(
          originOf(load, "trades[].output_lamports", clock, {
            note: "The recorded fill carried no parseable proceeds.",
          }),
        )
      : observed(
          proceeds,
          originOf(load, "trades[].output_lamports", clock, {
            kind: "derived",
            note: "output_lamports ÷ 1e9. This is the realised SOL received, before any basis comparison.",
          }),
        );

  return (
    <tr className="bg-primary/5 hover:bg-primary/10">
      <Td>
        <span className="font-mono text-[11px]">{stampUtc(row.timestamp)}</span>
        <div className="text-[10px] text-muted-foreground">
          <ClockPair clock={clock} now={now} compact />
        </div>
      </Td>
      <Td>
        <StatusPill label="trade" tone="info" help="An executed sell recorded by the engine." />
      </Td>
      <Td>
        <span className="font-mono text-[11px] text-muted-foreground">{row.reason}</span>
      </Td>
      <Td>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px]">{row.name}</span>
          <Copyable
            value={row.mint}
            display={<span className="text-[10px] text-muted-foreground">{shortAddress(row.mint)}</span>}
          />
          <a
            href={`https://solscan.io/tx/${row.signature}`}
            target="_blank"
            rel="noreferrer noopener"
            className="font-mono text-[10px] text-muted-foreground underline decoration-dotted underline-offset-4 hover:text-primary"
          >
            {shortAddress(row.signature, 6, 6)} ↗
          </a>
        </div>
        {row.input_amount && (
          <div className="font-mono text-[10px] text-muted-foreground">
            sold {row.input_amount} raw units
          </div>
        )}
      </Td>
      <Td align="right">
        <Figure m={measured} format={(value) => `${decimals(value, 6)} SOL`} />
      </Td>
    </tr>
  );
}

