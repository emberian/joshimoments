import type { ReactNode } from "react";

import { ClockPair, Explain } from "@/components/figure";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn, relativeAge } from "@/lib/format";
import type { Clock } from "@/lib/measure";

/**
 * A panel that names its own producer.
 *
 * Every instrument on this console states which endpoint or CLI it is reading
 * and when that read happened, in the chrome, so nothing on screen is anonymous.
 */
export function Panel({
  title,
  source,
  clock,
  now,
  note,
  actions,
  children,
  className,
  tone = "neutral",
}: {
  title: ReactNode;
  source?: string;
  clock?: Clock;
  now?: number;
  note?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  tone?: "neutral" | "alert" | "warn";
}) {
  return (
    <section
      className={cn(
        "flex min-w-0 flex-col rounded-lg border bg-card/60",
        tone === "alert" && "border-destructive/60 bg-destructive/5",
        tone === "warn" && "border-chart-3/50 bg-chart-3/5",
        className,
      )}
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border/70 px-3 py-2">
        <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em]">{title}</h2>
        {source && (
          <code className="rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
            {source}
          </code>
        )}
        {clock && now !== undefined && <ClockPair clock={clock} now={now} />}
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      </header>
      {note && (
        <p className="border-b border-border/70 px-3 py-1.5 text-[11px] text-muted-foreground">
          {note}
        </p>
      )}
      <div className="min-w-0 flex-1">{children}</div>
    </section>
  );
}

/** A labelled slot in a dense readout grid. */
export function Field({
  label,
  children,
  hint,
  className,
}: {
  label: ReactNode;
  children: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 space-y-0.5", className)}>
      <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {hint ? <Explain of={label}>{hint}</Explain> : label}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function FieldGrid({
  columns = 4,
  children,
  className,
}: {
  columns?: 2 | 3 | 4 | 5 | 6;
  children: ReactNode;
  className?: string;
}) {
  const cols = {
    2: "sm:grid-cols-2",
    3: "sm:grid-cols-2 lg:grid-cols-3",
    4: "sm:grid-cols-2 lg:grid-cols-4",
    5: "sm:grid-cols-3 lg:grid-cols-5",
    6: "sm:grid-cols-3 lg:grid-cols-6",
  }[columns];
  return <div className={cn("grid grid-cols-1 gap-x-4 gap-y-3 p-3", cols, className)}>{children}</div>;
}

export function Lamp({
  tone,
  live = false,
  title,
}: {
  tone: "ok" | "warn" | "bad" | "idle";
  live?: boolean;
  title?: string;
}) {
  const color = {
    ok: "text-lamp-ok",
    warn: "text-lamp-warn",
    bad: "text-lamp-bad",
    idle: "text-muted-foreground",
  }[tone];
  return <span className={cn("lamp shrink-0", color, live && "lamp-live")} title={title} />;
}

/** A status pill whose meaning is explained on hover rather than in a legend. */
export function StatusPill({
  label,
  tone,
  help,
  className,
}: {
  label: ReactNode;
  tone: "ok" | "warn" | "bad" | "idle" | "info";
  help?: ReactNode;
  className?: string;
}) {
  const tones = {
    ok: "bg-lamp-ok/15 text-lamp-ok",
    warn: "bg-chart-3/15 text-chart-3",
    bad: "bg-destructive/15 text-destructive",
    idle: "bg-muted text-muted-foreground",
    info: "bg-chart-2/15 text-chart-2",
  }[tone];
  const pill = (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        tones,
        help && "cursor-help",
        className,
      )}
    >
      {label}
    </span>
  );
  if (!help) return pill;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{pill}</TooltipTrigger>
      <TooltipContent>
        <div className="text-xs">{help}</div>
      </TooltipContent>
    </Tooltip>
  );
}

/** Horizontal scroll container: wide instrument tables must not scroll the page. */
export function Scroller({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("min-w-0 overflow-x-auto", className)}>{children}</div>;
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <table className={cn("w-full border-collapse text-left text-xs", className)}>{children}</table>
  );
}

export function Th({
  children,
  hint,
  align = "left",
  className,
}: {
  children?: ReactNode;
  hint?: ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <th
      className={cn(
        "whitespace-nowrap border-b border-border/70 px-3 py-1.5 font-mono text-[10px] font-medium uppercase tracking-wider text-muted-foreground",
        align === "right" && "text-right",
        className,
      )}
    >
      {hint ? <Explain of={children}>{hint}</Explain> : children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  className,
  colSpan,
}: {
  children?: ReactNode;
  align?: "left" | "right";
  className?: string;
  colSpan?: number;
}) {
  return (
    <td
      colSpan={colSpan}
      className={cn(
        "border-b border-border/40 px-3 py-1.5 align-top",
        align === "right" && "text-right",
        className,
      )}
    >
      {children}
    </td>
  );
}

/**
 * The empty state that is NOT a zero.
 *
 * Used wherever a collection is empty, to say which of "nothing happened" and
 * "nothing is being recorded" is true.
 */
export function Absent({
  reason,
  detail,
}: {
  reason: "no-rows" | "not-wired" | "error" | "loading";
  detail?: ReactNode;
}) {
  const copy = {
    "no-rows": "Producer answered with zero rows.",
    "not-wired": "No producer is wired for this view.",
    error: "The producer errored.",
    loading: "Reading…",
  }[reason];
  return (
    <div className="px-3 py-6 text-center">
      <p
        className={cn(
          "font-mono text-[11px] uppercase tracking-wider",
          reason === "error" ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {copy}
      </p>
      {detail && <div className="mx-auto mt-2 max-w-xl text-xs text-muted-foreground">{detail}</div>}
    </div>
  );
}

/** A copyable mint/signature/address. Investigation starts by grabbing the id. */
export function Copyable({
  value,
  display,
  className,
}: {
  value: string;
  display?: ReactNode;
  className?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={() => void navigator.clipboard?.writeText(value)}
          className={cn(
            "font-mono text-xs underline decoration-dotted decoration-muted-foreground/40 underline-offset-4 hover:text-primary hover:decoration-primary",
            className,
          )}
        >
          {display ?? value}
        </button>
      </TooltipTrigger>
      <TooltipContent>
        <p className="font-mono text-[11px] break-all">{value}</p>
        <p className="mt-1 text-[11px] text-muted-foreground">Click to copy.</p>
      </TooltipContent>
    </Tooltip>
  );
}

export function Freshness({
  at,
  now,
  ttlSeconds,
}: {
  at: string | null;
  now: number;
  ttlSeconds?: number | null;
}) {
  if (!at) return <span className="font-mono text-[11px] text-muted-foreground">never</span>;
  const elapsed = (now - new Date(at).getTime()) / 1000;
  const tone =
    !ttlSeconds || !Number.isFinite(elapsed)
      ? "text-muted-foreground"
      : elapsed <= ttlSeconds
        ? "text-lamp-ok"
        : elapsed <= ttlSeconds * 3
          ? "text-chart-3"
          : "text-destructive";
  return <span className={cn("font-mono text-[11px]", tone)}>{relativeAge(at, now)}</span>;
}
