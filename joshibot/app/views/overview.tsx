import { useState } from "react";

import { BagCard, BookBar, Lamp, PageKicker, PageLede, PageTitle } from "@/components/desk";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { protectUnmonitored } from "@/lib/api";
import { bookTotalSol, deskBags, FEE_TANK_SOL, feeTank, gateLamps, parseSol, policyFor, policyRuleLabel, shareOfBook } from "@/lib/desk";
import type { IntelligenceSnapshot, Policy, ProtectUnmonitoredResult, Snapshot, UnmonitoredRow } from "@/lib/types";
import { age, cn, number } from "@/lib/utils";

export function Overview({
  snapshot,
  policies,
  intel,
  now,
  onChanged,
  onChart,
  onBags,
}: {
  snapshot: Snapshot | null;
  policies: Policy[];
  intel: IntelligenceSnapshot | null;
  now: number;
  onChanged: () => void;
  onChart: (mint: string) => void;
  onBags: () => void;
}) {
  const bags = deskBags(snapshot);
  const gates = snapshot?.system.gate_failures ?? [];
  const lamps = gateLamps(gates);
  const live = snapshot?.system.mode === "live";
  const unmonitored = snapshot?.unmonitored.length ?? 0;
  const tank = feeTank(snapshot?.wallet.sol);
  const total = bookTotalSol(bags);
  const whisper = intel?.x_tape[0] ?? intel?.inbox[0] ?? null;

  return (
    <div className="space-y-6">
      <div>
        <PageKicker>Overview</PageKicker>
        <PageTitle>
          The exit door, <span className="italic text-primary">kept open.</span>
        </PageTitle>
        <PageLede>
          The browser observes. The local process decides. The <strong className="text-foreground">shitcoims</strong> key
          never crosses that boundary.
        </PageLede>
      </div>

      <UnmonitoredBanner snapshot={snapshot} onChanged={onChanged} />
      <BookClimb sol={snapshot?.wallet.sol} book={snapshot?.wallet.portfolio_exit_sol} />

      <div className="grid gap-3 md:grid-cols-4">
        <Stat
          label="Native SOL"
          value={number(snapshot?.wallet.sol, 4)}
          hint={tank === "ok" ? "fee tank ready" : tank === "low" ? `below ${FEE_TANK_SOL} SOL · exits may fail` : "no gas"}
          tone={tank === "ok" ? undefined : "critical"}
        />
        <Stat label="Quoted exits" value={`${number(snapshot?.wallet.portfolio_exit_sol, 3)} SOL`} hint="full-balance Jupiter quotes" />
        <Stat label="Protected" value={String(snapshot?.positions.length ?? 0)} hint="explicit YAML policies" />
        <Stat
          label="Observe-only"
          value={String(unmonitored)}
          hint={unmonitored ? "will not auto-exit" : "every bag has a rule"}
          tone={unmonitored > 0 ? "critical" : undefined}
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-end justify-between gap-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">The book</p>
          <p className="font-mono tnum text-xs text-muted-foreground">{number(total, 4)} SOL quoted</p>
        </div>
        <BookBar bags={bags} onPick={onChart} />
        <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
          {bags.map((bag, index) => (
            <span key={bag.mint} className="flex items-center gap-1.5">
              <span className={cn("size-1.5 rounded-full", ["bg-primary", "bg-chart-2", "bg-chart-3", "bg-chart-5"][index % 4])} />
              {bag.name}
            </span>
          ))}
        </div>
      </div>

      {bags.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {bags.map((bag) => {
            const policy = policyFor(policies, bag.mint);
            return (
              <BagCard
                key={bag.mint}
                bag={bag}
                share={shareOfBook(bag, total)}
                policy={policy}
                policyLabel={policyRuleLabel(policy, bag)}
                onChart={() => onChart(bag.mint)}
                onProtect={onBags}
              />
            );
          })}
        </div>
      ) : (
        <p className="rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">No token inventory.</p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>PANIC PREVIEW</CardTitle>
            <CardDescription>A live panic would attempt to sell these bags to SOL. Nothing was sold. CANNOT EXECUTE.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {live ? <Badge variant="warning">signer armed</Badge> : <Badge variant="warning">dry-run lock</Badge>}
              <Badge variant="outline">{snapshot?.system.protection_state ?? "STARTING"}</Badge>
              <Badge variant={live ? "warning" : "destructive"}>{live ? "preview still cannot execute" : "CANNOT EXECUTE"}</Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              gate_failures: {gates.length ? gates.join(" · ") : "none reported"}.{" "}
              {gates.length
                ? "All three live gates are currently closed."
                : "All three live gates are open. This preview still sells nothing."}
            </p>
            <ul className="divide-y text-sm">
              {bags.map((bag) => (
                <li key={bag.mint} className="flex items-center justify-between py-2">
                  <span>{bag.name}</span>
                  <span className="font-mono tnum text-xs">{number(bag.exit_sol, 4)} SOL</span>
                </li>
              ))}
              {!bags.length && <li className="py-6 text-center text-muted-foreground">No token inventory.</li>}
            </ul>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Live gates</CardTitle>
              <CardDescription>Three keys. All must turn before a sell can exist.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {lamps.map((gate) => (
                <div key={gate.id} className="flex items-center justify-between gap-3 text-sm">
                  <div className="flex items-center gap-2">
                    <Lamp tone={gate.closed ? "bad" : "ok"} />
                    <span className="font-mono text-xs">{gate.label}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">{gate.closed ? "closed" : "open"}</span>
                </div>
              ))}
              <p className="text-xs text-muted-foreground">
                Gas {number(snapshot?.wallet.sol, 4)} SOL
                {tank !== "ok" ? ` — live exits may fail below ${FEE_TANK_SOL}.` : " — enough for a priority fee."}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Room tone</CardTitle>
              <CardDescription>
                {whisper
                  ? `Wire ${age(whisper.observed_at, now)} · ${intel?.service.x_items_today ?? 0} X today`
                  : "Observatory is quiet."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {whisper && (
                <p className="text-sm leading-relaxed">
                  <span className="font-mono text-primary">{whisper.author ? `@${whisper.author}` : whisper.kind}</span>
                  <span className="text-muted-foreground"> — {whisper.summary}</span>
                </p>
              )}
              <ul className="space-y-2 text-sm">
                {(snapshot?.events ?? []).slice(0, 4).map((event, index) => (
                  <li key={`${event.timestamp}-${index}`} className="flex gap-2">
                    <Lamp tone={event.severity === "critical" ? "bad" : event.severity === "warning" ? "warn" : "idle"} />
                    <span className="text-muted-foreground">{event.message}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

export function UnmonitoredBanner({
  snapshot,
  onChanged,
}: {
  snapshot: Snapshot | null;
  onChanged?: () => void;
}) {
  const rows = snapshot?.unmonitored ?? [];
  const [protecting, setProtecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProtectUnmonitoredResult | null>(null);
  if (rows.length === 0) return null;

  const count = rows.length;
  const heading = count === 1 ? "1 bag has no exit policy" : `${count} bags have no exit policy`;
  const quoted = rows.reduce((sum, row) => sum + (parseSol(row.exit_sol) ?? 0), 0);

  const protect = async () => {
    setProtecting(true);
    setError(null);
    setResult(null);
    try {
      const next = await protectUnmonitored({ mode: "rug_only" }, rows);
      setResult(next);
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "protect failed");
    } finally {
      setProtecting(false);
    }
  };

  return (
    <Card className="border-destructive/70 bg-destructive/10 shadow-[0_0_0_1px_color-mix(in_oklab,var(--destructive)_30%,transparent)]">
      <CardHeader>
        <div className="flex flex-wrap gap-2">
          <Badge variant="destructive">No exit policy</Badge>
          <Badge variant="warning">{snapshot?.system.protection_state ?? "OBSERVE_ONLY"}</Badge>
          <Badge variant="destructive">Not live-armed</Badge>
          <Badge variant="destructive">CANNOT EXECUTE</Badge>
        </div>
        <CardTitle className="font-display text-2xl font-medium text-destructive">{heading}</CardTitle>
        <CardDescription className="text-destructive/90">
          Rug detection and stop-loss will NOT sell {count === 1 ? "this bag" : "these bags"}. Nothing auto-exits.
          This is not live-armed. A click here writes YAML only — it does not sell.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="divide-y divide-destructive/20 text-sm">
          {rows.map((row) => (
            <UnmonitoredLine key={row.mint} row={row} />
          ))}
        </ul>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="space-y-1">
            <Button type="button" variant="outline" disabled={protecting} onClick={() => void protect()}>
              {protecting ? "Writing YAML…" : "Protect with quoted exits as basis"}
            </Button>
            <p className="text-xs text-muted-foreground">Writes config.yaml only. Cannot execute. Cannot arm.</p>
          </div>
          <p className="font-mono tnum text-xs text-muted-foreground">{number(quoted, 4)} SOL would be sealed from here</p>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {result && (
          <div className="space-y-1 text-xs text-muted-foreground">
            <p>
              Wrote {result.created.length} {result.created.length === 1 ? "policy" : "policies"} to config.yaml.
              Cannot execute. Cannot arm.
            </p>
            {result.skipped.length > 0 && (
              <ul className="list-disc pl-4">
                {result.skipped.map((item) => (
                  <li key={item.mint}>
                    skipped {item.mint}: {item.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function BookClimb({ sol, book }: { sol?: string | null; book?: string | null }) {
  const native = parseSol(sol) ?? 0;
  const quoted = parseSol(book) ?? 0;
  const total = native + quoted;
  const target = 18;
  const pct = Math.max(0, Math.min(100, (total / target) * 100));
  const multiple = total > 0 ? target / total : null;
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardDescription>Climb · 3 weeks · rent</CardDescription>
        <CardTitle className="font-mono tnum text-2xl">
          {number(total, 3)} <span className="text-sm text-muted-foreground">/ {target} SOL</span>
        </CardTitle>
        <p className="text-[11px] text-muted-foreground">
          {multiple != null ? `${number(multiple, 1)}× from here.` : "No book yet."} Need a few runners to 2–4×,
          not a 40-hypothesis Sharpe. Unprotected bags cannot help.
        </p>
      </CardHeader>
      <CardContent>
        <div className="h-2 overflow-hidden rounded-full bg-muted">
          <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
        </div>
      </CardContent>
    </Card>
  );
}

function UnmonitoredLine({ row }: { row: UnmonitoredRow }) {
  return (
    <li className="flex items-center justify-between py-2">
      <span className="font-medium">{row.name}</span>
      <span className="font-mono tnum text-xs">{number(row.exit_sol, 4)} SOL quoted exit</span>
    </li>
  );
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "critical";
}) {
  return (
    <Card className={tone === "critical" ? "border-destructive bg-destructive/10" : undefined}>
      <CardHeader className="pb-3">
        <CardDescription className={tone === "critical" ? "text-destructive" : undefined}>{label}</CardDescription>
        <CardTitle className={`font-mono tnum text-2xl ${tone === "critical" ? "text-destructive" : ""}`}>{value}</CardTitle>
        {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
      </CardHeader>
    </Card>
  );
}
