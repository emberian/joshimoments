import { useEffect, useMemo, useState } from "react";

import { PageKicker, PageLede, PageTitle } from "@/components/desk";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { loadCandles } from "@/lib/api";
import { deskBags, parseSol } from "@/lib/desk";
import type { CandleBar, Snapshot } from "@/lib/types";
import { number, shortAddress } from "@/lib/utils";

const INTERVALS = ["5m", "15m", "1h", "4h", "1d"] as const;

export function Markets({ snapshot, selectedMint = null }: { snapshot: Snapshot | null; selectedMint?: string | null }) {
  const tokens = useMemo(() => deskBags(snapshot), [snapshot]);
  const [localMint, setLocalMint] = useState<string | null>(null);
  const [interval, setInterval] = useState<(typeof INTERVALS)[number]>("15m");
  const [bars, setBars] = useState<CandleBar[]>([]);
  const [stats, setStats] = useState<Record<string, number | null> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selected = selectedMint ?? localMint ?? tokens[0]?.mint ?? null;
  const token = tokens.find((item) => item.mint === selected);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    void loadCandles(selected, interval)
      .then((payload) => {
        if (!cancelled) {
          setBars(payload.bars);
          setStats(payload.stats ?? null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setBars([]);
          setError(err instanceof Error ? err.message : "candles unavailable");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selected, interval]);

  const last = bars.at(-1);
  const first = bars[0];
  const change =
    last && first && first.c
      ? ((last.c - first.c) / first.c) * 100
      : null;

  return (
    <div className="space-y-6">
      <div>
        <PageKicker>Markets</PageKicker>
        <PageTitle>History / candles</PageTitle>
        <PageLede>
          History / candles are proxied through the local sentinel from DexScreener windows (m5/h1/h6/h24). The browser
          never talks to that host.
        </PageLede>
      </div>
      <div className="flex flex-wrap gap-2">
        {tokens.map((item) => (
          <Button
            key={item.mint}
            size="sm"
            variant={item.mint === selected ? "default" : "outline"}
            onClick={() => setLocalMint(item.mint)}
          >
            {item.name}
            <span className="font-mono tnum text-[10px] opacity-70">{number(item.exit_sol, 3)}</span>
          </Button>
        ))}
        {!tokens.length && <p className="text-sm text-muted-foreground">No holdings to chart.</p>}
      </div>
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle className="font-display text-2xl font-medium">{token?.name ?? "Select a token"}</CardTitle>
            <CardDescription className="font-mono">{token ? shortAddress(token.mint) : "—"}</CardDescription>
          </div>
          <div className="flex gap-1">
            {INTERVALS.map((item) => (
              <Button key={item} size="sm" variant={item === interval ? "default" : "ghost"} onClick={() => setInterval(item)}>
                {item}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <Badge variant="outline">last {last ? number(last.c, 6) : "—"} USD</Badge>
            {change != null && (
              <span className={change < 0 ? "text-destructive" : "text-primary"}>{number(change, 1)}% window</span>
            )}
            {stats?.change_h24 != null && <span>24h {number(stats.change_h24, 1)}%</span>}
            {stats?.liquidity_usd != null && <span>liq ${number(stats.liquidity_usd, 0)}</span>}
            {stats?.volume_h24 != null && <span>vol ${number(stats.volume_h24, 0)}</span>}
            {parseSol(token?.exit_sol) != null && <span>exit {number(token?.exit_sol, 4)} SOL</span>}
          </div>
          <div className="h-[380px] w-full">
            {bars.length ? (
              <CandleStrip bars={bars} />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                {error ?? "No candle history for this mint yet."}
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function CandleStrip({ bars }: { bars: CandleBar[] }) {
  const pad = { top: 12, right: 12, bottom: 8, left: 12 };
  const width = 920;
  const height = 360;
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const lows = bars.map((bar) => bar.l);
  const highs = bars.map((bar) => bar.h);
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const span = max - min || 1;
  const gap = innerW / bars.length;
  const body = Math.max(2, gap * 0.62);
  const y = (value: number) => pad.top + ((max - value) / span) * innerH;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" aria-label="candles">
      {bars.map((bar, index) => {
        const x = pad.left + index * gap + gap / 2;
        const up = bar.c >= bar.o;
        const color = up ? "var(--primary)" : "var(--destructive)";
        const top = y(Math.max(bar.o, bar.c));
        const bottom = y(Math.min(bar.o, bar.c));
        return (
          <g key={`${bar.t}-${index}`}>
            <line x1={x} x2={x} y1={y(bar.h)} y2={y(bar.l)} stroke={color} strokeWidth={1} />
            <rect
              x={x - body / 2}
              y={top}
              width={body}
              height={Math.max(1, bottom - top)}
              fill={color}
              opacity={up ? 0.85 : 0.7}
            />
          </g>
        );
      })}
    </svg>
  );
}
