import { useMemo } from "react";

import { Figure } from "@/components/figure";
import {
  Absent,
  Field,
  FieldGrid,
  Panel,
  Scroller,
  StatusPill,
  Table,
  Td,
  Th,
} from "@/components/instrument";
import { PERFORMANCE_PATH, TRADES_PATH, type Loaded } from "@/lib/api";
import { loadedClock, originOf } from "@/lib/desk";
import { NO_DATA, decimals, lamportsToSol, relativeAge, stampUtc } from "@/lib/format";
import { fromDecimalString, observed, unobserved, type Measured } from "@/lib/measure";
import type { Performance as PerformanceData, TradeRow } from "@/lib/types";

/** The server reads at most this many rows to build the summary. */
const SUMMARY_WINDOW = 500;

export function Performance({
  performance: loaded,
  trades: tradesLoad,
  now,
}: {
  performance: Loaded<PerformanceData>;
  trades: Loaded<{ items: TradeRow[] }>;
  now: number;
}) {
  const data = loaded.state === "ok" ? loaded.fetched.data : null;
  const trades = useMemo(
    () => (tradesLoad.state === "ok" ? tradesLoad.fetched.data.items : []),
    [tradesLoad],
  );
  const clock = loadedClock(loaded, data?.last_exit_at ?? null);

  const byReason = useMemo(() => {
    const map = new Map<string, { count: number; proceeds: number }>();
    for (const trade of trades) {
      const proceeds = lamportsToSol(trade.output_lamports) ?? 0;
      const current = map.get(trade.reason) ?? { count: 0, proceeds: 0 };
      map.set(trade.reason, { count: current.count + 1, proceeds: current.proceeds + proceeds });
    }
    return [...map.entries()].sort((a, b) => b[1].proceeds - a[1].proceeds);
  }, [trades]);

  if (loaded.state === "error") {
    return (
      <Panel title="Ledger" source={loaded.source} tone="alert">
        <Absent reason="error" detail={<p className="font-mono">{loaded.error}</p>} />
      </Panel>
    );
  }
  if (!data) {
    return (
      <Panel title="Ledger" source={PERFORMANCE_PATH}>
        <Absent reason="loading" />
      </Panel>
    );
  }

  /**
   * `realized_sol` is a SUM OF SALE PROCEEDS. `performance_summary` adds up
   * `output_lamports / 1e9` across recorded exits and subtracts nothing — no
   * cost basis, no fees. It is how much SOL came back from selling, and it says
   * nothing about whether those sales were at a profit or a loss. Labelling it
   * "realized PnL" would be the same class of error as a fabricated cost basis:
   * a number that looks like performance and is not.
   */
  const proceeds: Measured<number> = fromDecimalString(
    data.realized_sol,
    originOf(loaded, "realized_sol", clock, {
      kind: "derived",
      sample: { n: data.trade_count, window: `newest ${SUMMARY_WINDOW} recorded exits` },
      note: "Sum of output_lamports ÷ 1e9 over recorded exits. No cost basis and no fees are subtracted.",
      caveats: [
        {
          kind: "derived",
          note: "GROSS PROCEEDS, NOT PROFIT. Nothing is netted off. A position sold at a 90% loss still adds its sale proceeds to this total, so a large number here is not evidence of a profitable desk.",
        },
      ],
    }),
  );

  const totalProceeds = byReason.reduce((sum, [, value]) => sum + value.proceeds, 0);

  return (
    <div className="space-y-3">
      <Panel
        title="Ledger"
        source={PERFORMANCE_PATH}
        clock={clock}
        now={now}
        note={
          <>
            Every aggregate here is computed over the newest {SUMMARY_WINDOW} journal rows, not over
            all history. The counts are windowed, not lifetime.
          </>
        }
        actions={
          <>
            <StatusPill label={data.mode ?? "unknown"} tone={data.mode === "live" ? "warn" : "idle"} />
            <StatusPill
              label={data.protection_state ?? "unknown"}
              tone={data.protection_state === "LIVE_ARMED" ? "ok" : "warn"}
            />
          </>
        }
      >
        <FieldGrid columns={4}>
          <Field
            label="gross proceeds"
            hint="Sum of sale proceeds. Nothing is subtracted — not basis, not fees. This is not profit."
          >
            <Figure m={proceeds} format={(value) => `${decimals(value, 6)} SOL`} emphasis="strong" />
          </Field>
          <Field label="recorded exits" hint="Rows in the trade journal inside the summary window.">
            <Figure
              m={observed(
                data.trade_count,
                originOf(loaded, "trade_count", clock, {
                  sample: { n: data.trade_count, window: `newest ${SUMMARY_WINDOW} rows` },
                }),
              )}
              emphasis="strong"
            />
          </Field>
          <Field label="native sol">
            <Figure
              m={fromDecimalString(data.native_sol, originOf(loaded, "native_sol", clock))}
              format={(value) => decimals(value, 6)}
              emphasis="strong"
            />
          </Field>
          <Field label="last exit">
            {data.last_exit_at ? (
              <div>
                <div className="font-mono text-sm">{relativeAge(data.last_exit_at, now)}</div>
                <div className="font-mono text-[10px] text-muted-foreground">
                  {stampUtc(data.last_exit_at)}
                </div>
              </div>
            ) : (
              <Figure
                m={unobserved(
                  originOf(loaded, "last_exit_at", clock, {
                    note: "No exit has been recorded in the journal window.",
                  }),
                )}
              />
            )}
          </Field>
        </FieldGrid>

        <div className="border-t border-border/70">
          <FieldGrid columns={4}>
            <Field label="positions with a rule">
              <Figure
                m={observed(data.protected_positions, originOf(loaded, "protected_positions", clock))}
              />
            </Field>
            <Field label="observe-only">
              <Figure
                m={observed(data.observe_only, originOf(loaded, "observe_only", clock))}
                className={data.observe_only > 0 ? "text-destructive" : undefined}
              />
            </Field>
            {(["info", "warning", "critical"] as const).map((severity) => (
              <Field key={severity} label={`${severity} events`}>
                <Figure
                  m={
                    data.event_counts[severity] == null
                      ? unobserved(
                          originOf(loaded, `event_counts.${severity}`, clock, {
                            note: "This severity does not appear in the journal window. The producer emitted no key for it.",
                          }),
                        )
                      : observed(
                          data.event_counts[severity],
                          originOf(loaded, `event_counts.${severity}`, clock, {
                            sample: {
                              n: Object.values(data.event_counts).reduce((a, b) => a + b, 0),
                              window: `newest ${SUMMARY_WINDOW} events`,
                            },
                          }),
                        )
                  }
                  className={severity === "critical" && (data.event_counts.critical ?? 0) > 0 ? "text-destructive" : undefined}
                />
              </Field>
            ))}
          </FieldGrid>
        </div>
      </Panel>

      <Panel
        title="Proceeds by exit reason"
        source={TRADES_PATH}
        clock={loadedClock(tradesLoad)}
        now={now}
        note="Which rule actually closed positions, and how much SOL each path returned. Still proceeds, not profit — the basis is not in this dataset."
      >
        {byReason.length === 0 ? (
          <Absent reason="no-rows" detail="No exits recorded in the journal window." />
        ) : (
          <Scroller>
            <Table>
              <thead>
                <tr>
                  <Th>reason</Th>
                  <Th align="right">exits</Th>
                  <Th align="right">gross proceeds</Th>
                  <Th align="right">mean per exit</Th>
                  <Th>share</Th>
                </tr>
              </thead>
              <tbody>
                {byReason.map(([reason, value]) => (
                  <tr key={reason} className="hover:bg-muted/30">
                    <Td>
                      <span className="font-mono text-[11px]">{reason}</span>
                    </Td>
                    <Td align="right">
                      <span className="font-mono text-[11px]">{value.count}</span>
                    </Td>
                    <Td align="right">
                      <span className="font-mono text-[11px]">{decimals(value.proceeds, 6)}</span>
                    </Td>
                    <Td align="right">
                      <Figure
                        // The sample size travels with the mean, so a mean over
                        // three exits is flagged thin without anyone deciding to
                        // flag it here.
                        m={observed(value.proceeds / value.count, {
                          source: TRADES_PATH,
                          kind: "derived",
                          clock: loadedClock(tradesLoad),
                          sample: { n: value.count, window: `${value.count} exits` },
                        })}
                        format={(v) => decimals(v, 6)}
                      />
                    </Td>
                    <Td>
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full bg-primary/70"
                            style={{
                              width: `${totalProceeds > 0 ? (value.proceeds / totalProceeds) * 100 : 0}%`,
                            }}
                          />
                        </div>
                        <span className="font-mono text-[10px] text-muted-foreground">
                          {totalProceeds > 0
                            ? `${decimals((value.proceeds / totalProceeds) * 100, 1)}%`
                            : NO_DATA}
                        </span>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Scroller>
        )}
      </Panel>
    </div>
  );
}
