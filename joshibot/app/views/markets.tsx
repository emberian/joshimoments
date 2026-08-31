import { useEffect, useMemo, useState } from "react";

import { Figure } from "@/components/figure";
import { useNow } from "@/components/now";
import {
  Absent,
  Copyable,
  Field,
  FieldGrid,
  Panel,
  StatusPill,
} from "@/components/instrument";
import { PriceChart, hoverTime, shapeOf, useHover } from "@/components/pricechart";
import { CANDLES_PATH, loadCandles, type Loaded } from "@/lib/api";
import { snapshotOf } from "@/lib/desk";
import { NO_DATA, cn, decimals, shortAddress, stampUtc, usd } from "@/lib/format";
import { clockOf, observed, unobserved, type Measured, type Origin } from "@/lib/measure";
import type { CandlePayload, Snapshot } from "@/lib/types";

export function Markets({
  snapshot: loaded,
  selectedMint = null,
  onSelect,
}: {
  snapshot: Loaded<Snapshot>;
  selectedMint?: string | null;
  onSelect: (mint: string) => void;
}) {
  const snapshot = snapshotOf(loaded);
  const tokens = useMemo(() => {
    if (!snapshot) return [];
    return [
      ...snapshot.positions.map((row) => ({ mint: row.mint, name: row.name })),
      ...snapshot.unmonitored.map((row) => ({ mint: row.mint, name: row.name })),
    ];
  }, [snapshot]);

  const selected = selectedMint ?? tokens[0]?.mint ?? null;
  const [payload, setPayload] = useState<CandlePayload | null>(null);
  const [receivedAt, setReceivedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useHover();
  const now = useNow();

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    void loadCandles(selected)
      .then((fetched) => {
        if (cancelled) return;
        setPayload(fetched.data);
        setReceivedAt(fetched.receivedAt);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setPayload(null);
        setError(err instanceof Error ? err.message : "candles unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const bars = payload?.bars ?? [];
  const shape = shapeOf(bars);
  const clock = clockOf(
    bars.length ? new Date(bars[bars.length - 1].t * 1000).toISOString() : null,
    receivedAt,
  );
  const statOrigin = (path: string, note?: string): Origin => ({
    source: CANDLES_PATH,
    path,
    kind: "served",
    clock,
    note,
  });

  const stats = payload?.stats ?? {};
  const stat = (key: string, note?: string): Measured<number> => {
    const value = stats[key];
    return value == null
      ? unobserved(statOrigin(`stats.${key}`, note))
      : observed(value, statOrigin(`stats.${key}`, note));
  };

  return (
    <div className="space-y-3">
      <Panel title="Instrument" source="/api/snapshot → positions[] + unmonitored[]">
        <div className="flex flex-wrap gap-1.5 p-3">
          {tokens.map((token) => (
            <button
              key={token.mint}
              type="button"
              onClick={() => onSelect(token.mint)}
              className={cn(
                "rounded border px-2 py-1 font-mono text-[11px]",
                token.mint === selected
                  ? "border-primary/60 bg-primary/15 text-primary"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              {token.name}
            </button>
          ))}
          {!tokens.length && (
            <span className="text-xs text-muted-foreground">No holdings to chart.</span>
          )}
        </div>
      </Panel>

      {!selected ? (
        <Panel title="Price" source={CANDLES_PATH}>
          <Absent reason="no-rows" detail="Select an instrument." />
        </Panel>
      ) : (
        <Panel
          title={`Price · ${payload?.mint ? shortAddress(payload.mint) : shortAddress(selected)}`}
          source={CANDLES_PATH}
          clock={clock}
          now={now}
          tone={shape === "reconstructed-path" ? "warn" : "neutral"}
          actions={
            payload && (
              <>
                <StatusPill label={payload.source} tone="idle" />
                {payload.dex && <StatusPill label={payload.dex} tone="idle" />}
              </>
            )
          }
          note={
            shape === "reconstructed-path" ? (
              <>
                <strong className="text-chart-3">This is not an OHLC series.</strong>{" "}
                <code className="font-mono">/api/candles</code> back-solves at most five prior
                prices out of DexScreener&apos;s percentage windows (m5 / h1 / h6 / h24) as{" "}
                <code className="font-mono">price ÷ (1 + pct/100)</code>, and emits each one with
                open = high = low = close and volume 0. Drawn as candlesticks those become five doji
                over a flat volume pane, which reads as a quiet market when the truth is that no
                high, low, or volume was ever measured. It is drawn as what it is: a handful of
                reconstructed points. The line between them is interpolation, not observed movement.
              </>
            ) : undefined
          }
        >
          {error ? (
            <Absent reason="error" detail={<p className="font-mono">{error}</p>} />
          ) : !bars.length ? (
            <Absent reason="no-rows" detail="No price history reconstructed for this mint." />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border/70 px-3 py-1.5 font-mono text-[11px]">
                {hover ? (
                  <>
                    <span className="text-muted-foreground">{hoverTime(hover.time)}</span>
                    <span>
                      close{" "}
                      {hover.close < 0.01 ? hover.close.toExponential(4) : decimals(hover.close, 6)}
                    </span>
                    {hover.high != null && hover.low != null && (
                      <span className="text-muted-foreground">
                        h {hover.high.toExponential(4)} · l {hover.low.toExponential(4)}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-muted-foreground">
                    {bars.length} point{bars.length === 1 ? "" : "s"} · hover for values · log price
                    scale
                  </span>
                )}
              </div>
              <PriceChart bars={bars} shape={shape} onHover={setHover} />
            </>
          )}
        </Panel>
      )}

      <Panel
        title="Served statistics"
        source={`${CANDLES_PATH} → stats`}
        clock={clock}
        now={now}
        note="These are the aggregator's own window statistics, and unlike the price path they were measured rather than reconstructed. They carry ingest time only — no block time — so they must not be joined against chain events."
      >
        <FieldGrid columns={4}>
          <Field label="price usd">
            <Figure
              m={stat("price_usd", "DexScreener's current price for the chosen pair.")}
              format={(value) => (value < 0.01 ? value.toExponential(4) : usd(value, 6))}
            />
          </Field>
          <Field label="liquidity usd">
            <Figure m={stat("liquidity_usd")} format={(value) => usd(value, 0)} />
          </Field>
          <Field label="volume 24h">
            <Figure m={stat("volume_h24")} format={(value) => usd(value, 0)} />
          </Field>
          <Field label="fdv">
            <Figure m={stat("fdv")} format={(value) => usd(value, 0)} />
          </Field>
          {(["m5", "h1", "h6", "h24"] as const).map((window) => (
            <Field key={window} label={`change ${window}`}>
              <Figure
                m={stat(
                  `change_${window}`,
                  "The percentage window the price path above is reconstructed from. This is the measurement; the path is the inference.",
                )}
                format={(value) => `${decimals(value, 2)}%`}
                className={
                  stats[`change_${window}`] == null
                    ? undefined
                    : (stats[`change_${window}`] ?? 0) >= 0
                      ? "text-lamp-ok"
                      : "text-destructive"
                }
              />
            </Field>
          ))}
          <Field label="volume per bar" hint="Every reconstructed bar carries v = 0 as a filler.">
            <Figure
              m={unobserved({
                source: CANDLES_PATH,
                path: "bars[].v",
                kind: "served",
                clock,
                note: "The reconstruction emits v = 0 for every bar. No per-bar volume is measured anywhere in this path, so it is shown as absent rather than as zero volume.",
              })}
            />
          </Field>
          <Field label="pair">
            {payload?.mint ? (
              <Copyable value={payload.mint} display={shortAddress(payload.mint)} />
            ) : (
              <span className="font-mono text-xs text-muted-foreground">{NO_DATA}</span>
            )}
          </Field>
          <Field label="fetched">
            <span className="font-mono text-[11px]">{stampUtc(receivedAt)}</span>
          </Field>
        </FieldGrid>
      </Panel>
    </div>
  );
}
