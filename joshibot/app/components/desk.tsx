import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { DeskBag } from "@/lib/desk";
import { bookTotalSol, liveRunnerLine, scaleRungsLabel, shareOfBook, waitingGraduation } from "@/lib/desk";
import type { Policy } from "@/lib/types";
import { cn, number, shortAddress } from "@/lib/utils";

export function PageKicker({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[10px] font-medium uppercase tracking-[0.22em] text-primary/85">
      {children}
    </p>
  );
}

export function PageTitle({ children }: { children: ReactNode }) {
  return <h2 className="font-display mt-1 text-[2.15rem] font-medium leading-[1.1] tracking-tight">{children}</h2>;
}

export function PageLede({ children }: { children: ReactNode }) {
  return <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-muted-foreground">{children}</p>;
}

export function Lamp({
  tone,
  live = false,
  className,
}: {
  tone: "ok" | "warn" | "bad" | "idle";
  live?: boolean;
  className?: string;
}) {
  const color =
    tone === "ok"
      ? "text-lamp-ok"
      : tone === "warn"
        ? "text-lamp-warn"
        : tone === "bad"
          ? "text-lamp-bad"
          : "text-muted-foreground/50";
  return <span className={cn("lamp", live && "lamp-live", color, className)} />;
}

export function BookBar({
  bags,
  onPick,
}: {
  bags: DeskBag[];
  onPick?: (mint: string) => void;
}) {
  const total = bookTotalSol(bags);
  if (!bags.length || total <= 0) {
    return (
      <div className="flex h-10 items-center rounded-full border border-dashed px-4 text-xs text-muted-foreground">
        No quoted book yet.
      </div>
    );
  }
  return (
    <div className="flex h-10 overflow-hidden rounded-full border">
      {bags.map((bag, index) => {
        const share = shareOfBook(bag, total) ?? 0;
        if (share <= 0) return null;
        const palette = ["bg-primary", "bg-chart-2", "bg-chart-3", "bg-chart-5", "bg-chart-4"];
        return (
          <button
            key={bag.mint}
            type="button"
            title={`${bag.name} · ${number(bag.exit_sol, 4)} SOL`}
            onClick={() => onPick?.(bag.mint)}
            className={cn(
              "relative h-full min-w-2 transition-opacity hover:opacity-90",
              palette[index % palette.length],
              bag.kind === "observe" && "opacity-70",
            )}
            style={{ width: `${Math.max(share, 3)}%` }}
          />
        );
      })}
    </div>
  );
}

export function BagCard({
  bag,
  share,
  policyLabel,
  policy,
  onChart,
  onProtect,
  onDelete,
  deleting = false,
  limits,
}: {
  bag: DeskBag;
  share: number | null;
  policyLabel: string;
  policy?: Policy;
  onChart: () => void;
  onProtect: () => void;
  onDelete?: () => void;
  deleting?: boolean;
  limits?: ReactNode;
}) {
  const tape = liveRunnerLine(bag, policy);
  const scaled = scaleRungsLabel(bag.scale_rungs_fired);
  const bonding = waitingGraduation(bag.decision_reason);
  return (
    <Card className="rise-in overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="font-display text-xl font-medium">{bag.name}</CardTitle>
            <CardDescription className="mt-1 font-mono text-[10px]">{shortAddress(bag.mint)}</CardDescription>
          </div>
          <Lamp tone={bag.rug_emergency ? "bad" : bag.kind === "observe" ? "warn" : "ok"} live={bag.rug_emergency} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">Quoted exit</p>
          <p className="font-mono tnum text-3xl font-medium tracking-tight">
            {number(bag.exit_sol, 4)}
            <span className="ml-1 text-sm text-muted-foreground">SOL</span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {share != null ? `${number(share, 1)}% of book` : "unquoted"} · {number(bag.ui_amount, 2)} tokens
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant={bag.kind === "observe" ? "warning" : "default"}>{policyLabel}</Badge>
          {bag.rug_emergency && <Badge variant="destructive">rug</Badge>}
          {bag.mint_revoked === true && <Badge variant="outline">mint revoked</Badge>}
          {bag.mint_revoked === false && <Badge variant="warning">mint live</Badge>}
          {bonding && <Badge variant="warning">waiting graduation</Badge>}
          {bag.kind === "protected" && !bag.stop_live && (
            <Badge variant="warning">SL warming</Badge>
          )}
          {scaled && <Badge variant="outline">{scaled}</Badge>}
        </div>
        {tape && <p className="font-mono tnum text-[11px] text-muted-foreground">{tape}</p>}
        {limits}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={onChart}>
            Chart
          </Button>
          <Button size="sm" variant="outline" onClick={onProtect}>
            {bag.kind === "protected" ? "More…" : "Protect"}
          </Button>
          {bag.kind === "protected" && onDelete && (
            <Button size="sm" variant="destructive" disabled={deleting} onClick={onDelete}>
              {deleting ? "Removing…" : "Delete rule"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function EmptyRoom({ title, lede }: { title: string; lede: string }) {
  return (
    <div className="rounded-xl border border-dashed px-6 py-14 text-center">
      <p className="font-display text-2xl">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">{lede}</p>
    </div>
  );
}
