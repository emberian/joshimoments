import { useState } from "react";

import { Figure, ClockPair, Explain } from "@/components/figure";
import {
  Absent,
  Copyable,
  Field,
  FieldGrid,
  Freshness,
  Lamp,
  Panel,
  Scroller,
  StatusPill,
  Table,
  Td,
  Th,
} from "@/components/instrument";
import { protectUnmonitored, type Loaded } from "@/lib/api";
import {
  FEE_TANK_SOL,
  feeTank,
  gateLamps,
  originOf,
  protectionTone,
  snapshotClock,
  snapshotOf,
} from "@/lib/desk";
import { NO_DATA, decimals, relativeAge, shortAddress, sol, stampUtc } from "@/lib/format";
import {
  absenceFromStatus,
  clockOf,
  fromDecimalString,
  observed,
  unobserved,
  unwatched,
  type Measured,
} from "@/lib/measure";
import type { ProtectUnmonitoredResult, Snapshot } from "@/lib/types";

export function Overview({
  snapshot: loaded,
  now,
  onChanged,
}: {
  snapshot: Loaded<Snapshot>;
  now: number;
  onChanged: () => void;
}) {
  const snapshot = snapshotOf(loaded);
  const clock = snapshotClock(loaded);

  if (loaded.state === "error") {
    return (
      <Panel title="Sentinel" source={loaded.source} tone="alert">
        <Absent
          reason="error"
          detail={
            <>
              <p className="font-mono">{loaded.error}</p>
              <p className="mt-2">
                The protection loop is not answering. Nothing on this page is current; no figure is
                being shown as zero in its place.
              </p>
            </>
          }
        />
      </Panel>
    );
  }
  if (!snapshot) {
    return (
      <Panel title="Sentinel" source={loaded.state === "loading" ? loaded.source : ""}>
        <Absent reason="loading" />
      </Panel>
    );
  }

  const system = snapshot.system;
  const gates = gateLamps(system.gate_failures ?? []);
  const closed = gates.filter((gate) => gate.closed).length;
  const freshness = snapshot.freshness ?? [];
  const quotePlane = freshness.find((row) => row.id === "jupiter_quotes");
  const quotesNeverSampled = quotePlane?.status === "never";

  const nativeSol = fromDecimalString(
    snapshot.wallet.sol,
    originOf(loaded, "wallet.sol", clock, {
      note: "Read from the wallet's lamport balance each cycle and divided by 1e9.",
    }),
  );

  /**
   * A portfolio total of 0 while the quote plane has NEVER produced a sample is
   * a sum over nothing, not a measurement that the book is worthless. The server
   * publishes both facts; joining them here is the whole point of the console.
   */
  const bookSol: Measured<number> = quotesNeverSampled
    ? unobserved(
        originOf(loaded, "wallet.portfolio_exit_sol", clock, {
          note: "Suppressed. The Jupiter quote plane reports status=never, so this total is a sum over zero quotes rather than a measured book value.",
          caveats: [
            {
              kind: "unbounded",
              note: "freshness[jupiter_quotes].status === 'never' — no exit route has ever been quoted. The served value is 0; that 0 is not evidence the book is empty.",
            },
          ],
        }),
      )
    : fromDecimalString(
        snapshot.wallet.portfolio_exit_sol,
        originOf(loaded, "wallet.portfolio_exit_sol", clock, {
          note: "Sum of full-balance Jupiter exit quotes across held positions.",
          kind: "derived",
        }),
      );

  const tank = feeTank(nativeSol.state === "observed" ? nativeSol.value : null);

  return (
    <div className="space-y-3">
      <UnmonitoredBanner snapshot={snapshot} onChanged={onChanged} />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Panel
          title="Protection loop"
          source="/api/snapshot"
          clock={clock}
          now={now}
          tone={system.last_cycle_error ? "alert" : "neutral"}
          actions={
            <StatusPill
              label={system.protection_state}
              tone={protectionTone(system.protection_state)}
              help="protection_state as published by the engine. LIVE_ARMED means all three live gates are open and the signer is loaded."
            />
          }
        >
          <FieldGrid columns={4}>
            <Field
              label="mode"
              hint="`live` means the process can sign. It is not a claim that any position is protected."
            >
              <StatusPill
                label={system.mode}
                tone={system.mode === "live" ? "warn" : "idle"}
              />
            </Field>
            <Field label="running">
              <StatusPill label={system.running ? "yes" : "no"} tone={system.running ? "ok" : "bad"} />
            </Field>
            <Field label="last cycle" hint="Engine cycle completion. Both clocks are shown.">
              <ClockPair clock={clockOf(system.last_cycle_at, clock.ingest)} now={now} />
            </Field>
            <Field label="poll interval">
              <Figure
                m={
                  system.poll_interval_seconds != null
                    ? observed(
                        system.poll_interval_seconds,
                        originOf(loaded, "system.poll_interval_seconds", clock, { kind: "config" }),
                      )
                    : unobserved(originOf(loaded, "system.poll_interval_seconds", clock))
                }
                format={(value) => `${value}s`}
              />
            </Field>
            <Field label="wallet">
              <Copyable value={system.wallet_address} display={shortAddress(system.wallet_address, 5, 5)} />
            </Field>
            <Field label="rpc">
              <StatusPill label={system.rpc_ready ? "ready" : "down"} tone={system.rpc_ready ? "ok" : "bad"} />
            </Field>
            <Field label="jupiter">
              <StatusPill
                label={system.jupiter_ready ? "ready" : "down"}
                tone={system.jupiter_ready ? "ok" : "bad"}
                help="Credential/readiness only. Whether a quote has ever been RETURNED is the freshness plane below."
              />
            </Field>
            <Field label="telegram">
              <StatusPill
                label={system.telegram_ready ? "ready" : system.telegram_configured ? "failed" : "unpaired"}
                tone={system.telegram_ready ? "ok" : system.telegram_configured ? "bad" : "idle"}
                help={system.telegram_last_error_type ?? "Alert delivery path."}
              />
            </Field>
          </FieldGrid>

          {system.last_cycle_error && (
            <p className="border-t border-border/70 px-3 py-2 font-mono text-xs text-destructive">
              last_cycle_error: {system.last_cycle_error}
            </p>
          )}
        </Panel>

        <Panel
          title="Live gates"
          source="/api/snapshot"
          clock={clock}
          now={now}
          note={
            <>
              Three independent gates. All must be open before a sell can exist. This console can
              open none of them — it has no route that touches any, and holds no key.
            </>
          }
          actions={
            <StatusPill
              label={closed === 0 ? "all open" : `${closed} closed`}
              tone={closed === 0 ? "warn" : "ok"}
              help={
                closed === 0
                  ? "All gates open: the sentinel is able to sign and submit sell-only exits on its own cycle."
                  : "At least one gate is closed, so no sell can be constructed."
              }
            />
          }
        >
          <div className="space-y-1.5 p-3">
            {gates.map((gate) => (
              <div key={gate.id} className="flex items-center gap-2">
                <Lamp tone={gate.closed ? "bad" : "ok"} />
                <Explain of={<span className="font-mono text-xs">{gate.label}</span>}>
                  {gate.detail}
                </Explain>
                <span className="ml-auto font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  {gate.closed ? "closed" : "open"}
                </span>
              </div>
            ))}
            {system.gate_failures.length > 0 && (
              <p className="pt-1 font-mono text-[10px] text-muted-foreground">
                gate_failures: {system.gate_failures.join(" · ")}
              </p>
            )}
          </div>
        </Panel>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Panel title="Native SOL" source="/api/snapshot" clock={clock} now={now}>
          <div className="space-y-1 p-3">
            <Figure m={nativeSol} format={(value) => decimals(value, 6)} emphasis="strong" />
            <p className="text-[11px] text-muted-foreground">
              {tank === "ok"
                ? `fee tank above the ${FEE_TANK_SOL} SOL floor`
                : tank === "low"
                  ? `below ${FEE_TANK_SOL} SOL — a live exit may fail to land`
                  : tank === "empty"
                    ? "no gas — exits cannot pay a priority fee"
                    : "balance not observed"}
            </p>
          </div>
        </Panel>

        <Panel title="Quoted book" source="/api/snapshot" clock={clock} now={now}>
          <div className="space-y-1 p-3">
            <Figure m={bookSol} format={(value) => decimals(value, 4)} emphasis="strong" />
            <p className="text-[11px] text-muted-foreground">
              {quotesNeverSampled
                ? "no exit route has ever been quoted"
                : "sum of full-balance exit quotes"}
            </p>
          </div>
        </Panel>

        <Panel title="Inventory" source="/api/snapshot" clock={clock} now={now}>
          <div className="grid grid-cols-2 gap-3 p-3">
            <Field label="with policy">
              <Figure
                m={observed(snapshot.positions.length, originOf(loaded, "positions[]", clock))}
                emphasis="strong"
              />
            </Field>
            <Field label="unprotected">
              <Figure
                m={observed(snapshot.unmonitored.length, originOf(loaded, "unmonitored[]", clock))}
                emphasis="strong"
                className={snapshot.unmonitored.length > 0 ? "text-destructive" : undefined}
              />
            </Field>
          </div>
        </Panel>
      </div>

      <FreshnessMatrix snapshot={snapshot} loaded={loaded} now={now} />
      <ReadinessTable snapshot={snapshot} loaded={loaded} now={now} />
      <ExperimentsTable snapshot={snapshot} loaded={loaded} now={now} />
    </div>
  );
}

/**
 * The two-clock plane. This block exists in the API and the previous UI dropped
 * it entirely.
 */
function FreshnessMatrix({
  snapshot,
  loaded,
  now,
}: {
  snapshot: Snapshot;
  loaded: Loaded<Snapshot>;
  now: number;
}) {
  const rows = snapshot.freshness ?? [];
  const clock = snapshotClock(loaded);
  return (
    <Panel
      title="Freshness · two clocks"
      source="/api/snapshot → freshness[]"
      clock={clock}
      now={now}
      note={
        <>
          Event time is when it happened; ingest time is when this process learned it. The sentinel
          currently publishes one timestamp as both for every producer, so every row here is marked{" "}
          <span className="font-mono text-chart-3">proxied</span>: these are ingest stamps standing
          in for event time. Differencing them would fabricate a latency of exactly zero.
        </>
      }
    >
      {rows.length === 0 ? (
        <Absent reason="no-rows" detail="This server build publishes no freshness plane." />
      ) : (
        <Scroller>
          <Table>
            <thead>
              <tr>
                <Th>producer</Th>
                <Th>status</Th>
                <Th hint="Chain/block time, or the producer's own measurement time.">event t</Th>
                <Th hint="When the sentinel received it.">ingest t</Th>
                <Th align="right" hint="The producer's own staleness budget.">ttl</Th>
                <Th align="right">age</Th>
                <Th>last error</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const absence = absenceFromStatus(row.status);
                return (
                  <tr key={row.id} className="hover:bg-muted/30">
                    <Td>
                      <span className="font-mono">{row.label}</span>
                      <div className="font-mono text-[10px] text-muted-foreground">{row.id}</div>
                    </Td>
                    <Td>
                      <StatusPill
                        label={row.status}
                        tone={
                          absence === "observed"
                            ? "ok"
                            : absence === "unobserved"
                              ? "warn"
                              : "idle"
                        }
                        help={
                          absence === "observed"
                            ? "This producer has yielded at least one sample."
                            : absence === "unobserved"
                              ? "Watched, and has NEVER yielded a sample. Any downstream total built from it is a sum over nothing, not a zero."
                              : "Not being watched. Absence here carries no information."
                        }
                      />
                    </Td>
                    <Td>
                      <span className="font-mono text-[11px]">
                        {row.observed_at ? stampUtc(row.observed_at) : NO_DATA}
                      </span>
                    </Td>
                    <Td>
                      <span className="font-mono text-[11px]">
                        {row.received_at ? stampUtc(row.received_at) : NO_DATA}
                      </span>
                      {row.observed_at && row.observed_at === row.received_at && (
                        <span className="ml-2 font-mono text-[10px] uppercase text-chart-3">
                          proxied
                        </span>
                      )}
                    </Td>
                    <Td align="right">
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {row.ttl_seconds != null ? `${row.ttl_seconds}s` : NO_DATA}
                      </span>
                    </Td>
                    <Td align="right">
                      <Freshness at={row.received_at} now={now} ttlSeconds={row.ttl_seconds} />
                    </Td>
                    <Td>
                      {row.last_error ? (
                        <span className="font-mono text-[11px] text-destructive">{row.last_error}</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </Scroller>
      )}
    </Panel>
  );
}

function ReadinessTable({
  snapshot,
  loaded,
  now,
}: {
  snapshot: Snapshot;
  loaded: Loaded<Snapshot>;
  now: number;
}) {
  const readiness = snapshot.readiness;
  const clock = snapshotClock(loaded);
  return (
    <Panel
      title="Capabilities"
      source="/api/snapshot → readiness"
      clock={clock}
      now={now}
      actions={
        readiness && (
          <StatusPill
            label={readiness.overall}
            tone={readiness.overall === "ready" ? "ok" : readiness.overall === "degraded" ? "warn" : "bad"}
          />
        )
      }
      note="What the process can currently do, and which operating mode each ability is required for."
    >
      {!readiness?.capabilities.length ? (
        <Absent reason="no-rows" />
      ) : (
        <Scroller>
          <Table>
            <thead>
              <tr>
                <Th>capability</Th>
                <Th>state</Th>
                <Th>reason</Th>
                <Th hint="null means this capability has never been checked — not checked at epoch.">
                  checked
                </Th>
                <Th>required for</Th>
              </tr>
            </thead>
            <tbody>
              {readiness.capabilities.map((cap) => (
                <tr key={cap.id} className="hover:bg-muted/30">
                  <Td>
                    <span className="font-mono">{cap.label}</span>
                    <div className="font-mono text-[10px] text-muted-foreground">{cap.id}</div>
                  </Td>
                  <Td>
                    <StatusPill
                      label={cap.state}
                      tone={
                        cap.state === "ready"
                          ? "ok"
                          : cap.state === "degraded"
                            ? "warn"
                            : cap.state === "blocked"
                              ? "bad"
                              : "idle"
                      }
                    />
                  </Td>
                  <Td>
                    <span className="text-[11px] text-muted-foreground">{cap.reason ?? "—"}</span>
                  </Td>
                  <Td>
                    {cap.checked_at ? (
                      <span className="font-mono text-[11px]">{relativeAge(cap.checked_at, now)}</span>
                    ) : (
                      <span className="font-mono text-[11px] text-muted-foreground">never checked</span>
                    )}
                  </Td>
                  <Td>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {cap.required_for.join(" · ")}
                    </span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Scroller>
      )}
    </Panel>
  );
}

function ExperimentsTable({
  snapshot,
  loaded,
  now,
}: {
  snapshot: Snapshot;
  loaded: Loaded<Snapshot>;
  now: number;
}) {
  const rows = snapshot.experiments ?? [];
  const clock = snapshotClock(loaded);
  if (!rows.length) return null;
  return (
    <Panel
      title="Experiments"
      source="/api/snapshot → experiments[]"
      clock={clock}
      now={now}
      note="Ingest-only planes. None of these can affect an exit decision; `can_execute` is published per row and is false throughout."
    >
      <Scroller>
        <Table>
          <thead>
            <tr>
              <Th>experiment</Th>
              <Th>mode</Th>
              <Th>health</Th>
              <Th align="right" hint="Count of signals this plane has produced. 0 with health=healthy means watched-and-nothing-seen.">
                signals
              </Th>
              <Th>last sample</Th>
              <Th>can execute</Th>
              <Th>note</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const rowClock = clockOf(row.last_sample_at, row.last_sample_at);
              // `mode` and `health` can disagree: a plane switched off reports
              // mode=disabled while its health stays "unknown". Either one means
              // nothing is collecting, so the count is not a measurement of zero.
              const collecting = row.mode !== "disabled" && row.health !== "disabled";
              const seen: Measured<number> = !collecting
                ? unwatched(
                    originOf(loaded, `experiments[${row.id}].signals_seen`, rowClock, {
                      note: `This plane is not collecting (mode=${row.mode}, health=${row.health}). Its signal count is not a measurement.`,
                    }),
                  )
                  : observed(
                      row.signals_seen,
                      originOf(loaded, `experiments[${row.id}].signals_seen`, rowClock, {
                        note:
                          row.signals_seen === 0
                            ? "Watched, and nothing has been produced yet. This is a measured zero."
                            : undefined,
                      }),
                    );
              return (
                <tr key={row.id} className="hover:bg-muted/30">
                  <Td>
                    <span className="font-mono">{row.label}</span>
                    <div className="font-mono text-[10px] text-muted-foreground">{row.id}</div>
                  </Td>
                  <Td>
                    <span className="font-mono text-[11px] text-muted-foreground">{row.mode}</span>
                  </Td>
                  <Td>
                    <StatusPill
                      label={row.health}
                      tone={
                        row.health === "healthy" ? "ok" : row.health === "disabled" ? "idle" : "warn"
                      }
                      help={row.last_error_type ?? undefined}
                    />
                  </Td>
                  <Td align="right">
                    <Figure m={seen} />
                  </Td>
                  <Td>
                    {row.last_sample_at ? (
                      <ClockPair clock={rowClock} now={now} compact />
                    ) : (
                      <span className="font-mono text-[11px] text-muted-foreground">never</span>
                    )}
                  </Td>
                  <Td>
                    <StatusPill label={row.can_execute ? "yes" : "no"} tone={row.can_execute ? "bad" : "idle"} />
                  </Td>
                  <Td>
                    <span className="text-[11px] text-muted-foreground">{row.note ?? "—"}</span>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </Scroller>
    </Panel>
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
    <Panel
      title={`${count} position${count === 1 ? "" : "s"} with no exit policy`}
      source="/api/snapshot → unmonitored[]"
      tone="alert"
      note="Rug detection and stop-loss will not sell these. Writing a rule changes config.yaml only; the sentinel reads it on its own cycle and decides for itself."
    >
      <Scroller>
        <Table>
          <thead>
            <tr>
              <Th>name</Th>
              <Th>mint</Th>
              <Th align="right">ui amount</Th>
              <Th align="right">quoted exit</Th>
              <Th>protection</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.mint}>
                <Td>{row.name}</Td>
                <Td>
                  <Copyable value={row.mint} display={shortAddress(row.mint)} />
                </Td>
                <Td align="right">
                  <span className="font-mono">{row.ui_amount}</span>
                </Td>
                <Td align="right">
                  <span className="font-mono">
                    {row.exit_sol != null ? sol(Number(row.exit_sol)) : NO_DATA}
                  </span>
                </Td>
                <Td>
                  <StatusPill label={row.protection} tone="bad" />
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Scroller>
      <div className="flex flex-wrap items-center gap-3 border-t border-border/70 p-3">
        <button
          type="button"
          disabled={protecting}
          onClick={() => void protect()}
          className="rounded border border-destructive/60 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-destructive hover:bg-destructive/10 disabled:opacity-50"
        >
          {protecting ? "writing config.yaml…" : "write rug-only rules"}
        </button>
        <p className="text-[11px] text-muted-foreground">
          No cost basis is sent. Seeding a basis from the current exit quote made PnL start at 0%
          regardless of what was paid, firing every stop below an already-fallen price.
        </p>
      </div>
      {error && <p className="px-3 pb-3 font-mono text-xs text-destructive">{error}</p>}
      {result && (
        <div className="px-3 pb-3 text-xs text-muted-foreground">
          <p>Wrote {result.created.length} rule(s) to config.yaml. can_execute: {String(result.can_execute)}.</p>
          {result.skipped.length > 0 && (
            <ul className="mt-1 list-disc pl-4">
              {result.skipped.map((item) => (
                <li key={item.mint}>
                  skipped {shortAddress(item.mint)}: {item.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Panel>
  );
}
