import type { EvidenceClass, IntelEvidence, IntelligenceSnapshot } from "./types";

export const INTELLIGENCE_BASE_URL = "http://127.0.0.1:8788/api";

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function text(value: unknown, fallback = "", limit = 320) {
  return typeof value === "string" ? value.slice(0, limit) : fallback;
}

function strings(value: unknown, limit = 8) {
  if (!Array.isArray(value)) return [];
  return value.slice(0, limit).map((item) => text(item, "", 80)).filter(Boolean);
}

function classify(item: Record<string, unknown>): EvidenceClass {
  const kind = text(item.kind).toLowerCase();
  if (kind.includes("hypothesis") || kind.includes("speculation")) return "speculation";
  if (kind.startsWith("x_") || kind.includes("claim") || kind.includes("callout") || kind.includes("social")) return "claim";
  return "fact";
}

export async function loadIntelligence(): Promise<IntelligenceSnapshot> {
  const paths = [
    "/health",
    "/intelligence/feed?limit=50",
    "/intelligence/sources",
    "/intelligence/watchlists",
    "/intelligence/candidates",
  ] as const;
  const results = await Promise.allSettled(
    paths.map((path) =>
      fetch(`${INTELLIGENCE_BASE_URL}${path}`, {
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
        signal: AbortSignal.timeout(2500),
        headers: { accept: "application/json" },
      }).then(async (response) => ({ ok: response.ok, value: await response.json().catch(() => ({})) })),
    ),
  );
  const health = record(results[0].status === "fulfilled" ? results[0].value.value : {});
  const feed = record(results[1].status === "fulfilled" ? results[1].value.value : {});
  const sources = record(results[2].status === "fulfilled" ? results[2].value.value : {});
  const watchlists = record(results[3].status === "fulfilled" ? results[3].value.value : {});
  const candidatesPage = record(results[4].status === "fulfilled" ? results[4].value.value : {});
  const inbox: IntelEvidence[] = (Array.isArray(feed.items) ? feed.items : []).slice(0, 80).map((raw, index) => {
    const value = record(raw);
    const details = record(value.details);
    return {
      id: text(value.id, `INTEL-${index + 1}`, 80),
      classification: classify(value),
      title: text(value.title, text(value.kind, "observation"), 140),
      summary: text(value.summary, "No summary supplied.", 400),
      observed_at: text(value.observed_at, "", 64) || null,
      source_ids: strings(value.source_ids).length ? strings(value.source_ids) : text(value.source_id) ? [text(value.source_id)] : [],
      kind: text(value.kind, "observation", 40),
      url: text(value.url ?? details.url, "", 240) || null,
      author: text(value.author_username ?? details.author_username, "", 32) || null,
      cashtags: strings(value.cashtags ?? details.cashtags),
      mint_candidates: strings(value.mint_candidates ?? details.mint_candidates),
      watched_handle: text(value.watched_handle ?? details.watched_handle, "", 15) || null,
      mint: text(value.mint, "", 64) || null,
    };
  });
  const runtime = record(health.runtime);
  // Whether the service answered at all. Every counter below is null when it did
  // not: a service that is not reachable has NOT reported zero collectors and
  // zero items today, and rendering it as `0` was a measurement claim we could
  // not make.
  const reachable = results[0].status === "fulfilled" && results[0].value.ok;
  const counter = (value: unknown): number | null =>
    typeof value === "number" && Number.isFinite(value) ? value : null;
  return {
    reachable,
    service: {
      status: !reachable ? "unreachable" : health.healthy === true ? "healthy" : "degraded",
      collectors_active: counter(runtime.collectors_active),
      last_cycle_at: text(runtime.last_cycle_at, "", 64) || null,
      x_items_today: counter(runtime.x_items_today),
      cycle_in_progress: runtime.cycle_in_progress === true,
      last_cycle_partial: runtime.last_cycle_partial === true,
      last_error: text(runtime.last_error, "", 160) || null,
    },
    inbox,
    x_tape: inbox.filter((item) => item.kind.startsWith("x_") || item.source_ids.some((source) => source.includes("apify_x"))),
    sources: (Array.isArray(sources.items) ? sources.items : []).slice(0, 20).map((raw, index) => {
      const value = record(raw);
      return {
        id: text(value.id, `source-${index}`, 40),
        label: text(value.name ?? value.label, text(value.id, "source"), 80),
        status: text(value.status, "unknown", 24),
      };
    }),
    watchlists: (Array.isArray(watchlists.items) ? watchlists.items : []).slice(0, 20).map((raw, index) => {
      const value = record(raw);
      return {
        id: text(value.id, `wl-${index}`, 40),
        name: text(value.name, "watchlist", 80),
        member_count: counter(value.member_count),
      };
    }),
    candidates: (Array.isArray(candidatesPage.items) ? candidatesPage.items : []).slice(0, 24).map((raw) => {
      const value = record(raw);
      return {
        mint: text(value.mint, "", 64),
        name: text(value.name, "", 48) || null,
        verdict: text(value.verdict, "skip", 16),
        reasons: strings(value.reasons, 4),
        scores: {},
        execution_effect: "none" as const,
      };
    }),
  };
}
