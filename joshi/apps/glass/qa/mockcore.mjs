#!/usr/bin/env node
/**
 * A mock joshi-core for the parity walk's SELF-TEST. Not a fixture for Glass development and
 * never a data source for anything but `qa/walk.mjs` proving itself: it exists so the harness
 * can be trusted BEFORE it is pointed at a live session, and so a broken walk is
 * distinguishable from a broken cockpit.
 *
 * It serves the minimum honest surface of `apps/core/src/service.rs`:
 *   POST /api/v1/pairing/exchange       — accepts any canonical code once, issues a session
 *   GET  /api/v1/glass/snapshot         — two immutable scenes, exact digests
 *   GET  /api/v1/glass/scenes           — the feed; scene 2 appears ~20s after the first
 *                                         snapshot read, so the walk's advance station is real
 *   POST /api/v1/operator/commands      — receipts with recomputed digests (the wire body is
 *                                         canonical, so re-stringifying JSON.parse of it
 *                                         reproduces the exact canonical bytes)
 *   GET  /api/v1/operator/commands      — empty readback, retention stated
 *   GET  /api/v1/glass/venue-readouts/… — one measured readout, stated absences for the rest
 *   POST /api/v1/presentation/*        — 404: the witness is deliberately unmounted here, so
 *                                         the walk exercises the quiet stated-absence chip
 *
 * Run (the walk's self-test wires this up):
 *   node qa/mockcore.mjs --port 43991 --origin http://127.0.0.1:4179
 */

import { createHash, randomBytes } from "node:crypto";
import { createServer } from "node:http";

const argv = process.argv.slice(2);
function flag(name, fallback) {
  const index = argv.indexOf(name);
  return index >= 0 && index + 1 < argv.length ? argv[index + 1] : fallback;
}
const port = Number(flag("--port", "43991"));
const pageOrigin = flag("--origin", "http://127.0.0.1:4179");

const sha256hex = (text) => createHash("sha256").update(text, "utf8").digest("hex");
const digest = (text) => `sha256:${sha256hex(text)}`;

// ── the pairing session ────────────────────────────────────────────────────────────────────
const originTag = sha256hex("joshi.pairing.origin.v1\0" + pageOrigin);
const session = {
  contract: "joshi.pairing.session",
  schemaVersion: 1,
  sessionId: `pair-session-${originTag}-1-1`,
  origin: pageOrigin,
  epoch: "1",
  expiresAt: "2027-01-01T00:00:00.000000Z",
  scopes: ["cockpit_read", "operator_evidence_write", "presentation_evidence_write"],
  authority: "read_only_no_execution",
  capability: `jpc1_${randomBytes(32).toString("hex")}`,
};

// ── two immutable scenes ───────────────────────────────────────────────────────────────────
// Object literals are written in EXACT contract/v1.ts schema order, so JSON.stringify of them
// is the canonical encoding the client recomputes after its schema-ordered parse.
const T0 = 1787940000;
function candle(offset, open, close, high, low) {
  return {
    timeUnix: String(T0 + offset),
    knownAt: "2026-08-24T18:00:05.000000Z",
    open,
    high,
    low,
    close,
    volumeTokens: "1200.5",
  };
}
// A 1-second path with one 9-second silence in the middle: the gap discipline stays visible.
const candles = [];
for (let index = 0; index < 14; index += 1) {
  const price = (0.0000031 + index * 0.0000001).toFixed(7);
  candles.push(candle(index, price, price, price, price));
}
for (let index = 0; index < 14; index += 1) {
  const price = (0.0000045 - index * 0.00000005).toFixed(8);
  candles.push(candle(23 + index, price, price, price, price));
}

const evidence = (id, field, note, cls = "observed") => ({
  id,
  sourceId: "pump.fun.http.v1",
  field,
  evidenceClass: cls,
  observedAt: null,
  ingestedAt: "2026-08-24T18:00:01.000000Z",
  knownAt: "2026-08-24T18:00:02.000000Z",
  status: "available",
  note,
});

const MINT1 = "WALKmint1111111111111111111111111111111111";
const MINT2 = "WALKmint2222222222222222222222222222222222";
const MINT3 = "WALKmint3333333333333333333333333333333333";
// The multichain listing (pump went multichain): an EVM coin whose id is its 0x address —
// exactly the rows Ember saw leading the real board. The provider claims its chain; the
// cockpit's venue scope keeps it off the default hunt and the chain chip marks it under
// "All chains".
const MINT4 = "0x00eB5459c2c60a2a614C536846F225ED88f10ae8";
const SOLANA_CHAIN_ID = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp";

// Coin art the mock serves ITSELF (see the /art/ route below): the walk must exercise a real
// cross-origin <img> fetch under the seam's security attributes without touching any provider.
const ART1 = `http://127.0.0.1:${port}/art/walk1.svg`;
const artSvg = (background, glyph) =>
  `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>`
  + `<rect width='64' height='64' fill='${background}'/>`
  + `<circle cx='32' cy='32' r='17' fill='${glyph}'/></svg>`;

// The first scene's render clock, the anchor every provider clock below derives from —
// derived, not hand-copied, so the epoch strings cannot disagree with the ISO clocks.
const RENDERED1_MS = Date.parse("2026-08-24T18:00:06.000000Z");

// Movers flow for the walk coins. serverTs sits at the scene's own render second.
const flowAt = (ts) => ([
  { window: "5m", volumeSol: "2.1000", volumeUsd: "410.00", txns: "18", traders: "11", serverTsUnixMs: ts },
  { window: "1h", volumeSol: "16.8000", volumeUsd: "3220.00", txns: "150", traders: "64", serverTsUnixMs: ts },
  // 24h states no trader count: the omitted-traders absence stays walkable.
  { window: "24h", volumeSol: "120.5000", volumeUsd: "23100.00", txns: "1180", serverTsUnixMs: ts },
]);

function candidates(mcap1) {
  return [
    {
      id: MINT4,
      mint: MINT4,
      symbol: null,
      name: null,
      board: "new",
      lifecycle: "unknown",
      firstKnownAt: "2026-08-24T17:59:50.000000Z",
      lastObservedAt: null,
      rank: null,
      metrics: {
        priceSol: null,
        marketCapUsd: "8900.00",
        change5mBps: null,
        ageSeconds: null,
        activity: "unknown",
        quoteSizeSol: null,
        executableExitSol: null,
      },
      attentionReason: "Mock multichain listing: the provider claims a non-Solana chain.",
      socialSummary: "No social source was acquired in this cut.",
      tags: ["multichain"],
      watched: null,
      episodeId: null,
      evidence: [
        evidence("obs:walk4:01", "mint", "Named by the mock discovery read."),
        evidence("obs:walk4:02:claim-chainId", "chainId", "The provider's verbatim chain_id for this listing."),
      ],
      candles: [],
      chainId: "eip155:8453",
    },
    {
      id: MINT1,
      mint: MINT1,
      symbol: "WALK1",
      name: "Parity Walk One",
      board: "trending",
      lifecycle: "bonding",
      firstKnownAt: "2026-08-24T17:55:00.000000Z",
      lastObservedAt: "2026-08-24T18:00:00.000000Z",
      rank: "1",
      metrics: {
        priceSol: "0.0000038",
        marketCapUsd: mcap1,
        change5mBps: "312",
        ageSeconds: "540",
        activity: "two_sided",
        quoteSizeSol: null,
        executableExitSol: null,
      },
      attentionReason: "Mock coin for the harness self-test; carries a full glance row.",
      socialSummary: "No social source was acquired in this cut.",
      tags: ["coin_metadata_observed", "market_cap_from_usd_market_cap", "market_cap_fields_disagree"],
      watched: null,
      episodeId: null,
      evidence: [
        evidence("obs:walk1:01", "mint", "Named by the mock discovery read."),
        evidence("obs:walk1:02:claim-symbol", "symbol", "Provider claim copied from the mock read."),
        evidence("obs:walk1:03:claim-name", "name", "Provider claim copied from the mock read."),
        evidence(
          "obs:walk1:04:claim-metrics-marketCapUsd",
          "metrics.marketCapUsd",
          `The provider asserts two USD market caps in the same document: usd_market_cap=${mcap1} (rendered) and market_cap_usd=99123.40 (differs); neither is averaged and the rendered field is named.`,
        ),
        evidence("obs:walk1:05:claim-imageUri", "imageUri", "Provider-asserted art URL; JOSHI does not host the bytes."),
        evidence("obs:walk1:06:claim-createdAtUnixMs", "createdAtUnixMs", "Provider creation clock copied verbatim from the coin's own record."),
        evidence("obs:walk1:07:claim-flow", "flow", "Movers-tap window claims retained verbatim."),
        evidence("obs:walk1:08:claim-chainId", "chainId", "The provider's verbatim chain_id for this listing."),
      ],
      candles,
      // The parity-density seam, in EXACT contract/v1.ts key order (after candles): the
      // digest is computed over these literal bytes, so the order is load-bearing here.
      imageUri: ART1,
      description: "Mock walk coin one: the full parity-density record, self-served art included.",
      replyCount: "412",
      athMarketCapUsd: "90241.10",
      athAtUnixMs: String(RENDERED1_MS - 3_600_000),
      createdAtUnixMs: String(RENDERED1_MS - 540_000),
      lastTradeAtUnixMs: String(RENDERED1_MS - 2_000),
      graduated: false,
      verified: true,
      nsfw: false,
      currentlyLive: true,
      flow: flowAt(String(RENDERED1_MS)),
      chainId: SOLANA_CHAIN_ID,
    },
    {
      id: MINT2,
      mint: MINT2,
      symbol: "WALK2",
      name: "Parity Walk Two",
      board: "new",
      lifecycle: "graduated",
      firstKnownAt: "2026-08-24T17:58:00.000000Z",
      lastObservedAt: null,
      rank: "2",
      metrics: {
        priceSol: null,
        marketCapUsd: "12800.00",
        change5mBps: "-88",
        ageSeconds: "120",
        activity: "quiet",
        quoteSizeSol: null,
        executableExitSol: null,
      },
      attentionReason: "Mock coin two; no price path, so the row states its dashes.",
      socialSummary: "No social source was acquired in this cut.",
      tags: ["coin_metadata_observed"],
      watched: null,
      episodeId: null,
      evidence: [
        evidence("obs:walk2:01", "mint", "Named by the mock discovery read."),
        evidence("obs:walk2:02:claim-symbol", "symbol", "Provider claim copied from the mock read."),
        evidence("obs:walk2:03:claim-flow", "flow", "Movers-tap window claims retained verbatim."),
      ],
      candles: [],
      // Flow with no price path: the grid card must plot claimed volume, never invent candles.
      description: "Mock walk coin two: movers flow only, so the card's chart is volume.",
      createdAtUnixMs: String(RENDERED1_MS - 120_000),
      flow: [
        { window: "1h", volumeSol: "5.0000", volumeUsd: "900.00", txns: "40", traders: "12", serverTsUnixMs: String(RENDERED1_MS) },
        { window: "24h", volumeSol: "21.0000", volumeUsd: "3900.00", txns: "260", serverTsUnixMs: String(RENDERED1_MS) },
      ],
      chainId: SOLANA_CHAIN_ID,
    },
    {
      id: MINT3,
      mint: MINT3,
      symbol: null,
      name: null,
      board: "callouts",
      lifecycle: "unknown",
      firstKnownAt: "2026-08-24T17:59:30.000000Z",
      lastObservedAt: null,
      rank: null,
      metrics: {
        priceSol: null,
        marketCapUsd: null,
        change5mBps: null,
        ageSeconds: null,
        activity: "unknown",
        quoteSizeSol: null,
        executableExitSol: null,
      },
      attentionReason: "Mock coin three; ticker unobserved, every figure an explicit absence.",
      socialSummary: "One retained callout names this mint.",
      tags: ["chain_observed", "ticker_unobserved", "no_price_observed"],
      watched: null,
      episodeId: null,
      evidence: [evidence("obs:walk3:01", "mint", "Named by retained chain bytes.")],
      candles: [],
    },
  ];
}

function view(sceneId, catalogCommit, renderedAt, mcap1) {
  return {
    contract: "joshi.glass.view",
    schemaVersion: 1,
    mode: "witnessed",
    sceneId,
    basisSceneId: null,
    asOf: {
      catalogCommit,
      sources: [
        {
          sourceId: "pump.fun.http.v1",
          deliveredThrough: catalogCommit,
          cursors: [],
          receivedThrough: renderedAt,
        },
      ],
      chain: null,
      projections: [],
      renderedAt,
    },
    payload: {
      sources: [
        {
          id: "pump.fun.http.v1",
          label: "pump.fun HTTP (mock)",
          status: "fixture",
          lastObservedAt: renderedAt,
          lastIngestedAt: renderedAt,
          coverage: "mock discovery plus one hot tap",
          note: "Mock core for the parity walk self-test; nothing here is a market fact.",
        },
      ],
      candidates: candidates(mcap1),
      episodes: [],
      socialEvents: [
        {
          id: "callout:walk3:01",
          candidateId: MINT3,
          eventAt: "2026-08-24T17:59:00.000000Z",
          knownAt: "2026-08-24T17:59:45.000000Z",
          kind: "callout",
          author: "mock_caller",
          text: "Mock callout: multiple 2.4x as of this view (self-test data, not a market fact).",
          evidence: evidence("callout:walk3:01:ev", "socialEvents", "Retained mock callout body.", "attested"),
        },
      ],
    },
  };
}

const SCENE1 = "scene-live-walkmock00000000000000000000001";
const SCENE2 = "scene-live-walkmock00000000000000000000002";
const view1 = view(SCENE1, "3", "2026-08-24T18:00:06.000000Z", "45120.55");
const view2 = view(SCENE2, "4", "2026-08-24T18:03:06.000000Z", "47881.10");
const snapshot = (theView) => ({
  contract: "joshi.glass.snapshot",
  schemaVersion: 1,
  snapshotDigest: digest(JSON.stringify(theView)),
  transport: "loopback",
  recordingAuthority: "read_record_replay_only",
  view: theView,
});
const snapshot1 = snapshot(view1);
const snapshot2 = snapshot(view2);

let firstSnapshotAt = null;
const SECOND_SCENE_AFTER_MS = 20_000;

const feedEntry = (sceneId, cutoff, derivedAt, viewDigest) => ({
  sceneId,
  derivedAt,
  cutoffCommitSeq: cutoff,
  subjectCount: "4",
  observationCount: cutoff,
  viewDigest,
  derivationVersion: "live_surface.v5",
  sceneRetention: "served_not_yet_durable",
  retiredReason: null,
});

function feed() {
  const grown = firstSnapshotAt !== null && Date.now() - firstSnapshotAt > SECOND_SCENE_AFTER_MS;
  const scenes = [feedEntry(SCENE1, "3", "2026-08-24T18:00:06.000000Z", snapshot1.snapshotDigest)];
  if (grown) scenes.unshift(feedEntry(SCENE2, "4", "2026-08-24T18:03:06.000000Z", snapshot2.snapshotDigest));
  return {
    contract: "joshi.core.scene_feed",
    schemaVersion: 1,
    authority: "read_only_no_execution",
    sourceId: "pump.fun.http.v1",
    scenes,
    catalog: {
      outcome: grown ? "advanced" : "unchanged",
      lastContactAt: "2026-08-24T18:03:00.000000Z",
      detail: null,
      basisCommitSeq: grown ? "4" : "3",
    },
  };
}

// One measured venue readout so the coin page's venue slot renders real numbers in the walk.
const measuredReadout = {
  contract: "joshi.glass.venue_readout",
  schemaVersion: 1,
  authority: "read_record_replay_only",
  mint: MINT1,
  venueKind: "pump bonding curve",
  venueKindLabel: "pump_bonding_curve",
  venueAccount: "WALKcurveAccount111111111111111111111111111",
  venueBinding: "mock capture (self-test)",
  feeFloorBps: "247",
  feeFloorProbeSol: "0.05000000",
  declaredLiftBps: "300",
  breakEvenClip: {
    smallestSol: "0.00120000",
    largestSol: "0.41000000",
    smallestHurdleBps: "299",
    largestHurdleBps: "300",
  },
  feeTier: { absence: "A bonding curve carries no market-cap fee tier table." },
  pessimisticTierBranch: null,
  stateAge: {
    contextSlot: "312450000",
    requestedCommitment: "finalized",
    chainToReceipt: { absence: "The mock capture states no block time." },
    receivedAtUnixMs: String(Date.now()),
    clockId: "mockcore-wall-clock",
    drift: { absence: "No second read exists to measure drift against." },
  },
  declaredCosts: "venue fee floor only; network fees and tips are not included (mock).",
  unsupported: ["This is the walk self-test's mock readout; nothing here describes a real venue."],
};

let commitSeq = 100;

const server = createServer((request, response) => {
  const url = new URL(request.url, `http://127.0.0.1:${port}`);
  // The venue-readout client calls the core origin directly (VITE_JOSHI_CORE_URL), which is
  // cross-origin from the vite page — exactly as the real core is — so CORS mirrors it.
  const cors = {
    "access-control-allow-origin": pageOrigin,
    "access-control-allow-headers": "accept, content-type, x-joshi-pairing-token",
    "access-control-allow-methods": "GET, POST, OPTIONS",
  };
  if (request.method === "OPTIONS") {
    response.writeHead(204, cors);
    return response.end();
  }
  const answer = (status, body) => {
    response.writeHead(status, { "content-type": "application/json", "cache-control": "no-store", ...cors });
    response.end(JSON.stringify(body));
  };

  if (request.method === "POST" && url.pathname === "/api/v1/pairing/exchange") {
    return answer(200, session);
  }
  if (request.method === "GET" && url.pathname === "/api/v1/glass/snapshot") {
    if (firstSnapshotAt === null) firstSnapshotAt = Date.now();
    const basis = url.searchParams.get("basisSceneId");
    if (url.searchParams.get("mode") !== "witnessed") return answer(409, { code: "mode_mismatch" });
    if (basis === SCENE1) return answer(200, snapshot1);
    if (basis === SCENE2) return answer(200, snapshot2);
    return answer(404, { code: "scene_not_found" });
  }
  if (request.method === "GET" && url.pathname === "/api/v1/glass/scenes") {
    return answer(200, feed());
  }
  const sliceMatch = url.pathname.match(/^\/api\/v1\/glass\/scenes\/([^/]+)\/candidates\/([^/]+)$/);
  if (request.method === "GET" && sliceMatch) {
    const sceneId = decodeURIComponent(sliceMatch[1]);
    const candidateId = decodeURIComponent(sliceMatch[2]);
    const source = sceneId === SCENE1 ? snapshot1 : sceneId === SCENE2 ? snapshot2 : null;
    if (!source) return answer(404, { code: "scene_not_found", detail: "no retained scene carries that id" });
    const list = source.view.payload.candidates;
    const ordinal = list.findIndex((candidate) => candidate.id === candidateId);
    if (ordinal < 0) {
      return answer(404, {
        code: "candidate_not_rendered",
        detail: `this scene renders ${list.length} candidate(s) and none carries that id; an `
          + "elided candidate remains observed in the catalog — falling out of render is a "
          + "bound, never a denial",
      });
    }
    return answer(200, {
      contract: "joshi.glass.candidate_slice",
      schemaVersion: 1,
      sceneId,
      viewDigest: source.snapshotDigest,
      mode: "witnessed",
      catalogCommit: source.view.asOf.catalogCommit,
      renderedAt: source.view.asOf.renderedAt,
      renderedCandidateCount: String(list.length),
      renderedOrdinal: String(ordinal),
      candidate: list[ordinal],
    });
  }
  if (request.method === "POST" && url.pathname === "/api/v1/operator/commands") {
    let body = "";
    request.on("data", (chunk) => { body += chunk; });
    request.on("end", () => {
      try {
        const command = JSON.parse(body);
        commitSeq += 1;
        answer(202, {
          contract: "joshi.store.command_receipt",
          schemaVersion: 1,
          catalogId: "walk-selftest-mock",
          catalogSchema: "joshi.sqlite.v24",
          batchId: `operator:${command.commandId}`,
          commandId: command.commandId,
          // The client posts its canonical encoding, so re-stringifying the parse of the
          // exact wire bytes reproduces the canonical command and payload byte-for-byte.
          commandPayloadDigest: digest(JSON.stringify(command.payload)),
          commandDigest: digest(JSON.stringify(command)),
          scene: command.scene,
          commitSeq: String(commitSeq),
          status: "accepted",
        });
      } catch (error) {
        answer(400, { code: "unparseable_command", detail: String(error) });
      }
    });
    return;
  }
  if (request.method === "GET" && url.pathname === "/api/v1/operator/commands") {
    return answer(200, {
      contract: "joshi.core.operator_command_readback",
      schemaVersion: 1,
      authority: "read_only_no_execution",
      sceneId: url.searchParams.get("sceneId") ?? SCENE1,
      sceneRetention: "served_not_yet_durable",
      commands: [],
    });
  }
  if (request.method === "GET" && url.pathname.startsWith("/api/v1/glass/venue-readouts/")) {
    const mint = decodeURIComponent(url.pathname.split("/").pop() ?? "");
    if (mint === MINT1) {
      return answer(200, { ...measuredReadout, stateAge: { ...measuredReadout.stateAge, receivedAtUnixMs: String(Date.now()) } });
    }
    return answer(404, { code: "venue_readout_not_measured", detail: "the mock capture names no venue for this mint" });
  }
  // Self-served coin art: a cross-origin image fetch the seam's attributes really exercise.
  // `crossorigin=anonymous` on the cockpit's <img> makes this a CORS request, so the wildcard
  // allow-origin (with no credentials, exactly as the seam demands) is what lets it render.
  if (request.method === "GET" && url.pathname === "/art/walk1.svg") {
    response.writeHead(200, {
      "content-type": "image/svg+xml",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
    });
    return response.end(artSvg("#2e6b4f", "#b9f7d3"));
  }
  // The presentation witness is deliberately unmounted: the walk must see the quiet chip.
  return answer(404, { code: "not_found" });
});

server.listen(port, "127.0.0.1", () => {
  console.log(`mockcore listening on http://127.0.0.1:${port} (page origin ${pageOrigin})`);
});
