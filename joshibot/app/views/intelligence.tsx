import { useState } from "react";

import { Figure } from "@/components/figure";
import {
  Absent,
  Copyable,
  Field,
  FieldGrid,
  Panel,
  Scroller,
  StatusPill,
  Table,
  Td,
  Th,
} from "@/components/instrument";
import { INTELLIGENCE_BASE_URL } from "@/lib/intelligence";
import { cn, relativeAge, shortAddress, stampUtc } from "@/lib/format";
import { clockOf, observed, unwatched, type Measured } from "@/lib/measure";
import type { EvidenceClass, IntelEvidence, IntelligenceSnapshot } from "@/lib/types";

const CLASSES: EvidenceClass[] = ["fact", "claim", "speculation"];

export function Intelligence({
  intel,
  now,
}: {
  intel: IntelligenceSnapshot | null;
  now: number;
}) {
  const [classes, setClasses] = useState<Set<EvidenceClass>>(new Set(CLASSES));
  const [onlyWatched, setOnlyWatched] = useState(false);

  if (!intel) {
    return (
      <Panel title="Wire" source={INTELLIGENCE_BASE_URL}>
        <Absent reason="loading" />
      </Panel>
    );
  }

  const clock = clockOf(intel.service.last_cycle_at, null);
  const reachable = intel.reachable;

  /**
   * A service that did not answer has NOT reported zero. Every counter is a
   * `Measured` so an unreachable collector cannot render as a quiet one.
   */
  const counter = (value: number | null, path: string, note?: string): Measured<number> =>
    !reachable
      ? unwatched({
          source: `${INTELLIGENCE_BASE_URL}/health`,
          path,
          kind: "served",
          clock,
          note: "The intelligence service did not answer. This is not a report of zero.",
        })
      : value == null
        ? unwatched({ source: `${INTELLIGENCE_BASE_URL}/health`, path, kind: "served", clock, note })
        : observed(value, {
            source: `${INTELLIGENCE_BASE_URL}/health`,
            path,
            kind: "served",
            clock,
            note,
          });

  const items = intel.inbox.filter((item) => {
    if (!classes.has(item.classification)) return false;
    if (onlyWatched && !item.watched_handle) return false;
    return true;
  });

  return (
    <div className="space-y-3">
      <Panel
        title="Intelligence service"
        source={INTELLIGENCE_BASE_URL}
        clock={clock}
        now={now}
        tone={reachable ? "neutral" : "warn"}
        actions={
          <StatusPill
            label={intel.service.status}
            tone={
              !reachable ? "idle" : intel.service.status === "healthy" ? "ok" : "warn"
            }
            help={
              reachable
                ? intel.service.last_error ?? undefined
                : "No response on the intelligence port. Every counter below is shown as not-watching rather than zero."
            }
          />
        }
        note={
          <>
            A separate process on port 8788. Everything it produces is evidence, never an
            instruction: nothing on this page can reach an execution path, and cashtags stay labels
            rather than resolving to mints on their own.
          </>
        }
      >
        <FieldGrid columns={4}>
          <Field label="collectors active">
            <Figure m={counter(intel.service.collectors_active, "runtime.collectors_active")} emphasis="strong" />
          </Field>
          <Field label="x items today">
            <Figure m={counter(intel.service.x_items_today, "runtime.x_items_today")} emphasis="strong" />
          </Field>
          <Field label="last cycle">
            {intel.service.last_cycle_at ? (
              <div>
                <div className="font-mono text-sm">{relativeAge(intel.service.last_cycle_at, now)}</div>
                <div className="font-mono text-[10px] text-muted-foreground">
                  {stampUtc(intel.service.last_cycle_at)}
                </div>
              </div>
            ) : (
              <span className="font-mono text-xs text-muted-foreground">never</span>
            )}
          </Field>
          <Field label="cycle state">
            <div className="flex flex-wrap gap-1">
              {intel.service.cycle_in_progress && <StatusPill label="running" tone="info" />}
              {intel.service.last_cycle_partial && (
                <StatusPill
                  label="partial"
                  tone="warn"
                  help="The last cycle did not complete every collector, so the feed below is an incomplete view of the window."
                />
              )}
              {!intel.service.cycle_in_progress && !intel.service.last_cycle_partial && (
                <StatusPill label="idle" tone="idle" />
              )}
            </div>
          </Field>
        </FieldGrid>
        {intel.service.last_error && (
          <p className="border-t border-border/70 px-3 py-2 font-mono text-xs text-destructive">
            {intel.service.last_error}
          </p>
        )}
      </Panel>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title={`Sources (${intel.sources.length})`} source={`${INTELLIGENCE_BASE_URL}/sources`}>
          {intel.sources.length === 0 ? (
            <Absent reason={reachable ? "no-rows" : "not-wired"} />
          ) : (
            <Scroller>
              <Table>
                <thead>
                  <tr>
                    <Th>source</Th>
                    <Th>status</Th>
                  </tr>
                </thead>
                <tbody>
                  {intel.sources.map((source) => (
                    <tr key={source.id} className="hover:bg-muted/30">
                      <Td>
                        <span className="font-mono text-[11px]">{source.label}</span>
                        <div className="font-mono text-[10px] text-muted-foreground">{source.id}</div>
                      </Td>
                      <Td>
                        <StatusPill
                          label={source.status}
                          tone={source.status === "healthy" || source.status === "ok" ? "ok" : "warn"}
                        />
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Scroller>
          )}
        </Panel>

        <Panel title={`Watchlists (${intel.watchlists.length})`} source={`${INTELLIGENCE_BASE_URL}/watchlists`}>
          {intel.watchlists.length === 0 ? (
            <Absent reason={reachable ? "no-rows" : "not-wired"} />
          ) : (
            <Scroller>
              <Table>
                <thead>
                  <tr>
                    <Th>watchlist</Th>
                    <Th align="right" hint="null means the service did not report a count — not that the list is empty.">
                      members
                    </Th>
                  </tr>
                </thead>
                <tbody>
                  {intel.watchlists.map((list) => (
                    <tr key={list.id} className="hover:bg-muted/30">
                      <Td>
                        <span className="font-mono text-[11px]">{list.name}</span>
                      </Td>
                      <Td align="right">
                        <Figure
                          m={counter(list.member_count, `watchlists[${list.id}].member_count`)}
                        />
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Scroller>
          )}
        </Panel>
      </div>

      <Panel
        title={`Evidence (${items.length}/${intel.inbox.length})`}
        source={`${INTELLIGENCE_BASE_URL}/intelligence/feed?limit=50`}
        note="Classification is assigned by this client from the item kind, and is a reading aid rather than a claim the upstream service made. Contradicting evidence is not reconciled anywhere: two rows may disagree and both are shown."
        actions={
          <div className="flex flex-wrap gap-1.5">
            {CLASSES.map((klass) => (
              <button
                key={klass}
                type="button"
                onClick={() =>
                  setClasses((current) => {
                    const next = new Set(current);
                    if (next.has(klass)) next.delete(klass);
                    else next.add(klass);
                    return next;
                  })
                }
                className={cn(
                  "rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
                  classes.has(klass) ? toneFor(klass) : "text-muted-foreground/50",
                )}
              >
                {klass}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setOnlyWatched((value) => !value)}
              className={cn(
                "rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
                onlyWatched ? "border-primary/60 bg-primary/15 text-primary" : "text-muted-foreground/50",
              )}
            >
              watched handles
            </button>
          </div>
        }
      >
        {items.length === 0 ? (
          <Absent
            reason={reachable ? "no-rows" : "not-wired"}
            detail={
              reachable
                ? "No evidence matches the current filter."
                : "The intelligence service is not answering, so no evidence is available. This is distinct from a quiet wire."
            }
          />
        ) : (
          <Scroller>
            <Table>
              <thead>
                <tr>
                  <Th>class</Th>
                  <Th>observed (event t)</Th>
                  <Th>item</Th>
                  <Th>labels</Th>
                  <Th>effect</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <EvidenceLine key={item.id} item={item} now={now} />
                ))}
              </tbody>
            </Table>
          </Scroller>
        )}
      </Panel>

      {intel.candidates.length > 0 && (
        <Panel
          title={`Sieve candidates (${intel.candidates.length})`}
          source={`${INTELLIGENCE_BASE_URL}/intelligence/candidates`}
          note="Verdicts from the candidate sieve. execution_effect is 'none' on every row by construction — this plane cannot buy anything."
        >
          <Scroller>
            <Table>
              <thead>
                <tr>
                  <Th>mint</Th>
                  <Th>verdict</Th>
                  <Th>reasons</Th>
                  <Th>effect</Th>
                </tr>
              </thead>
              <tbody>
                {intel.candidates.map((card) => (
                  <tr key={card.mint} className="hover:bg-muted/30">
                    <Td>
                      <Copyable
                        value={card.mint}
                        display={<span className="font-mono text-[11px]">{card.name ?? shortAddress(card.mint)}</span>}
                      />
                    </Td>
                    <Td>
                      <StatusPill
                        label={card.verdict}
                        tone={card.verdict === "skip" ? "idle" : "warn"}
                      />
                    </Td>
                    <Td>
                      <span className="text-[11px] text-muted-foreground">
                        {card.reasons.join(" · ") || "—"}
                      </span>
                    </Td>
                    <Td>
                      <StatusPill label={card.execution_effect} tone="idle" />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Scroller>
        </Panel>
      )}
    </div>
  );
}

function toneFor(klass: EvidenceClass) {
  return klass === "fact"
    ? "border-lamp-ok/60 bg-lamp-ok/15 text-lamp-ok"
    : klass === "claim"
      ? "border-chart-3/60 bg-chart-3/15 text-chart-3"
      : "border-border bg-muted text-muted-foreground";
}

function EvidenceLine({ item, now }: { item: IntelEvidence; now: number }) {
  return (
    <tr className="hover:bg-muted/30">
      <Td>
        <span
          className={cn(
            "inline-flex rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
            toneFor(item.classification),
          )}
        >
          {item.classification}
        </span>
      </Td>
      <Td>
        {item.observed_at ? (
          <div>
            <span className="font-mono text-[11px]">{relativeAge(item.observed_at, now)}</span>
            <div className="font-mono text-[10px] text-muted-foreground">
              {stampUtc(item.observed_at)}
            </div>
          </div>
        ) : (
          <span className="font-mono text-[11px] text-muted-foreground">no stamp</span>
        )}
      </Td>
      <Td>
        <div className="flex flex-wrap items-center gap-2">
          {item.author && <span className="font-mono text-[11px] text-primary">@{item.author}</span>}
          <span className="font-mono text-[10px] text-muted-foreground">{item.kind}</span>
          {item.url && (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer noopener"
              className="font-mono text-[10px] text-muted-foreground underline decoration-dotted underline-offset-4 hover:text-primary"
            >
              source ↗
            </a>
          )}
        </div>
        <p className="mt-0.5 max-w-2xl text-[11px] text-muted-foreground">{item.summary}</p>
      </Td>
      <Td>
        <div className="flex flex-wrap gap-1">
          {item.watched_handle && (
            <StatusPill label={`@${item.watched_handle}`} tone="info" help="A watched handle." />
          )}
          {item.cashtags.map((tag) => (
            <StatusPill
              key={tag}
              label={tag}
              tone="idle"
              help="Cashtags stay labels. They are never resolved to a mint automatically — a ticker is not an identifier."
            />
          ))}
          {item.mint_candidates.slice(0, 2).map((mint) => (
            <Copyable
              key={mint}
              value={mint}
              display={<span className="text-[10px] text-muted-foreground">{shortAddress(mint)}</span>}
            />
          ))}
        </div>
      </Td>
      <Td>
        <StatusPill
          label="none"
          tone="idle"
          help="Evidence has no execution effect. Nothing on this plane can open, close, or size a position."
        />
      </Td>
    </tr>
  );
}
