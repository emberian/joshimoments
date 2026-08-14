import { useState } from "react";

import { EvidenceTag, Explain, Figure } from "@/components/figure";
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
import { NO_DATA, cn, compact, decimals, hours, shortAddress, stampUtc, usd } from "@/lib/format";
import { clockOf, observed, unobserved, unwatched, type Measured } from "@/lib/measure";
import {
  NETMAP_COMMAND,
  clockCorruptedEdges,
  cycleNetUsd,
  tvlUnavailable,
  type NetCycle,
  type NetEdge,
  type NetMap,
  type NetMapLoad,
  type NetNode,
} from "@/lib/netmap";

export function Circuit({
  netmap,
  now,
  onRefresh,
  loading,
}: {
  netmap: NetMapLoad;
  now: number;
  onRefresh: () => void;
  loading: boolean;
}) {
  if (netmap.state === "loading") {
    return (
      <Panel title="Cluster circuit" source="shitcoims_netmap.render">
        <Absent reason="loading" />
      </Panel>
    );
  }
  if (netmap.state === "not-wired") {
    return (
      <Panel title="Cluster circuit" source="shitcoims_netmap.render" tone="warn">
        <Absent
          reason="not-wired"
          detail={
            <div className="space-y-3 text-left">
              <p>
                The netmap is a CLI. There is no HTTP route for it, and this console does not add
                one — the sentinel process holds the signer and the web tier does not get to grow
                its surface. Nothing is being rendered as an empty cluster in the meantime.
              </p>
              <p className="text-muted-foreground">Tried, in order:</p>
              <ul className="font-mono text-[11px] text-muted-foreground">
                {netmap.tried.map((path) => (
                  <li key={path}>{path} → 404</li>
                ))}
              </ul>
              <p className="text-muted-foreground">Mint a snapshot the console can read:</p>
              <code className="block rounded bg-muted/60 px-2 py-1.5 font-mono text-[11px] break-all">
                {NETMAP_COMMAND}
              </code>
            </div>
          }
        />
        <div className="border-t border-border/70 p-3">
          <RefreshButton onRefresh={onRefresh} loading={loading} />
        </div>
      </Panel>
    );
  }
  if (netmap.state === "error") {
    return (
      <Panel title="Cluster circuit" source={netmap.source} tone="alert">
        <Absent reason="error" detail={<p className="font-mono">{netmap.error}</p>} />
      </Panel>
    );
  }

  const map = netmap.map;
  return (
    <div className="space-y-3">
      <CircuitHeader map={map} source={netmap.source} receivedAt={netmap.receivedAt} now={now} onRefresh={onRefresh} loading={loading} />
      {map.warnings.length > 0 && <Warnings warnings={map.warnings} />}
      <Cycles map={map} />
      <Edges map={map} />
      <Nodes map={map} />
    </div>
  );
}

function RefreshButton({ onRefresh, loading }: { onRefresh: () => void; loading: boolean }) {
  return (
    <button
      type="button"
      onClick={onRefresh}
      disabled={loading}
      className="rounded border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider hover:bg-muted disabled:opacity-50"
    >
      {loading ? "reading…" : "re-read snapshot"}
    </button>
  );
}

function CircuitHeader({
  map,
  source,
  receivedAt,
  now,
  onRefresh,
  loading,
}: {
  map: NetMap;
  source: string;
  receivedAt: string;
  now: number;
  onRefresh: () => void;
  loading: boolean;
}) {
  const tape = map.sources.cluster_tape;
  const lp = map.sources.lp_meter;
  const corrupted = clockCorruptedEdges(map);
  const clock = clockOf(map.window.to_t_event, map.generated_at);

  return (
    <Panel
      title="Cluster circuit"
      source={source}
      clock={clock}
      now={now}
      actions={<RefreshButton onRefresh={onRefresh} loading={loading} />}
      note={
        <>
          A static snapshot minted by <code className="font-mono">{NETMAP_COMMAND}</code>. It does
          not refresh itself — the age above is the age of the file, and the window below is event
          time, not the age of this page.
        </>
      }
      tone={corrupted.length > 0 ? "alert" : "neutral"}
    >
      <FieldGrid columns={6}>
        <Field label="schema">
          <span className="font-mono text-xs">{map.schema}</span>
        </Field>
        <Field label="minted" hint="Ingest/wall clock of the render run.">
          <span className="font-mono text-xs">{stampUtc(map.generated_at)}</span>
        </Field>
        <Field label="page read at" hint="When this browser fetched the file.">
          <span className="font-mono text-xs">{stampUtc(receivedAt)}</span>
        </Field>
        <Field label="event window" hint="from_t_event → to_t_event. Chain time, the only clock safe to join on.">
          <span className="font-mono text-xs">
            {map.window.hours != null ? hours(map.window.hours) : NO_DATA}
          </span>
        </Field>
        <Field label="nodes / edges / cycles">
          <span className="font-mono text-xs">
            {map.nodes.length} / {map.edges.length} / {map.cycles.length}
          </span>
        </Field>
        <Field label="gas assumption" hint="Used to price whether a cycle nets anything after costs.">
          <span className="font-mono text-xs">{usd(map.config.gas_usd, 2)}</span>
        </Field>
      </FieldGrid>

      <div className="grid gap-0 border-t border-border/70 md:grid-cols-3">
        <div className="space-y-1 border-border/70 p-3 md:border-r">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            cluster tape
          </p>
          {"status" in tape ? (
            <StatusPill label="not read" tone="idle" help="The tape was not read for this render." />
          ) : (
            <div className="space-y-0.5 font-mono text-[11px]">
              <div>
                {compact(tape.rows)} rows · {tape.files_read} files
              </div>
              <div className={cn(tape.malformed_lines > 0 && "text-destructive")}>
                malformed {tape.malformed_lines} · partial final {tape.partial_final_lines}
              </div>
              {tape.unreadable_files.length > 0 && (
                <div className="text-destructive">{tape.unreadable_files.length} unreadable</div>
              )}
            </div>
          )}
        </div>
        <div className="space-y-1 border-border/70 p-3 md:border-r">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            price sources
          </p>
          <div className="space-y-0.5 font-mono text-[11px]">
            <div>
              dexscreener {map.sources.prices.dexscreener_pools} · gecko{" "}
              {map.sources.prices.geckoterminal_pools} · dlmm {map.sources.prices.dlmm_pool_states}
            </div>
            {map.sources.prices.errors.length > 0 && (
              <div className="text-chart-3">{map.sources.prices.errors.join(" · ")}</div>
            )}
          </div>
        </div>
        <div className="space-y-1 p-3">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            lp meter
          </p>
          {"status" in lp ? (
            <StatusPill
              label="not read"
              tone="idle"
              help="No LP wallet was resolved. Every edge's ownership is therefore UNKNOWN, which is not the same as 'we own nothing'."
            />
          ) : (
            <div className="space-y-0.5 font-mono text-[11px]">
              <div>
                wallet {lp.wallet ? shortAddress(lp.wallet) : NO_DATA}{" "}
                <span className="text-muted-foreground">({lp.provenance})</span>
              </div>
              <div>
                {lp.total_value_usd != null ? usd(lp.total_value_usd, 2) : NO_DATA} in{" "}
                {lp.pools_with_positions.length} pools
              </div>
            </div>
          )}
        </div>
      </div>

      {corrupted.length > 0 && (
        <p className="border-t border-destructive/40 px-3 py-2 font-mono text-[11px] text-destructive">
          CLOCK ALARM — {corrupted.length} edge(s) carry rows stamped as ingested before they
          happened: {corrupted.map((edge) => edge.label).join(", ")}. Ingest precedes event, which
          means the tape's clocks disagree on those pools.
        </p>
      )}
    </Panel>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  return (
    <Panel title={`Render warnings (${warnings.length})`} source="netmap → warnings[]" tone="warn">
      <ul className="space-y-1.5 p-3">
        {warnings.map((warning) => (
          <li key={warning} className="flex gap-2 text-[11px] leading-relaxed">
            <span className="text-chart-3">▲</span>
            <span className="text-muted-foreground">{warning}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/**
 * A curl is only interesting if it escapes the fee dead-zone AND nets positive
 * after gas and depth. The meter shows the band and the curl together, because
 * a curl shown alone reads as an opportunity when it is usually just noise
 * inside the diode drop.
 */
function DeadZoneMeter({ cycle }: { cycle: NetCycle }) {
  const primary = cycle.curl_primary_source;
  const curl = primary ? cycle.curl_bps[primary] : undefined;
  const band = cycle.fee_band_bps;
  const full = cycle.full_band_bps.no_concentration;
  const extent = Math.max(full * 1.25, Math.abs(curl ?? 0) * 1.1, band * 1.5);
  const toPct = (value: number) => 50 + (value / extent) * 50;

  return (
    <div className="min-w-[13rem] space-y-1">
      <div className="relative h-4 overflow-hidden rounded border border-border/70 bg-muted/30">
        {/* full band: fee + depth cost */}
        <div
          className="absolute inset-y-0 bg-chart-3/15"
          style={{ left: `${toPct(-full)}%`, right: `${100 - toPct(full)}%` }}
        />
        {/* fee dead-zone: the diode drop */}
        <div
          className="absolute inset-y-0 bg-muted-foreground/25"
          style={{ left: `${toPct(-band)}%`, right: `${100 - toPct(band)}%` }}
        />
        <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
        {curl !== undefined && (
          <div
            className={cn(
              "absolute inset-y-0 w-0.5",
              Math.abs(curl) > full
                ? "bg-lamp-ok"
                : Math.abs(curl) > band
                  ? "bg-chart-3"
                  : "bg-muted-foreground",
            )}
            style={{ left: `${Math.max(0, Math.min(100, toPct(curl)))}%` }}
          />
        )}
      </div>
      <div className="flex justify-between font-mono text-[10px] text-muted-foreground">
        <span>dead-zone ±{decimals(band, 0)}</span>
        <span>full ±{decimals(full, 0)}</span>
      </div>
    </div>
  );
}

function Cycles({ map }: { map: NetMap }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!map.cycles.length) {
    return (
      <Panel title="Cycles" source="netmap → cycles[]">
        <Absent
          reason="no-rows"
          detail="No closed loop had every leg priced by a single source. A cycle with an unpriced leg is omitted rather than estimated."
        />
      </Panel>
    );
  }
  return (
    <Panel
      title={`Cycles (${map.cycles.length})`}
      source="netmap → cycles[]"
      note={
        <>
          Every cycle here is <span className="font-mono">diagnostic_only</span>. A curl is a KVL
          residual around a loop; it moves nothing until it clears the fee dead-zone and still nets
          positive after gas and depth.
        </>
      }
    >
      <Scroller>
        <Table>
          <thead>
            <tr>
              <Th>loop</Th>
              <Th hint="KVL residual around the loop, in bps, from the source that priced every leg.">
                curl
              </Th>
              <Th hint="The diode dead-zone: summed fee drop. A curl inside this band drives no current.">
                vs dead-zone
              </Th>
              <Th align="right" hint="|DexScreener − GeckoTerminal|. Large spread means the curl is a source artefact.">
                spread
              </Th>
              <Th align="right" hint="Net USD after fees, gas and depth, at the pessimistic and optimistic depth bounds.">
                net after cost
              </Th>
              <Th align="right" hint="The shallowest leg caps any size you could actually push.">
                thinnest leg
              </Th>
              <Th>verdict</Th>
            </tr>
          </thead>
          <tbody>
            {map.cycles.map((cycle) => {
              const primary = cycle.curl_primary_source;
              const curl = primary ? cycle.curl_bps[primary] : undefined;
              const net = cycleNetUsd(cycle);
              const unresolvable = cycle.verdict.startsWith("unresolvable");
              const expanded = open === cycle.name;
              return (
                <>
                  <tr
                    key={cycle.name}
                    className="cursor-pointer hover:bg-muted/30"
                    onClick={() => setOpen(expanded ? null : cycle.name)}
                  >
                    <Td>
                      <span className="font-mono text-xs">{cycle.name}</span>
                      <div className="font-mono text-[10px] text-muted-foreground">
                        {cycle.legs.length} legs
                      </div>
                    </Td>
                    <Td>
                      {curl !== undefined ? (
                        <Figure
                          m={observed(curl, {
                            source: "netmap → cycles[].curl_bps",
                            path: primary ?? undefined,
                            kind: "derived",
                            clock: clockOf(
                              cycle.chain_leg_event_times[0] ?? null,
                              map.sources.prices.fetched_at,
                            ),
                            note: `Primary source: ${primary}. Only sources that priced EVERY leg produce a curl.`,
                            caveats: unresolvable
                              ? [
                                  {
                                    kind: "disagreement",
                                    note: `Price sources disagree by ${decimals(cycle.source_spread_bps ?? 0, 0)} bps, wider than the ${decimals(cycle.fee_band_bps, 0)} bps band. The curl is not resolvable from these feeds.`,
                                  },
                                ]
                              : undefined,
                          })}
                          format={(value) => `${decimals(value, 1)} bps`}
                        />
                      ) : (
                        <Figure
                          m={unobserved({
                            source: "netmap → cycles[].curl_bps",
                            kind: "derived",
                            clock: clockOf(null, map.sources.prices.fetched_at),
                            note: "No single source priced every leg of this loop.",
                          })}
                        />
                      )}
                    </Td>
                    <Td>
                      <DeadZoneMeter cycle={cycle} />
                    </Td>
                    <Td align="right">
                      <span
                        className={cn(
                          "font-mono text-[11px]",
                          unresolvable && "text-destructive",
                        )}
                      >
                        {cycle.source_spread_bps != null
                          ? `${decimals(cycle.source_spread_bps, 0)} bps`
                          : NO_DATA}
                      </span>
                    </Td>
                    <Td align="right">
                      {net ? (
                        <span className="font-mono text-[11px]">
                          <span className={net.pessimistic > 0 ? "text-lamp-ok" : "text-muted-foreground"}>
                            {usd(net.pessimistic, 2)}
                          </span>
                          <span className="text-muted-foreground"> … </span>
                          <span className={net.optimistic > 0 ? "text-lamp-ok" : "text-muted-foreground"}>
                            {usd(net.optimistic, 2)}
                          </span>
                        </span>
                      ) : (
                        <span className="font-mono text-[11px] text-muted-foreground">{NO_DATA}</span>
                      )}
                    </Td>
                    <Td align="right">
                      <span className="font-mono text-[11px]">{usd(cycle.thinnest_leg_usd, 0)}</span>
                    </Td>
                    <Td>
                      <StatusPill
                        label={
                          unresolvable
                            ? "unresolvable"
                            : cycle.verdict.includes("dead-zone")
                              ? "in dead-zone"
                              : cycle.verdict.includes("uneconomic")
                                ? "uneconomic"
                                : cycle.verdict.includes("assumed")
                                  ? "assumed only"
                                  : cycle.verdict === "no_price"
                                    ? "no price"
                                    : "clears band"
                        }
                        tone={
                          unresolvable
                            ? "bad"
                            : cycle.verdict.includes("dead-zone")
                              ? "idle"
                              : cycle.verdict.includes("assumed")
                                ? "warn"
                                : cycle.verdict === "no_price"
                                  ? "idle"
                                  : "ok"
                        }
                        help={cycle.verdict}
                      />
                    </Td>
                  </tr>
                  {expanded && (
                    <tr key={`${cycle.name}-detail`}>
                      <Td className="bg-muted/20">
                        <div className="space-y-1">
                          {cycle.legs.map((leg) => (
                            <div key={leg.pool} className="font-mono text-[10px]">
                              <span className={leg.orientation === 1 ? "" : "text-muted-foreground"}>
                                {leg.orientation === 1 ? "→" : "←"} {leg.label}
                              </span>
                              <span className="text-muted-foreground">
                                {" "}
                                · {decimals(leg.fee_bps, 0)}bps{leg.fee_uncertain ? "?" : ""} ·{" "}
                                {usd(leg.tvl_usd, 0)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </Td>
                      <Td colSpan={6} className="bg-muted/20">
                        <div className="space-y-1.5 text-[11px] text-muted-foreground">
                          <p>
                            <span className="font-mono uppercase">verdict</span> — {cycle.verdict}
                          </p>
                          <p>{cycle.diagnostic_note}</p>
                          <p className="font-mono">
                            curl by source:{" "}
                            {Object.entries(cycle.curl_bps)
                              .map(([key, value]) => `${key} ${decimals(value, 1)}`)
                              .join(" · ") || "none"}
                          </p>
                          {cycle.chain_leg_event_times.length > 0 && (
                            <p className="font-mono">
                              chain leg event times: {cycle.chain_leg_event_times.map(stampUtc).join(" · ")}
                            </p>
                          )}
                          <p>{cycle.chain_channel_note}</p>
                        </div>
                      </Td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </Table>
      </Scroller>
    </Panel>
  );
}

function Edges({ map }: { map: NetMap }) {
  const [showAll, setShowAll] = useState(true);
  const edges = showAll ? map.edges : map.edges.filter((edge) => edge.flow.evidence !== "not_watching");
  return (
    <Panel
      title={`Edges (${map.edges.length})`}
      source="netmap → edges[]"
      note="Each edge is a pool. Flow evidence is three-way: observed, observed-zero, and not-watching. The third is not a zero."
      actions={
        <button
          type="button"
          onClick={() => setShowAll((value) => !value)}
          className="rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider hover:bg-muted"
        >
          {showAll ? "hide unwatched" : "show all"}
        </button>
      }
    >
      <Scroller>
        <Table>
          <thead>
            <tr>
              <Th>pool</Th>
              <Th>flow evidence</Th>
              <Th align="right" hint="Swaps per hour inside watch coverage. null when nothing is watching.">
                swaps/h
              </Th>
              <Th align="right" hint="attempts / (attempts + swaps + liquidity). A high rate means most traffic here never lands.">
                failed
              </Th>
              <Th align="right" hint="Chosen TVL. 'unavailable' means nobody served one — rendered as a dash, never as $0.">
                tvl
              </Th>
              <Th align="right" hint="Worst cross-source ratio against the chosen TVL.">
                disagree
              </Th>
              <Th align="right" hint="Taker fee: LP + protocol + creator. '?' means assumed, not read from pool config.">
                fee
              </Th>
              <Th hint="null means the LP wallet was never resolved — UNKNOWN, not 'not ours'.">ours</Th>
              <Th>last swap (event t)</Th>
            </tr>
          </thead>
          <tbody>
            {edges.map((edge) => (
              <EdgeRow key={edge.pool} edge={edge} map={map} />
            ))}
          </tbody>
        </Table>
      </Scroller>
      {edges.length === 0 && <Absent reason="no-rows" />}
    </Panel>
  );
}

function EdgeRow({ edge, map }: { edge: NetEdge; map: NetMap }) {
  const flow = edge.flow;
  const watching = flow.evidence !== "not_watching";

  const swapsPerHour: Measured<number> =
    "swaps_per_hour" in flow && flow.swaps_per_hour != null
      ? observed(flow.swaps_per_hour, {
          source: "netmap → edges[].flow.swaps_per_hour",
          kind: "derived",
          clock: clockOf("last_swap_t_event" in flow ? flow.last_swap_t_event : null, map.generated_at),
          sample: {
            n: "swaps_watched" in flow ? flow.swaps_watched : 0,
            window: "watched_seconds" in flow ? `${decimals(flow.watched_seconds / 3600, 2)}h watched` : null,
          },
          note:
            "swaps_unwatched" in flow && flow.swaps_unwatched > 0
              ? `${flow.swaps_unwatched} further swaps were seen OUTSIDE coverage and are excluded from this rate — they are evidence of flow, never of absence.`
              : undefined,
        })
      : unwatched({
          source: "netmap → edges[].flow",
          kind: "served",
          clock: clockOf(null, map.generated_at),
          note: "note" in flow ? flow.note : "No watch coverage in this window.",
        });

  const failedRate: Measured<number> = edge.attempts?.failed_attempt_rate != null
    ? observed(edge.attempts.failed_attempt_rate, {
        source: "netmap → edges[].attempts.failed_attempt_rate",
        kind: "derived",
        clock: clockOf(null, map.generated_at),
        sample: { n: edge.attempts.attempts + edge.attempts.landed, window: edge.attempts.denominator },
        note: edge.attempts.top_errors.length
          ? `Top errors: ${edge.attempts.top_errors.map((e) => `${e.error} ×${e.count}`).join(" · ")}`
          : undefined,
      })
    : unwatched({
        source: "netmap → edges[].attempts",
        kind: "served",
        clock: clockOf(null, map.generated_at),
        note: "This edge has no tape slice, so no attempts were counted.",
      });

  const tvl: Measured<number> = tvlUnavailable(edge)
    ? unobserved({
        source: "netmap → edges[].element",
        path: "tvl_usd",
        kind: "served",
        clock: clockOf(edge.element.liquidity_cross_check.tape_reserves_t_event, map.sources.prices.fetched_at),
        note: "tvl_source is 'unavailable': no source served a TVL for this pool. The served 0.0 is a placeholder, not a measurement that the pool is empty.",
      })
    : observed(edge.element.tvl_usd, {
        source: "netmap → edges[].element.tvl_usd",
        kind: "served",
        clock: clockOf(edge.element.liquidity_cross_check.tape_reserves_t_event, map.sources.prices.fetched_at),
        note: `Chosen source: ${edge.element.tvl_source}.`,
        caveats:
          (edge.element.liquidity_cross_check.disagreement_ratio ?? 0) > 2
            ? [
                {
                  kind: "disagreement",
                  note: `Sources disagree by ${decimals(edge.element.liquidity_cross_check.disagreement_ratio ?? 0, 2)}×. Chain vaults and aggregator listings do not agree about this pool.`,
                },
              ]
            : undefined,
      });

  return (
    <tr className="hover:bg-muted/30">
      <Td>
        <div className="flex items-center gap-2">
          <Copyable value={edge.pool} display={<span className="font-mono text-xs">{edge.label}</span>} />
          {!edge.in_cluster_universe && (
            <StatusPill label="lp-only" tone="idle" help="Outside the watched cluster universe: no tape slice exists for this pool." />
          )}
        </div>
        <div className="font-mono text-[10px] text-muted-foreground">
          {edge.dex} · {edge.element.type === "capacitor" ? "CPMM" : "DLMM"}
        </div>
      </Td>
      <Td>
        <EvidenceTag
          evidence={flow.evidence}
          note={"unwatched_note" in flow ? flow.unwatched_note : "note" in flow ? flow.note : undefined}
        />
        {watching && "gap_seconds" in flow && flow.gap_seconds > 0 && (
          <div className="mt-0.5 font-mono text-[10px] text-chart-3">
            gap {hours(flow.gap_seconds / 3600)}
          </div>
        )}
      </Td>
      <Td align="right">
        <Figure m={swapsPerHour} format={(value) => decimals(value, 1)} />
      </Td>
      <Td align="right">
        <Figure
          m={failedRate}
          format={(value) => `${decimals(value * 100, 1)}%`}
          className={
            failedRate.state === "observed" && failedRate.value > 0.5 ? "text-destructive" : undefined
          }
        />
      </Td>
      <Td align="right">
        <Figure m={tvl} format={(value) => usd(value, 0)} />
      </Td>
      <Td align="right">
        <span className="font-mono text-[11px] text-muted-foreground">
          {edge.element.liquidity_cross_check.disagreement_ratio != null
            ? `${decimals(edge.element.liquidity_cross_check.disagreement_ratio, 2)}×`
            : NO_DATA}
        </span>
      </Td>
      <Td align="right">
        <Explain
          of={
            <span className="font-mono text-[11px]">
              {decimals(edge.fee.taker_bps, 0)}
              {edge.fee.uncertain ? "?" : ""}
            </span>
          }
        >
          <p>
            {decimals(edge.fee.taker_bps, 1)} bps taker · LP share {decimals(edge.fee.lp_share * 100, 1)}%
          </p>
          <p className="mt-1 text-muted-foreground">source: {edge.fee.source}</p>
          {edge.fee.uncertain && (
            <p className="mt-1 text-chart-3">
              ASSUMED — not read from the pool's own config. Every band computed from it inherits
              this assumption.
            </p>
          )}
        </Explain>
      </Td>
      <Td>
        {edge.ours === null ? (
          <StatusPill
            label="unknown"
            tone="idle"
            help="No LP wallet was ever resolved, so ownership of this pool is UNKNOWN. This is deliberately not rendered as 'not ours' — that would be a scoped negative we have not measured."
          />
        ) : edge.ours.is_ours ? (
          <StatusPill
            label="ours"
            tone="info"
            help={`${edge.ours.positions.length} position(s) · ${edge.ours.basis}`}
          />
        ) : (
          <StatusPill label="not ours" tone="idle" help={edge.ours.basis} />
        )}
      </Td>
      <Td>
        {"last_swap_t_event" in flow && flow.last_swap_t_event ? (
          <span className="font-mono text-[11px]">{stampUtc(flow.last_swap_t_event)}</span>
        ) : (
          <span className="font-mono text-[11px] text-muted-foreground">{NO_DATA}</span>
        )}
      </Td>
    </tr>
  );
}

function Nodes({ map }: { map: NetMap }) {
  return (
    <Panel
      title={`Nodes (${map.nodes.length})`}
      source="netmap → nodes[]"
      note="Inventory is always a LOWER BOUND: wallet balances need an RPC read that is not wired, so `complete` is false on every row."
    >
      <Scroller>
        <Table>
          <thead>
            <tr>
              <Th>token</Th>
              <Th align="right" hint="A served price of 0 is coerced to null upstream: no price, not a zero price.">
                price
              </Th>
              <Th align="right" hint="Edges touching this mint / of those, edges above the liquidity floor.">
                degree
              </Th>
              <Th align="right" hint="LP units held. null means no LP wallet was resolved — unknown, not zero.">
                lp units
              </Th>
              <Th align="right">gross out (window)</Th>
              <Th align="right" hint="Net ΔQ from swaps only. Liquidity adds/withdrawals are kept separate.">
                net charge
              </Th>
              <Th>coverage</Th>
            </tr>
          </thead>
          <tbody>
            {map.nodes.map((node) => (
              <NodeRow key={node.mint} node={node} map={map} />
            ))}
          </tbody>
        </Table>
      </Scroller>
    </Panel>
  );
}

function NodeRow({ node, map }: { node: NetNode; map: NetMap }) {
  const clock = clockOf(map.window.to_t_event, map.sources.prices.fetched_at);
  const price: Measured<number> =
    node.price_usd != null
      ? observed(node.price_usd, {
          source: "netmap → nodes[].price_usd",
          kind: "served",
          clock,
          note: `Price source: ${node.price_source ?? "unknown"}. Aggregator prices carry no block time and must not be joined on event time.`,
        })
      : unobserved({
          source: "netmap → nodes[].price_usd",
          kind: "served",
          clock,
          note: "No source priced this mint. A served 0 is coerced to null upstream so it cannot be read as a zero price.",
        });

  const lpUnits: Measured<number> =
    node.inventory.lp_units != null
      ? observed(node.inventory.lp_units, {
          source: "netmap → nodes[].inventory.lp_units",
          kind: "served",
          clock,
          note: node.inventory.basis,
          caveats: [
            {
              kind: "unbounded",
              note: "Inventory is a LOWER BOUND — `complete` is false. Wallet balances are not read, so the true holding is at least this.",
            },
          ],
        })
      : unwatched({
          source: "netmap → nodes[].inventory.lp_units",
          kind: "served",
          clock,
          note: node.inventory.basis,
        });

  return (
    <tr className="hover:bg-muted/30">
      <Td>
        <Copyable value={node.mint} display={<span className="font-mono text-xs">{node.symbol}</span>} />
      </Td>
      <Td align="right">
        <Figure m={price} format={(value) => (value < 0.01 ? value.toExponential(3) : usd(value, 4))} />
      </Td>
      <Td align="right">
        <Explain
          of={
            <span className="font-mono text-[11px]">
              {node.degree_live}/{node.degree}
            </span>
          }
        >
          {node.degree - node.degree_live} of {node.degree} edges sit below the{" "}
          {usd(map.config.min_cycle_liquidity_usd, 0)} liquidity floor and cannot carry a cycle.
        </Explain>
      </Td>
      <Td align="right">
        <Figure m={lpUnits} format={(value) => compact(value, 2)} />
      </Td>
      <Td align="right">
        <span className="font-mono text-[11px]">
          {node.flow_usd_out_window != null
            ? usd(node.flow_usd_out_window, 0)
            : compact(node.flow_units_out_window, 1)}
        </span>
      </Td>
      <Td align="right">
        <span
          className={cn(
            "font-mono text-[11px]",
            node.net_charge_units_window > 0 ? "text-lamp-ok" : node.net_charge_units_window < 0 ? "text-destructive" : "",
          )}
        >
          {node.net_charge_usd_window != null
            ? usd(node.net_charge_usd_window, 0)
            : compact(node.net_charge_units_window, 1)}
        </span>
      </Td>
      <Td>
        {node.any_watch_coverage ? (
          <StatusPill label="watched" tone="ok" />
        ) : (
          <StatusPill
            label="no coverage"
            tone="idle"
            help="No edge touching this mint had watch coverage in the window. Its flow figures are unknown, not zero."
          />
        )}
      </Td>
    </tr>
  );
}
