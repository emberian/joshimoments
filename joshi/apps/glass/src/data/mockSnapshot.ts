import type {
  Candle,
  Candidate,
  Episode,
  EvidenceRef,
  GlassPayloadV1,
  GlassSnapshotV1,
  GlassViewV1,
  ReplayMode,
  SocialEvent,
  SourceHealth,
} from "../contract/v1";
import { digestGlassView, parseGlassSnapshotV1 } from "../contract/v1";

const BASE_TIME = 1_786_904_520;
const WITNESSED_AT = "2026-08-16T18:42:15.000000Z";
const CUTOFF_AT = "2026-08-16T18:35:00.000000Z";
const RETROSPECTIVE_AT = "2026-08-16T19:08:00.000000Z";
const WITNESSED_SCENE_ID = "scene-20260816-184215-witnessed";

function micro(value: string): string {
  const withFraction = value.replace(/\.(\d{1,6})Z$/, (_, fraction: string) => `.${fraction.padEnd(6, "0")}Z`);
  return withFraction.endsWith("Z") && !withFraction.includes(".")
    ? withFraction.replace(/Z$/, ".000000Z")
    : withFraction;
}

function sortBy<T>(values: T[], identity: (value: T) => string): T[] {
  return values.sort((a, b) => identity(a) < identity(b) ? -1 : identity(a) > identity(b) ? 1 : 0);
}

function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
    Object.values(value as Record<string, unknown>).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

type CandidateSeed = {
  id: string;
  mint: string;
  symbol: string;
  name: string;
  board: Candidate["board"];
  lifecycle: Candidate["lifecycle"];
  ranks: { knowledge_cutoff?: number; witnessed?: number; retrospective: number };
  firstKnownAt: string;
  price: string;
  marketCap: string;
  change5mBps: string;
  ageSeconds: string;
  activity: Candidate["metrics"]["activity"];
  reason: string;
  social: string;
  tags: string[];
  watched?: boolean;
  episodeId?: string;
  phase: number;
  /**
   * The parity-density seam's optional provider-record fields, carried by SOME seeds so the
   * dense board, grid cards, and trending strip render against fixture data — and absent
   * from others so every dash stays exercised. Art is a data: URI on purpose: the offline
   * fixture must fetch nothing from any provider.
   */
  seam?: Partial<Pick<Candidate,
    | "imageUri" | "description" | "replyCount" | "athMarketCapUsd" | "athAtUnixMs"
    | "createdAtUnixMs" | "lastTradeAtUnixMs" | "graduated" | "verified" | "nsfw"
    | "currentlyLive" | "flow" | "chainId">>;
};

/** Tiny self-contained coin art for the fixture: a data: URI fetches nothing from anywhere. */
function fixtureArt(background: string, glyph: string): string {
  return "data:image/svg+xml;utf8,"
    + `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>`
    + `<rect width='64' height='64' fill='%23${background}'/>`
    + `<circle cx='32' cy='32' r='17' fill='%23${glyph}'/></svg>`;
}

/** The provider's verbatim Solana chain id, as the multichain records carry it. */
const SOLANA_CHAIN_ID = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp";

function fixtureFlow(scale: number): Candidate["flow"] {
  const at = String(Date.parse("2026-08-16T18:42:10Z"));
  return [
    { window: "5m" as const, volumeSol: (2.1 * scale).toFixed(4), volumeUsd: (410 * scale).toFixed(2), txns: String(18 * scale), traders: String(11 * scale), serverTsUnixMs: at },
    { window: "15m" as const, volumeSol: (5.4 * scale).toFixed(4), volumeUsd: (1030 * scale).toFixed(2), txns: String(47 * scale), traders: String(23 * scale), serverTsUnixMs: at },
    { window: "1h" as const, volumeSol: (16.8 * scale).toFixed(4), volumeUsd: (3220 * scale).toFixed(2), txns: String(150 * scale), traders: String(64 * scale), serverTsUnixMs: at },
    // 24h deliberately states no trader count: the movers document sometimes omits it, and
    // the fixture keeps that absence renderable.
    { window: "24h" as const, volumeSol: (120.5 * scale).toFixed(4), volumeUsd: (23100 * scale).toFixed(2), txns: String(1180 * scale), serverTsUnixMs: at },
  ];
}

const seeds: CandidateSeed[] = [
  {
    id: "radon", mint: "RADON9BkJ3Wj5mT8p2Qx7sV4nL6cH1fZ", symbol: "RADON", name: "Radon",
    board: "watch", lifecycle: "graduated", ranks: { knowledge_cutoff: 2, witnessed: 2, retrospective: 4 },
    firstKnownAt: "2026-08-16T18:34:03Z", price: "0.00000004182", marketCap: "168420.00",
    change5mBps: "312", ageSeconds: "3940", activity: "two_sided",
    reason: "Runner retained after one realized clip; graph remains active.",
    social: "Repeat participants are still replying; no verified catalyst recorded.",
    tags: ["held", "runner", "two-sided"], watched: true, episodeId: "episode-radon", phase: 4,
    seam: {
      imageUri: fixtureArt("2e6b4f", "b9f7d3"),
      description: "A noble gas that refuses to decay quietly.",
      replyCount: "412",
      athMarketCapUsd: "241000.00",
      athAtUnixMs: String(Date.parse("2026-08-16T17:58:00Z")),
      createdAtUnixMs: String(Date.parse("2026-08-16T17:36:35Z")),
      lastTradeAtUnixMs: String(Date.parse("2026-08-16T18:42:01Z")),
      verified: true,
      flow: fixtureFlow(3),
      chainId: SOLANA_CHAIN_ID,
    },
  },
  {
    id: "earthcoin", mint: "EARTH7FxQ2vN9sC5mL1pT8kR4bW6jHdZ", symbol: "EarthCoin", name: "Earth Coin",
    board: "watch", lifecycle: "graduated", ranks: { knowledge_cutoff: 1, witnessed: 5, retrospective: 7 },
    firstKnownAt: "2026-08-16T18:21:40Z", price: "0.00000002741", marketCap: "109830.00",
    change5mBps: "-88", ageSeconds: "8640", activity: "building",
    reason: "Exited on the graph; intentionally watching flat for a possible re-entry.",
    social: "Community posting persists while market flow pauses.",
    tags: ["episode live", "re-entry", "watching flat"], watched: true, episodeId: "episode-earth", phase: 1,
    seam: {
      description: "The home team's coin.",
      graduated: true,
      createdAtUnixMs: String(Date.parse("2026-08-16T16:18:00Z")),
      athMarketCapUsd: "199500.00",
      chainId: SOLANA_CHAIN_ID,
    },
  },
  {
    id: "crashius", mint: "CRASH8MmQ5cV2pN7sD4kL9xF1bT6jHwZ", symbol: "CRASHIUS", name: "Crashius Maximus",
    board: "watch", lifecycle: "graduated", ranks: { knowledge_cutoff: 4, witnessed: 7, retrospective: 9 },
    firstKnownAt: "2026-08-16T18:11:12Z", price: "0.00000001972", marketCap: "78880.00",
    change5mBps: "146", ageSeconds: "11720", activity: "two_sided",
    reason: "Small remainder preserved after profit recognition.",
    social: "Low-volume but recurring community authors remain present.",
    tags: ["runner", "small exposure"], watched: true, episodeId: "episode-crashius", phase: 2,
  },
  {
    id: "fable", mint: "FABLE5HsP8nQ1vL4cT7mR2kD9bW6jXzA", symbol: "FABLE", name: "Fable Market",
    board: "trending", lifecycle: "bonding", ranks: { witnessed: 1, retrospective: 1 },
    firstKnownAt: "2026-08-16T18:39:22Z", price: "0.00000005210", marketCap: "208400.00",
    change5mBps: "741", ageSeconds: "780", activity: "bursting",
    reason: "Fast rank climb with broad two-sided prints.",
    social: "Three independent threads mention the same source event.", tags: ["fast", "multi-thread"], phase: 7,
    seam: {
      imageUri: fixtureArt("6b2e5c", "f7d3ec"),
      description: "Every market is a story; this one admits it.",
      replyCount: "1288",
      athMarketCapUsd: "212300.00",
      athAtUnixMs: String(Date.parse("2026-08-16T18:41:00Z")),
      createdAtUnixMs: String(Date.parse("2026-08-16T18:29:22Z")),
      lastTradeAtUnixMs: String(Date.parse("2026-08-16T18:42:12Z")),
      currentlyLive: true,
      flow: fixtureFlow(9),
      chainId: SOLANA_CHAIN_ID,
    },
  },
  {
    id: "orbitfan", mint: "ORBIT4JxM7qT2vN8cL5pR1kD9bW3sHzE", symbol: "ORBITFAN", name: "Orbit Fan Club",
    board: "callouts", lifecycle: "bonding", ranks: { witnessed: 3, retrospective: 2 },
    firstKnownAt: "2026-08-16T18:37:31Z", price: "0.00000003425", marketCap: "137000.00",
    change5mBps: "428", ageSeconds: "1220", activity: "building",
    reason: "Unverified fan coin; community identity is becoming coherent.",
    social: "Represented person has not been verified as aware or participating.",
    tags: ["fancoin", "identity unresolved"], phase: 5,
  },
  {
    id: "wetpaint", mint: "WETPT6NcQ3vM9sL2pT8kR5bD1jHxZaF", symbol: "WETPAINT", name: "Wet Paint",
    board: "new", lifecycle: "bonding", ranks: { witnessed: 4, retrospective: 5 },
    firstKnownAt: "2026-08-16T18:40:14Z", price: "0.00000001132", marketCap: "45280.00",
    change5mBps: "93", ageSeconds: "440", activity: "two_sided",
    reason: "Young coin with repeated shallow dips; not yet classified.",
    social: "Conversation is mostly launch-local and has not diffused.", tags: ["new", "unclassified"], phase: 0,
    seam: {
      imageUri: fixtureArt("6b4f2e", "f7e3b9"),
      description: "Do not touch.",
      nsfw: true,
      createdAtUnixMs: String(Date.parse("2026-08-16T18:34:54Z")),
      flow: fixtureFlow(1),
      chainId: SOLANA_CHAIN_ID,
    },
  },
  {
    id: "moss", mint: "MOSSX3Jq8vN1cL5pT7kR4bD9mW2sHzE", symbol: "MOSS", name: "Moss Protocol",
    board: "live", lifecycle: "migrating", ranks: { witnessed: 6, retrospective: 3 },
    firstKnownAt: "2026-08-16T18:38:49Z", price: "0.00000004618", marketCap: "184720.00",
    change5mBps: "506", ageSeconds: "1830", activity: "bursting",
    reason: "Migration boundary and a sudden change in trade cadence.",
    social: "Callouts arrived after chain activity accelerated.", tags: ["hot", "migration"], phase: 8,
    seam: {
      description: "Soft infrastructure for hard moves.",
      replyCount: "97",
      currentlyLive: true,
      createdAtUnixMs: String(Date.parse("2026-08-16T18:12:19Z")),
      flow: fixtureFlow(6),
      chainId: SOLANA_CHAIN_ID,
    },
  },
  {
    id: "copper", mint: "COPPR2Fm7qV4nL9cT1pR6kD8bW5sHxA", symbol: "COPPER", name: "Copper Wire",
    board: "trending", lifecycle: "bonding", ranks: { knowledge_cutoff: 3, witnessed: 8, retrospective: 8 },
    firstKnownAt: "2026-08-16T18:32:01Z", price: "0.00000002284", marketCap: "91360.00",
    change5mBps: "-214", ageSeconds: "2810", activity: "two_sided",
    reason: "Deep pullback, but both sides are still printing.",
    social: "No fresh social evidence inside this served view.", tags: ["drawdown", "two-sided"], phase: 3,
  },
  {
    id: "afterglow", mint: "AFTER9JmQ2vN6cL4pT8kR1bD7wX3sHzE", symbol: "AFTER", name: "Afterglow",
    board: "live", lifecycle: "graduated", ranks: { retrospective: 6 },
    firstKnownAt: "2026-08-16T18:47:20Z", price: "0.00000003914", marketCap: "156560.00",
    change5mBps: "661", ageSeconds: "2210", activity: "bursting",
    reason: "Appeared after the witnessed scene and exists only in the later DTO.",
    social: "Later evidence links two previously separate participant clusters.",
    tags: ["cluster link", "late evidence"], phase: 6,
  },
  {
    id: "zorbit", mint: "0x00eB5459c2c60a2a614C536846F225ED88f10ae8", symbol: "ZORB", name: "Zorbit",
    board: "new", lifecycle: "unknown", ranks: { witnessed: 10, retrospective: 11 },
    firstKnownAt: "2026-08-16T18:41:10Z", price: "0.00000001450", marketCap: "52000.00",
    change5mBps: "77", ageSeconds: "890", activity: "building",
    reason: "A multichain pump listing: the provider claims a non-Solana chain for it.",
    social: "No social source was acquired in this cut.",
    tags: ["multichain"], phase: 2,
    seam: { chainId: "eip155:8453", description: "An orbit on another chain entirely." },
  },
  {
    id: "lilypad", mint: "LILYP7Jq4vN2cM8pT1kR6bD9wX5sHzA", symbol: "LILY", name: "Lily Pad",
    board: "new", lifecycle: "bonding", ranks: { witnessed: 9, retrospective: 10 },
    firstKnownAt: "2026-08-16T18:41:50Z", price: "0.00000000891", marketCap: "35640.00",
    change5mBps: "21", ageSeconds: "325", activity: "quiet",
    reason: "Visible denominator example; no current operator thesis.",
    social: "One launch post and no observed replies.", tags: ["quiet"], phase: 0,
  },
];

function horizon(mode: ReplayMode): string {
  if (mode === "knowledge_cutoff") return CUTOFF_AT;
  if (mode === "witnessed") return WITNESSED_AT;
  return RETROSPECTIVE_AT;
}

function evidence(
  candidateId: string,
  sourceId: string,
  field: string,
  evidenceClass: EvidenceRef["evidenceClass"],
  note: string,
  knownAt: string,
  status: EvidenceRef["status"] = "available",
): EvidenceRef {
  const observed = new Date(Date.parse(knownAt) - 3_000).toISOString();
  const ingested = new Date(Date.parse(knownAt) - 1_000).toISOString();
  return {
    id: `${candidateId}:${sourceId}:${field}`,
    sourceId,
    field,
    evidenceClass,
    observedAt: micro(observed),
    ingestedAt: micro(ingested),
    knownAt: micro(knownAt),
    status,
    note,
  };
}

function candles(phase: number, mode: ReplayMode): Candle[] {
  const base = 0.000000018 + phase * 0.0000000017;
  return Array.from({ length: 42 }, (_, index) => {
    const drift = index * (0.00000000024 + phase * 0.00000000001);
    const wave = Math.sin((index + phase) / 2.9) * 0.0000000032;
    const pulse = index > 27 ? Math.sin(index * 1.8) * 0.0000000014 : 0;
    const close = Math.max(base + drift + wave + pulse, 0.000000001);
    const open = Math.max(close - Math.sin(index * 0.91) * 0.0000000011, 0.000000001);
    const high = Math.max(open, close) + 0.0000000014;
    const low = Math.max(Math.min(open, close) - 0.0000000011, 0.0000000001);
    const eventUnix = BASE_TIME + index * 30;
    return {
      timeUnix: String(eventUnix),
      knownAt: micro(new Date((eventUnix + (index < 24 ? 2 : 7)) * 1000).toISOString()),
      open: open.toFixed(12), high: high.toFixed(12), low: low.toFixed(12), close: close.toFixed(12),
      volumeTokens: String(110_000 + index * 9_700 + phase * 13_000),
    };
  }).filter((candle) => Date.parse(candle.knownAt) <= Date.parse(horizon(mode)));
}

function candidateFor(seed: CandidateSeed, mode: ReplayMode): Candidate | null {
  const rank = seed.ranks[mode];
  if (rank === undefined) return null;
  const laterRadon = mode === "retrospective" && seed.id === "radon";
  const knownAt = horizon(mode);
  const candidateEvidence = sortBy([
    evidence(seed.id, "pump-board", "rank", "observed", "Rank served inside this immutable view.", knownAt),
    evidence(seed.id, "chain-tape", "metrics.priceSol", "derived", "Derived observation; not an executable quote.", knownAt),
    evidence(seed.id, "pump-social", "socialSummary", "interpreted", "View-local summary; raw fixture events remain separate.", knownAt, mode === "witnessed" ? "gap" : "available"),
    // The seam fields carry their claims like any other field: an evidence row per family,
    // class observed, its note the sentence a hover renders verbatim.
    ...(seed.seam?.createdAtUnixMs !== undefined
      ? [evidence(seed.id, "pump-board", "createdAtUnixMs", "observed", "Provider creation clock copied verbatim from the coin's own record.", knownAt)]
      : []),
    ...(seed.seam?.imageUri !== undefined
      ? [evidence(seed.id, "pump-board", "imageUri", "observed", "Provider-asserted art URL; JOSHI does not host the bytes.", knownAt)]
      : []),
    ...(seed.seam?.flow !== undefined
      ? [evidence(seed.id, "pump-board", "flow", "observed", "Movers-tap window claims retained verbatim for this fixture coin.", knownAt)]
      : []),
    ...(seed.seam?.chainId !== undefined
      ? [evidence(seed.id, "pump-board", "chainId", "observed", "The provider's verbatim chain_id for this multichain listing.", knownAt)]
      : []),
  ], (item) => item.id);
  return {
    ...seed.seam,
    id: seed.id,
    mint: seed.mint,
    symbol: seed.symbol,
    name: seed.name,
    board: seed.board,
    lifecycle: seed.lifecycle,
    firstKnownAt: micro(seed.firstKnownAt),
    lastObservedAt: micro(new Date(Date.parse(knownAt) - 3_000).toISOString()),
    rank: String(rank),
    metrics: {
      priceSol: laterRadon ? "0.00000006249" : seed.price,
      marketCapUsd: laterRadon ? "249999.00" : seed.marketCap,
      change5mBps: laterRadon ? "987" : seed.change5mBps,
      ageSeconds: seed.ageSeconds,
      activity: laterRadon ? "bursting" : seed.activity,
      quoteSizeSol: "0.100000000",
      executableExitSol: seed.episodeId ? (laterRadon ? "0.126420000" : "0.084210000") : null,
    },
    attentionReason: laterRadon ? "Later-only cluster evidence and price expansion; absent from witnessed bytes." : seed.reason,
    socialSummary: laterRadon ? "LATER_SOCIAL_CLUSTER: linked authors appeared only after the witnessed scene." : seed.social,
    tags: laterRadon ? [...seed.tags, "later-cluster"].sort() : [...seed.tags].sort(),
    watched: seed.watched ?? false,
    episodeId: seed.episodeId ?? null,
    evidence: candidateEvidence,
    candles: candles(seed.phase, mode),
  };
}

function sourcesFor(mode: ReplayMode): SourceHealth[] {
  const socialStatus = mode === "retrospective" ? "fresh" : mode === "witnessed" ? "gap" : "degraded";
  const observedAt = micro(new Date(Date.parse(horizon(mode)) - 4_000).toISOString());
  return sortBy([
    { id: "chain-tape", label: "Chain tape", status: "fixture", lastObservedAt: observedAt, lastIngestedAt: micro(new Date(Date.parse(observedAt) + 1_000).toISOString()), coverage: "Mode-local reserve and trade observations.", note: "No RPC or provider credential is present in this browser bundle." },
    { id: "pump-board", label: "Pump attention board", status: "fixture", lastObservedAt: observedAt, lastIngestedAt: micro(new Date(Date.parse(observedAt) + 1_000).toISOString()), coverage: "One exact attention-board projection for this served mode.", note: "Ranks are served facts in this DTO, never client reconstruction." },
    { id: "pump-social", label: "Pump social", status: socialStatus, lastObservedAt: observedAt, lastIngestedAt: micro(new Date(Date.parse(observedAt) + 1_000).toISOString()), coverage: mode === "retrospective" ? "LATER_SOURCE_RECOVERY: the previously visible gap recovered after the scene." : "The current view contains an explicit social coverage limitation.", note: mode === "retrospective" ? "Recovery belongs only to the retrospective DTO." : "Silence is not converted to zero." },
    { id: "wallet-watch", label: "Wallet observation", status: "fixture", lastObservedAt: observedAt, lastIngestedAt: micro(new Date(Date.parse(observedAt) + 1_000).toISOString()), coverage: "Mode-local inventory and episode projection.", note: "Read-only: no key, signer, transaction builder, or provider secret exists here." },
  ] satisfies SourceHealth[], (source) => source.id);
}

function baseEpisodes(): Episode[] {
  return [
    {
      id: "episode-radon", candidateId: "radon", state: "exposed", disposition: "retained runner",
      latestNote: "Recognized a small clip; remainder may still send.", openedAt: micro("2026-08-16T16:22:00Z"), lastChangedAt: micro("2026-08-16T17:04:31Z"),
      accounting: { totalSpentSol: "0.180000000", totalProceedsSol: "0.121500000", realizedNetSol: "0.014600000", remainingCostBasisSol: "0.058500000", executableLiquidationSol: "0.084210000", currentExposureSol: "0.084210000" },
      clips: sortBy([
        { id: "radon-clip-1", label: "initial crackle", openedAt: micro("2026-08-16T16:22:00Z"), closedAt: micro("2026-08-16T16:29:44Z"), realizedNetSol: "0.014600000" },
        { id: "radon-runner", label: "retained runner", openedAt: micro("2026-08-16T16:29:44Z"), closedAt: null, realizedNetSol: "0" },
      ], (clip) => clip.id),
      nextAttention: "Watch graph and community persistence; no automatic action is armed.",
    },
    {
      id: "episode-earth", candidateId: "earthcoin", state: "watching_flat", disposition: "flat, re-entry watch",
      latestNote: "Graph exit completed; keep the episode alive for another local setup.", openedAt: micro("2026-08-16T14:02:18Z"), lastChangedAt: micro("2026-08-16T18:12:09Z"),
      accounting: { totalSpentSol: "0.220000000", totalProceedsSol: "0.236800000", realizedNetSol: "0.011900000", remainingCostBasisSol: null, executableLiquidationSol: null, currentExposureSol: "0" },
      clips: [{ id: "earth-clip-1", label: "entry, exit, flat watch", openedAt: micro("2026-08-16T14:02:18Z"), closedAt: micro("2026-08-16T18:12:09Z"), realizedNetSol: "0.011900000" }],
      nextAttention: "Watching while flat. A future re-entry would begin another inventory interval.",
    },
    {
      id: "episode-crashius", candidateId: "crashius", state: "exposed", disposition: "small retained runner",
      latestNote: "Keep a deliberately small remainder without calling it free.", openedAt: micro("2026-08-15T23:18:12Z"), lastChangedAt: micro("2026-08-16T00:06:55Z"),
      accounting: { totalSpentSol: "0.140000000", totalProceedsSol: "0.112000000", realizedNetSol: "0.006300000", remainingCostBasisSol: "0.028000000", executableLiquidationSol: "0.031740000", currentExposureSol: "0.031740000" },
      clips: [{ id: "crashius-clip-1", label: "partial realization", openedAt: micro("2026-08-15T23:18:12Z"), closedAt: micro("2026-08-16T00:06:55Z"), realizedNetSol: "0.006300000" }],
      nextAttention: "Reassess activity and opportunity cost; no timed exit is represented.",
    },
  ];
}

function episodesFor(mode: ReplayMode): Episode[] {
  const episodes = baseEpisodes();
  if (mode === "retrospective") {
    const earth = episodes.find((episode) => episode.id === "episode-earth");
    if (earth) {
      earth.state = "exposed";
      earth.disposition = "LATER_REENTRY: re-entered after witnessed scene";
      earth.latestNote = "Later reconstruction includes a new inventory interval unavailable to the witnessed scene.";
      earth.lastChangedAt = micro("2026-08-16T18:52:10Z");
      earth.accounting.remainingCostBasisSol = "0.052000000";
      earth.accounting.executableLiquidationSol = "0.055400000";
      earth.accounting.currentExposureSol = "0.055400000";
      earth.clips.push({ id: "earth-reentry-2", label: "later re-entry", openedAt: micro("2026-08-16T18:52:10Z"), closedAt: null, realizedNetSol: "0" });
      sortBy(earth.clips, (clip) => clip.id);
      earth.nextAttention = "Later-only exposed state; never substitute into the witnessed scene.";
    }
  }
  return sortBy(episodes, (episode) => episode.id);
}

function socialEvent(
  id: string,
  candidateId: string,
  eventAt: string,
  knownAt: string,
  kind: SocialEvent["kind"],
  author: string | null,
  text: string,
): SocialEvent {
  return {
    id, candidateId, eventAt: micro(eventAt), knownAt: micro(knownAt), kind, author, text,
    evidence: evidence(candidateId, kind === "gap" ? "coverage-monitor" : "pump-social", `socialEvents.${id}`, "observed", kind === "gap" ? "Collector-declared gap; silence is not inferred." : "Raw mode-local social fixture event.", knownAt, kind === "gap" ? "gap" : "available"),
  };
}

const allSocialEvents = sortBy([
  socialEvent("social-earth-1", "earthcoin", "2026-08-16T18:33:54Z", "2026-08-16T18:33:56Z", "community", "soilkeeper", "Conversation persisted after the wallet became flat."),
  socialEvent("social-orbit-1", "orbitfan", "2026-08-16T18:40:42Z", "2026-08-16T18:40:45Z", "callout", "orbitwatch", "Fan community is linking one coin more consistently than its duplicates."),
  socialEvent("social-orbit-2", "orbitfan", "2026-08-16T18:49:00Z", "2026-08-16T18:49:04Z", "claim", null, "LATER_CLAIM: absent from witnessed view bytes."),
  socialEvent("social-radon-1", "radon", "2026-08-16T18:34:04Z", "2026-08-16T18:34:06Z", "reply", "looseelectron", "A reply known before the earlier cutoff."),
  socialEvent("social-radon-2", "radon", "2026-08-16T18:43:16Z", "2026-08-16T18:43:18Z", "post", "radonfriend", "LATER_POST: revealed only by the separately served retrospective DTO."),
  socialEvent("social-radon-gap", "radon", "2026-08-16T18:40:30Z", "2026-08-16T18:40:31Z", "gap", null, "Pump social collector unavailable for 23 seconds."),
], (event) => event.id);

function payloadFor(mode: ReplayMode): GlassPayloadV1 {
  const candidates = seeds.map((seed) => candidateFor(seed, mode)).filter((candidate): candidate is Candidate => candidate !== null);
  const candidateIds = new Set(candidates.map((candidate) => candidate.id));
  return {
    sources: sourcesFor(mode),
    candidates: sortBy(candidates, (candidate) => candidate.id),
    episodes: episodesFor(mode).filter((episode) => candidateIds.has(episode.candidateId)),
    socialEvents: allSocialEvents.filter((event) => candidateIds.has(event.candidateId) && Date.parse(event.knownAt) <= Date.parse(horizon(mode))),
  };
}

function asOf(mode: ReplayMode): GlassViewV1["asOf"] {
  const commit = mode === "knowledge_cutoff" ? "35" : mode === "witnessed" ? "42" : "68";
  const receivedThrough = micro(new Date(Date.parse(horizon(mode)) - 1_000).toISOString());
  return {
    catalogCommit: commit,
    sources: ["chain-tape", "pump-board", "pump-social", "wallet-watch"].map((sourceId, index) => {
      const deliveredThrough = String(Number(commit) - index);
      const cursors = sourceId === "pump-board"
        ? [
            { family: "attention", subject: null, cursorKind: "epoch", value: `fixture:census:${commit}`, advancedThrough: deliveredThrough },
            { family: "attention", subject: "hot:radon", cursorKind: "sequence", value: `fixture:hot:radon:${commit}`, advancedThrough: deliveredThrough },
          ]
        : [{ family: "default", subject: sourceId, cursorKind: "sequence", value: `fixture:${sourceId}:${commit}`, advancedThrough: deliveredThrough }];
      return { sourceId, deliveredThrough, cursors, receivedThrough };
    }),
    chain: { cluster: "solana-mainnet-fixture", slot: mode === "retrospective" ? "361000068" : mode === "witnessed" ? "361000042" : "361000035", finality: "confirmed" },
    projections: [
      { name: "accounting", version: "1", stateDigest: `sha256:${"1".repeat(64)}` },
      { name: "attention", version: "1", stateDigest: `sha256:${mode === "retrospective" ? "3".repeat(64) : mode === "witnessed" ? "2".repeat(64) : "0".repeat(64)}` },
      { name: "social", version: "1", stateDigest: `sha256:${mode === "retrospective" ? "6".repeat(64) : mode === "witnessed" ? "5".repeat(64) : "4".repeat(64)}` },
    ],
    renderedAt: horizon(mode),
  };
}

function viewFor(mode: ReplayMode): GlassViewV1 {
  return {
    contract: "joshi.glass.view",
    schemaVersion: 1,
    mode,
    sceneId: mode === "witnessed" ? WITNESSED_SCENE_ID : `scene-20260816-${mode === "knowledge_cutoff" ? "183500-cutoff" : "190800-retrospective"}`,
    basisSceneId: mode === "witnessed" ? null : WITNESSED_SCENE_ID,
    asOf: asOf(mode),
    payload: payloadFor(mode),
  };
}

function snapshotFor(mode: ReplayMode): GlassSnapshotV1 {
  const view = viewFor(mode);
  return parseGlassSnapshotV1({
    contract: "joshi.glass.snapshot",
    schemaVersion: 1,
    snapshotDigest: digestGlassView(view),
    transport: "offline_fixture",
    recordingAuthority: "read_record_replay_only",
    view,
  });
}

export const mockSnapshots: Readonly<Record<ReplayMode, GlassSnapshotV1>> = deepFreeze({
  knowledge_cutoff: snapshotFor("knowledge_cutoff"),
  retrospective: snapshotFor("retrospective"),
  witnessed: snapshotFor("witnessed"),
});

export const mockSnapshot = mockSnapshots.witnessed;
