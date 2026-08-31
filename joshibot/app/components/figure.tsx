import type { ReactNode } from "react";

import { useNow } from "@/components/now";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { NO_DATA, cn, relativeAge, stampUtc } from "@/lib/format";
import {
  type Caveat,
  type Clock,
  type Measured,
  type Origin,
  caveatsOf,
  clockIsProxied,
  worstCaveat,
} from "@/lib/measure";

/**
 * The only sanctioned way to put a number on screen.
 *
 * Renders a `Measured<T>` so that "measured zero", "watched but never sampled",
 * "not watching" and "the producer errored" are four visually distinct things,
 * and hangs the full provenance off a hover.
 */
export function Figure<T>({
  m,
  format,
  className,
  emphasis = "normal",
  suffix,
}: {
  m: Measured<T>;
  format?: (value: T) => string;
  className?: string;
  emphasis?: "normal" | "strong" | "quiet";
  suffix?: ReactNode;
}) {
  const caveats = caveatsOf(m.origin);
  const worst = worstCaveat(caveats);
  const weight =
    emphasis === "strong" ? "text-2xl font-medium" : emphasis === "quiet" ? "text-xs" : "text-sm";

  let body: ReactNode;
  let tone = "";
  if (m.state === "observed") {
    body = format ? format(m.value) : String(m.value);
  } else if (m.state === "unobserved") {
    body = NO_DATA;
    tone = "text-muted-foreground";
  } else if (m.state === "unwatched") {
    body = "not watching";
    tone = "text-muted-foreground/60 italic text-[0.85em]";
  } else {
    body = "error";
    tone = "text-destructive";
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "tnum cursor-help font-mono underline decoration-dotted decoration-muted-foreground/40 underline-offset-4 hover:decoration-foreground/70",
            weight,
            tone,
            className,
          )}
        >
          {body}
          {suffix}
          {worst && <CaveatMark caveat={worst} />}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <ProvenanceCard m={m} caveats={caveats} />
      </TooltipContent>
    </Tooltip>
  );
}

function CaveatMark({ caveat }: { caveat: Caveat }) {
  const tone =
    caveat.kind === "retracted" || caveat.kind === "disagreement"
      ? "text-destructive"
      : caveat.kind === "thin-sample" || caveat.kind === "unbounded"
        ? "text-chart-3"
        : "text-muted-foreground";
  return <sup className={cn("ml-0.5 not-italic", tone)}>†</sup>;
}

/** The hover card: where the number came from, when, and what is wrong with it. */
export function ProvenanceCard<T>({ m, caveats }: { m: Measured<T>; caveats: Caveat[] }) {
  const origin = m.origin;
  const now = useNow();
  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <StateTag state={m.state} />
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          {origin.kind}
        </span>
      </div>

      {m.state === "unobserved" && (
        <p className="text-muted-foreground">
          This producer is being watched and has never yielded a sample. It is not zero.
        </p>
      )}
      {m.state === "unwatched" && (
        <p className="text-muted-foreground">
          Nothing is watching this. Absence here carries no information at all — it is not a
          measurement of zero.
        </p>
      )}
      {m.state === "error" && <p className="text-destructive">{m.error}</p>}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-muted-foreground">source</dt>
        <dd className="font-mono break-all">{origin.source}</dd>
        {origin.path && (
          <>
            <dt className="text-muted-foreground">field</dt>
            <dd className="font-mono break-all">{origin.path}</dd>
          </>
        )}
        <dt className="text-muted-foreground">event t</dt>
        <dd className="font-mono">
          {origin.clock.event ? (
            <>
              {stampUtc(origin.clock.event)}{" "}
              <span className="text-muted-foreground">({relativeAge(origin.clock.event, now)})</span>
            </>
          ) : (
            <span className="text-muted-foreground">none published</span>
          )}
        </dd>
        <dt className="text-muted-foreground">ingest t</dt>
        <dd className="font-mono">
          {origin.clock.ingest ? (
            <>
              {stampUtc(origin.clock.ingest)}{" "}
              <span className="text-muted-foreground">
                ({relativeAge(origin.clock.ingest, now)})
              </span>
            </>
          ) : (
            <span className="text-muted-foreground">none published</span>
          )}
        </dd>
        {origin.ttlSeconds != null && (
          <>
            <dt className="text-muted-foreground">ttl</dt>
            <dd className="font-mono">{origin.ttlSeconds}s</dd>
          </>
        )}
        {origin.sample && (
          <>
            <dt className="text-muted-foreground">sample</dt>
            <dd className="font-mono">
              n={origin.sample.n}
              {origin.sample.window ? ` · ${origin.sample.window}` : ""}
            </dd>
          </>
        )}
      </dl>

      {origin.note && <p className="text-muted-foreground">{origin.note}</p>}

      {caveats.length > 0 && (
        <ul className="space-y-1 border-t border-border pt-2">
          {caveats.map((caveat) => (
            <li key={`${caveat.kind}-${caveat.note.slice(0, 12)}`} className="flex gap-2">
              <CaveatTag kind={caveat.kind} />
              <span className="text-muted-foreground">{caveat.note}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StateTag({ state }: { state: Measured<unknown>["state"] }) {
  const label =
    state === "observed"
      ? "observed"
      : state === "unobserved"
        ? "no sample"
        : state === "unwatched"
          ? "not watching"
          : "error";
  const tone =
    state === "observed"
      ? "bg-lamp-ok/15 text-lamp-ok"
      : state === "error"
        ? "bg-destructive/15 text-destructive"
        : "bg-muted text-muted-foreground";
  return (
    <span className={cn("rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider", tone)}>
      {label}
    </span>
  );
}

export function CaveatTag({ kind }: { kind: Caveat["kind"] }) {
  const tone =
    kind === "retracted" || kind === "disagreement"
      ? "bg-destructive/15 text-destructive"
      : kind === "thin-sample" || kind === "unbounded"
        ? "bg-chart-3/15 text-chart-3"
        : "bg-muted text-muted-foreground";
  return (
    <span
      className={cn(
        "shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        tone,
      )}
    >
      {kind}
    </span>
  );
}

/**
 * Both clocks, side by side, always.
 *
 * When a producer publishes one timestamp as both, this says PROXIED rather than
 * showing a 0ms lag — a fabricated latency is worse than an admitted gap.
 */
export function ClockPair({
  clock,
  now,
  compact: dense = false,
}: {
  clock: Clock;
  now: number;
  compact?: boolean;
}) {
  const proxied = clockIsProxied(clock);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-help font-mono text-[11px]">
          <span className={clock.event ? "" : "text-muted-foreground"}>
            {clock.event ? relativeAge(clock.event, now) : "never"}
          </span>
          {!dense && (
            <span className="ml-1.5 text-muted-foreground/70">
              {proxied ? "· proxied" : clock.ingest ? `· ingest ${relativeAge(clock.ingest, now)}` : ""}
            </span>
          )}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <div className="space-y-1.5 text-xs">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted-foreground">event t</dt>
            <dd className="font-mono">{stampUtc(clock.event)}</dd>
            <dt className="text-muted-foreground">ingest t</dt>
            <dd className="font-mono">{stampUtc(clock.ingest)}</dd>
          </dl>
          {proxied ? (
            <p className="text-chart-3">
              PROXIED — the producer publishes one timestamp as both. This is when the sentinel
              heard, not a measured block time. Do not read a latency from it.
            </p>
          ) : (
            <p className="text-muted-foreground">
              Event time is chain/block time. Ingest time is when this process learned it. Backfill
              runs ingest order backwards against chain order, so differencing them across sources
              fabricates latency.
            </p>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

/** The netmap's three-way flow evidence, rendered as three different things. */
export function EvidenceTag({
  evidence,
  note,
}: {
  evidence: "observed" | "observed_zero" | "not_watching";
  note?: string;
}) {
  const spec = {
    observed: { label: "observed", tone: "bg-lamp-ok/15 text-lamp-ok", help: "Flow crossed this edge inside a watch window." },
    observed_zero: {
      label: "observed zero",
      tone: "bg-chart-2/15 text-chart-2",
      help: "Watched, and nothing crossed. This is a real measured zero.",
    },
    not_watching: {
      label: "not watching",
      tone: "bg-muted text-muted-foreground",
      help: "No watch coverage in the window. Flow here is UNKNOWN, not zero.",
    },
  }[evidence];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex shrink-0 cursor-help rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
            spec.tone,
          )}
        >
          {spec.label}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p className="text-xs">{spec.help}</p>
        {note && <p className="mt-1 text-xs text-muted-foreground">{note}</p>}
      </TooltipContent>
    </Tooltip>
  );
}

/** Inline explainer for any label that needs one, without stealing layout space. */
export function Explain({ children, of }: { children: ReactNode; of: ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-help underline decoration-dotted decoration-muted-foreground/40 underline-offset-4">
          {of}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <div className="text-xs">{children}</div>
      </TooltipContent>
    </Tooltip>
  );
}

/** Convenience: build an Origin without repeating the boilerplate at every call. */
export function origin(
  source: string,
  path: string | undefined,
  clock: Clock,
  extra: Partial<Origin> = {},
): Origin {
  return { source, path, kind: "served", clock, ...extra };
}
