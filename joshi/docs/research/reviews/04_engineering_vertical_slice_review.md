# Review 04: the engineering corridor to first natural use

Status: cross-review and pre-engineering recommendation, 2026-08-16. This document does not
authorize implementation, automated source access, a purchase, a wallet credential, transaction
construction, signing, submission, or a trade.

## Executive decision

The Wave 2 lanes contain several good experiments that become a bad schedule when added together.
The three-language million-event bakeoff, the three-language protocol conformance program, four UI
hosts, a 72-hour stream pilot, a complete storage crash matrix, an OCaml numerical oracle, and a
natural Pump workflow audit cannot all precede the first useful screen. That sequence would spend
the August 16–30 corridor validating a platform while Ember continues making the actual decisions
somewhere else.

Use one narrow decision spike to falsify, rather than rediscover, the leading architecture:

> **Provisional production stack:** one stable-Rust local core, one React/TypeScript browser,
> SQLite with a fixed safe runtime plus content-addressed blobs, official/pinned TypeScript SDKs as
> offline protocol oracles, and Python only for fixture extraction and later research.

The core is a modular monolith with one authoritative writer. It owns raw append, exact identifiers
and quantities, a small pure reducer, command/query endpoints, scene capture, and replay. The
browser owns rendering and semantic gestures. The first live adapters are only a read-only wallet
path and one exact-mint market/chart/quote path whose exact access operation has been cleared. No
normal Slice 1 process needs Node, Python, OCaml, .NET, a desktop wrapper, Parquet, DuckDB, or a
source broker.

This resolves the direct Wave 2 contradiction between the Rust recommendation in lane 13 and the
Python-first hypothesis in lane 14. The topology in lane 14 is sound; its language conclusion is
not the best durable choice after lanes 13, 17, and 20 are considered together. Rust has the only
credible one-runtime path through official Solana/Pump decoding, exact protocol arithmetic,
SQLite, later columnar export, and a future independently reviewed guard. A Python core would still
need TypeScript or Rust at the protocol boundary and Rust for the proposed numerical authority,
creating three production runtimes before the first natural session. Python remains the right
research language and a useful disposable probe language.

The decision is provisional because a small walking path can still falsify it. Do not implement
the whole candidate matrix. Give Rust one continuation-ready working day against the real JOSHI
fixture and use a TypeScript local-core fallback only if the measured edit/build/boundary burden
prevents the path from closing. Do not add C#, F#, or OCaml to the August runtime comparison.
OCaml's strongest near-term role is an independent numerical oracle after the first product loop,
not a third daemon before it.

The first runnable product is **Slice 1R, the exact-mint truth corridor**. It is deliberately
post-selection: Ember can open or paste one mint, see a genuine chart, current exact exposure and a
size-specific liquidation observation or honest unquotability, make a few coarse semantic marks,
and replay the resulting scene. It can be used beside Pump or Padre before discovery parity is
settled. It must reach an ordinary Ember session by August 22–23. The selected discovery or
companion surface attaches only after the independent source/access Spike 0 chooses a lawful,
faithful mode.

The one-million-event test still has value, but not as three pre-product implementations. Run it
once through the chosen Slice 1 path, using representative payload sizes and failure classes, after
the runnable corridor exists and before authorizing continuous broader collection. It becomes a
capacity and recovery fixture, not a language pageant and not a condition for the first natural
session.

## Decisions made, and decisions deliberately left open

| Question | Decision for the August corridor | Reconsideration trigger |
| --- | --- | --- |
| Primary runtime | stable Rust, continuation-ready if the one-day walking gate passes | walking path cannot close cleanly; ordinary changes require cross-cutting borrow/trait work; protocol or SQLite dependency is unusable on the host |
| Runtime fallback | TypeScript local core and browser, scoped to the read-only exact-mint corridor | Rust gate fails and TS closes the same fixture by the fallback deadline; complex financial calculations remain assertions or unavailable until a separate core is validated |
| Python | fixture extraction and later locked research environment only | a bounded source probe is materially faster in Python and its output is promoted as raw fixtures/contracts rather than imported runtime code |
| OCaml, F#, C# | no production role before first natural use | a stable pure kernel has a named assurance gap or Ember genuinely wants a durable alternative after the corridor |
| Browser | React/TypeScript/Vite on loopback in Ember's actual browser | measured chart/input/a11y failure survives a narrow renderer repair |
| Desktop host | none | a measured global-shortcut, capture, focus, or packaging need; Tauri first, Electron only against a specific WKWebView failure |
| Operational store | one writer, pinned fixed SQLite in WAL/FULL mode, strict schema, content-addressed files for large/private blobs | fixed SQLite cannot be supplied; measured one-writer, checkpoint, backup, or query gates fail |
| Analytical store | none in Slice 1 runtime | a named study needs a frozen export; then manifested Parquet plus ephemeral DuckDB |
| Protocol plane | Rust raw decode/normalization for supported Pump/PumpSwap cases; pinned TS SDK as differential oracle | an exact mismatch blocks the affected case; Meteora remains outside Slice 1 unless product need pulls it in |
| Pump discovery | not assumed | Spike 0 selects replacement, companion, on-chain observatory, or stop/rethink |
| Research/ML | deferred consumer of immutable exports | enough prospective scenes exist for one named reproducible task |
| Transaction authority | structurally absent | separate future review after natural use, quote resolution, reconciliation, and loss gates |

Two decisions remain intentionally conditional. First, the exact source for the live event-backed
chart and quote depends on the cleared access/protocol probe. Second, SQLite is selected for Slice
1, not declared the permanent high-volume archive. Those uncertainties do not justify abstracting
over every source or store now.

## Two clocks run in parallel

The source/access premise and the engineering stack premise are independent. They should not be
serialized, and neither should be allowed to smuggle assumptions into the other.

### Clock A — source and access Spike 0

Run the accepted manual workflow audit from `PRE_ENGINEERING_PROGRAM.md` and engineering lane 21:

1. record three ordinary Pump/Padre sessions without automated capture;
2. select one actual discovery-to-coin workflow from observed use;
3. classify the exact fields and exact acquisition operations;
4. clear, exclude, or leave unresolved each operation before any automation uses it;
5. compare only the selected loop; and
6. choose replacement-capable, companion-capable, on-chain observatory, or stop/rethink.

This clock gates discovery claims and any companion implementation. It does **not** gate an offline
engineering fixture, a current-balance view built from a separately cleared public-chain read, or
the post-selection exact-mint workbench. No live adapter begins merely because its SDK is installed
or its route worked in `joshibot`; the exact HTTP, RPC, WebSocket, screenshot, or DOM operation must
have a recorded access disposition first.

### Clock B — engineering Decision Spike E0

Run one offline, keyless, continuation-ready path while Clock A is collecting ordinary sessions.
It does not call Pump, Solana, a wallet, or any paid service. It consumes only committed synthetic,
public, or sanitized fixtures.

The spike answers a smaller question than the engineering lanes proposed:

> Can the selected Rust/TypeScript/SQLite shape preserve JOSHI's hard distinctions through one
> displayed scene, with a pleasant enough loop to continue directly into Slice 1?

The source/access result later chooses an adapter. It does not reopen the core language, writer,
scene, or browser decisions unless it exposes an actual incompatible requirement.

### Why this reconciliation matters at a zero-dollar budget

The engineering decision needs no paid data. Compiler toolchains already exist. The fixture is
offline. Clock A begins with ordinary manual use and field inventory. The first live read paths are
bounded public or already-authorized paths and must remain inside their published or existing
allowances. Do not treat a funded PumpPortal wallet, free-plan overage, hidden frontend route, or
future trading gain as zero cost.

If a source decision requires a new plan, metered token/account feed, browser key, or permission,
mark the corresponding field unavailable and continue with exact-mint/manual nomination. A
purchase is a later runway decision, not an implicit way to keep the August schedule green.

## Decision Spike E0: one walking path, not three applications

### Fixed fixture packet

The spike uses one repository-owned packet with three layers.

**Semantic trace — small enough to read by hand.** It contains:

- two byte-identical acquisition attempts;
- two equal-valued but distinct chain effects;
- one unknown source variant;
- one source gap and recovery;
- one late correction with old event time and new availability time;
- one partial realization with a retained runner;
- exact flat followed by a watching-flat interval and re-entry;
- one unknown-basis incoming quantity;
- one operator mark with an idempotent retry; and
- one stored view/scene plus later retrospective evidence.

**Protocol trace — small enough to differential-review.** It contains:

- the public Pump native-SOL curve trade fixture already in the compost;
- one Pump curve state and one PumpSwap migrated state with exact integer quote vectors;
- boundary values `0`, `1`, a separate-fee rounding edge, and deliberate overflow/refusal;
- the exact pinned IDL/package/program identities used by the oracle; and
- an opaque future instruction/account variant that must remain raw and unsupported.

If the PumpSwap fixture cannot be sourced and reviewed in the day, it does not block the stack
decision. The affected live lifecycle stays explicitly unsupported in Slice 1 until the protocol
fixture lands.

**Load trace — representative enough to expose the writer shape.** Generate 50,000 envelopes with
the measured `joshibot` payload-size classes and a declared mix of duplicates, large payloads,
unknown variants, and source keys. It is not a market simulator and not a protocol-coverage claim.
Its purpose is to expose gross serialization, queue, writer, checkpoint, and browser-stream
mistakes before scaffolding continues.

### Required walking path

The leading implementation must demonstrate this one path:

```text
fixture frame
  -> bounded ingress
  -> exact raw bytes/blob + acquisition metadata
  -> atomic observation/cursor append
  -> versioned assertion or explicit quarantine
  -> pure wallet/episode projection
  -> versioned query snapshot
  -> React exact-mint/episode view
  -> idempotent operator mark + scene commit
  -> witnessed replay from stored rendered DTO
  -> separate retrospective replay digest
```

The spike is allowed one core process and one browser dev server. The production continuation
should serve the built browser from the loopback core, but that packaging detail does not need to
consume the decision day.

### Exact pass gate

Rust is selected for Slice 1 only if, by the end of the E0 working day:

1. a project-pinned stable toolchain builds and tests on Ember's Apple-arm64 host from one
   documented root command;
2. the runtime reports SQLite **3.51.3 or a reviewed fixed backport or later**, verifies WAL,
   `synchronous=FULL`, foreign keys, and strict schema behavior, and never uses the affected local
   3.51.0 CLI library by accident;
3. observation/blob durability and cursor advancement share the required transaction boundary;
4. killing at `raw durable / before cursor commit` repeats rather than skips, and killing around
   the scene command produces either one durable scene or none, never a false receipt;
5. the semantic digest is equal across two fresh replays and preserves the duplicate, distinct
   equal event, gap, correction, partial runner, flat interval, and re-entry distinctions;
6. release-profile arithmetic rejects overflow and the supported Pump quote vector agrees exactly
   with the pinned TypeScript oracle, including component rounding;
7. a browser view receives a versioned snapshot, renders exact quantities without JavaScript
   numeric coercion, records one stable-target mark, and reopens the witnessed scene;
8. the 50,000-envelope run has zero unexplained loss, bounded memory, a draining queue, and no
   gesture command delayed beyond 250 ms; this is a smoke threshold, not the final latency target;
9. every raw, assertion, view, and scene object exposes an intelligible lineage and source/version;
   and
10. the dependency graph and executable surfaces contain no builder, wallet adapter, key loader,
    signing API, `sendTransaction`, Jito client, or broadcast method.

The test does not require Parquet, a full protocol decoder, a live chart, a clean-user package,
four browser hosts, one million events, or 100 randomized schedules.

### Fallback and stop rules

| Failure | Exact response |
| --- | --- |
| Rust path misses the day because of core dependency/build/bridge friction, while the semantic contract is stable | give the TypeScript local-core fallback half a day to close the same small trace; do not extend Rust and TS into two full stacks |
| TypeScript closes the trace | use TS for the read-only Slice 1 corridor; keep economic values as exact `bigint`/decimal-string contracts and mark unsupported calculator cases unavailable; revisit a Rust core after natural use |
| Neither path closes the same trace by the fallback deadline | stop runtime comparison; deliver an offline fixture/contract report and reduce the product target to a static exposure/scene prototype before authorizing a daemon |
| Fixed SQLite runtime cannot be pinned and asserted | stop SQLite/WAL startup; do not downgrade silently to unsafe WAL settings or a mutable JSON store |
| Rust and TS disagree by one economic atom with no profile explanation | block that quote/formula/lifecycle; the rest of the read-only scene path may continue with `unquotable` |
| Browser work requires accounting types or SDK objects directly | stop and repair the view contract; do not make the UI the second reducer |
| A candidate needs Python + Node + Rust in the normal Slice 1 graph | reject that candidate for the corridor unless one process removes a measured blocker and receives its own ADR |
| Any convenience path introduces transaction construction or submission | stop the spike and remove the dependency/surface before further live-source work |

This is a falsification gate, not a weighted contest. The extensive language matrices already give
Rust a prior. The walking path asks whether reality on this machine overturns it.

## What happens to the million-event bakeoff

The lane 13 common bakeoff mixes five questions: semantic correctness, storage durability,
throughput, UI transport, and language ergonomics. Only a small part must precede Slice 1.

| Bakeoff element | Placement | Reason |
| --- | --- | --- |
| project-owned envelope, exact integer strings, explicit units/clocks, unknown variants | **E0 pre-Slice** | changing these after the first scene would corrupt the corpus |
| hand-readable duplicate/gap/correction/runner/flat/re-entry trace | **E0 pre-Slice** | proves the semantic object and reducer boundary |
| two crash points around evidence/cursor and scene receipt | **E0 pre-Slice** | prevents the first natural acts from entering an unsafe store |
| one pinned Pump quote/decode differential and release overflow refusal | **E0 pre-Slice** | catches the language/runtime's most consequential arithmetic and protocol mismatch |
| one snapshot and one live delta to the real React view | **E0 pre-Slice** | proves the proposed runtime split is real rather than architectural prose |
| 50,000-envelope queue/writer smoke with representative byte classes | **E0 pre-Slice** | detects an obviously wrong writer/runtime choice cheaply |
| 1,000,000 framed envelopes, capacity-4096 queue, slow-sink injection, queue/stall telemetry | **inside Slice 1 after first runnable use** | validates the chosen path; it is not worth implementing three times |
| SQLite checkpoint/resume and canonical replay over the million-event pack | **inside Slice 1 acceptance** | continuous collection should wait for it; the first exact-mint session should not |
| UI burst/reconnect over representative view deltas | **inside Slice 1 acceptance** | use the actual view contract and chart rather than a throwaway client |
| randomized crash schedules | **10 representative schedules inside Slice 1; deeper campaigns later** | a hundred schedules before one session has poor information value; preserve every failure as a fixture |
| Parquet result and Arrow interoperability | **after Slice 1, before the first reproducible research snapshot** | no Slice 1 product query requires a columnar export |
| three complete Rust/C#/OCaml implementations | **do not run** | ecosystem and numeric lanes already break the tie; three apps delay the product and create accidental maintenance |
| OCaml/Zarith independent numerical oracle | **after first runnable use; before trusting complex accounting or LP formulas** | valuable independence, but not necessary for current quantity and one supported quote vector |
| C#/F# semantic comparison | **defer indefinitely unless Ember wants it as the durable app runtime** | no current boundary earns the runtime |
| one fresh AI change task per candidate | **replace with two small changes in the selected stack** | measure actual agent maintainability rather than miniature-stack generation skill |
| 25,000 frames/s and 250 ms p99 synthetic stress thresholds | **defer to an S2/full-census decision** | Slice 1's measured planning envelope is 10–50/s with 200/s bursts; the synthetic target selects for an unapproved firehose |
| clean-user packaging, binary size, Tauri/Electron host comparison | **after repeated natural use** | browser loopback is adequate for the August product premise |
| 24-hour/72-hour provider recovery and 100-transaction protocol breadth | **source/protocol pilots after operating mode, not runtime admission** | live access and provider choice are separate from offline language correctness |
| Meteora parity, DLMM positions, rebalance simulation | **defer beyond Slice 1R** | no first exact-mint spot/exposure task requires an LP control plane |

The million-event Slice 1 pack must not be a million identical tiny JSON objects. Its manifest
records the source of its payload-size histogram, ratios of inline/external blobs, duplicate and
conflict rates, large-frame classes, fixture seeds, and logical digest. It may deterministically
expand a small reviewed corpus for load, but it must state that semantic diversity remains small.
Protocol breadth is tested by distinct goldens, not by repetition count.

Slice 1 capacity passes when one chosen runtime:

- ingests the pack with zero unexplained loss and exact counter reconciliation;
- survives the ten declared crash schedules without a cursor skip or false scene receipt;
- reproduces the same canonical projection digest from empty state;
- keeps operator-command p95 below 50 ms and ordinary cockpit query p95 below 250 ms on the local
  host during a 5× S0 replay;
- drains a 30-second 10× burst within five minutes;
- exposes every sampled, rejected, quarantined, duplicated, and gapped record class; and
- stays inside the local CPU, memory, and disk reserve accepted for S0.

If it fails, pause always-on collection and continue the manual/session-bound workbench while the
bounded bottleneck is repaired. Do not migrate stores or buy a stream merely because the load test
failed once.

## First runnable Slice 1R — exact-mint truth corridor

### Operator task

During an ordinary session, Ember can paste or open an exact mint, understand the current position
and exitability, mark what they are doing without completing a form, take any economic action in
the existing trusted tool, and later reopen what Joshi actually displayed.

This is useful even if discovery remains in Pump. It studies exposure and management, not selection
uplift. The product must say so.

### Minimum product surface

One responsive screen contains only:

1. **Exact-mint header** — mint, asset identity, observed metadata with source and age, lifecycle
   support state, and external Pump/Padre link.
2. **Genuine chart** — decoded event-backed points or legitimate OHLC aggregation, lifecycle/gap
   markers, coverage, and an explicit unsupported state. No DexScreener percentage-window
   reconstruction.
3. **Exposure card** — exact token atoms/display amount, finalized/current status, current full-bag
   executable liquidation artifact or `unquotable`, basis quality, realized cash if supported, and
   current residual risk. RADON, EarthCoin, and CRASHIUS are fixtures/current rows, not strategy
   success labels.
4. **Episode rail** — current episode may be exposed, watching, watching-flat, unresolved, or
   resolved; inventory epochs remain separate.
5. **Coarse acts** — `mark`, `watch`, `take-some intent`, `keep remainder`, `exit intent`, `watch
   flat`, `re-entry intent`, `resolve`, correction, optional free text, and `not articulable`.
   `arm shadow` may be recorded as an observation-only act but cannot start a strategy or economic
   simulator.
6. **Source/readiness strip** — wallet slot/finality, market/chart watermark and gap, quote state
   and age, scene-command health, and projection lag. There is no global green light.
7. **Replay entry** — witnessed scene first; retrospective state is a separately labeled view.

The first screen does not need a discovery feed, social thread, viewport virtualization, chart
drawing suite, model output, household allocator, LP schedule, or polished interview flow.

### Data and semantic minimum

- one explicitly declared read-only wallet or the smallest portfolio domain needed to avoid
  misclassifying an observed internal transfer;
- current finalized balances before complete history;
- exact external wallet-effect observations and optional later episode attribution;
- raw observation, versioned assertion, operator record, stored view DTO, scene manifest, and
  projection checkpoint as distinct object families;
- exact amount/asset types and event/receive/available/render/gesture clocks where actually known;
- content-addressed storage for the one optional private scene image and any large raw response;
- witnessed replay from the stored rendered DTO, not current recomputation;
- retrospective replay from named later evidence; and
- explicit basis, source, route, lifecycle, and coverage gaps.

Historical accounting must not delay current usefulness. A row with exact quantity, current
liquidation, and `basis unknown: missing predecessor evidence` is a passing early row. A synthetic
zero/current-quote basis is a stopping defect.

### Normal process graph

```text
                         Ember
                           |
                   local React browser
                    query + commands
                           |
                 loopback versioned API
                           |
        +------------------v------------------+
        | one Rust core process              |
        |                                    |
        | source adapters -> bounded ingress |
        |             -> one writer          |
        |             -> assertions/reducer  |
        | commands     -> scenes/operator    |
        | query        <- versioned views    |
        | replay       <- stored DTO/evidence|
        +---------+------------------+--------+
                  |                  |
           SQLite catalog       hashed blobs
            WAL + FULL          public/private

Cleared live read adapters only:
  Solana/RPC wallet + exact-mint market/account state
  officially described per-mint enrichment, if separately cleared

Offline test-only:
  pinned TypeScript Pump/PumpSwap oracle
  Python fixture extraction/report scripts

Explicitly absent:
  provider secrets in browser · wallet key · builder · signer · submitter
  unsupported Pump scraper · model worker · broker · analytical warehouse
```

A source adapter may become a separate local process only when a real SDK/runtime or crash boundary
earns it. The first choice is in-process Rust. The pinned TypeScript oracle is not a daemon and is
not asked for every live quote. If a supported quote function must remain TypeScript after an exact
parity failure, that exception receives a narrow manifest-bound read-only process and counts as a
production runtime; it is not added quietly during Slice 1R.

### Slice 1R pass gate

The slice passes into ordinary use when all of these are true:

1. one root command starts the keyless local core and browser and prints the capability ceiling;
2. the declared wallet's current quantities reconcile to a finalized chain snapshot or each exact
   residual is shown with a named cause;
3. the three retained-runner rows never call exposure free, never infer missing basis, and show a
   full-size liquidation artifact or `unquotable` with reason;
4. one naturally encountered exact mint displays a genuine chart with coverage and one supported
   exact-size quote whose state, slot, route, fees, size, and age are inspectable;
5. one consequential act receives exactly one durable receipt under retry, and the UI does not
   claim success before it;
6. one external wallet change can become a financial fact without manufactured intent; if no
   natural change occurs during the corridor, the fixed fixture proves the path and the live row
   remains unexercised rather than simulated as natural behavior;
7. exact flat closes an inventory epoch while the episode may remain watching-flat, and fixture
   re-entry starts a fresh basis epoch;
8. witnessed replay restores the exact stored view/scene and excludes later correction; the
   retrospective view includes it and is visibly different;
9. a chart, source, parser, or quote failure degrades only the relevant fields while the scene
   command and unaffected current quantity remain available;
10. no running process, dependency surface, or configuration exposes economic authority; and
11. Ember uses the screen in one ordinary session by August 22–23 and says it helped with exposure,
    memory, or management rather than requiring clerical work.

### Slice 1R fallback and stop outcomes

- **Quote path blocked:** ship exact quantity, chart, source state, and `unquotable`; do not delay
  the scene notebook or substitute a mark.
- **Historical basis blocked:** ship current exposure and explicit history gap; do not delay the
  current rail.
- **One runner cannot be identified safely:** show the mint/account effect without episode or
  strategy attribution.
- **Live chart lifecycle unsupported:** show the unsupported lifecycle and use another naturally
  encountered supported mint for the first prospective scene; do not fabricate continuity.
- **No cleared live source by August 22:** run the complete offline demo and a manual exact-mint
  scene shell, but do not call it natural market use. The blocker returns to the source/access
  gate.
- **Ember avoids the rail after two ordinary sessions because it is clerical or materially worse
  than current tools:** stop feed/platform expansion and preserve the artifact as an exposure
  prototype.
- **Current quantities cannot reconcile under any honest small portfolio domain:** stop financial
  claims and keep only the scene/workbench path until the custody boundary is repaired.
- **A source or UI defect loses/mistargets a consequential gesture:** stop natural-session use
  until the defect is reproduced and fixed.

## Source/access mode attaches after, not inside, the core decision

The mode decision changes the left edge of the process graph:

| Spike 0 result | August attachment | Claim allowed |
| --- | --- | --- |
| replacement-capable | one selected Pump surface with exact served order, rendered set, viewport, and target freezing | parity only for the audited surface and measured reaction window |
| companion-capable | lowest-privilege reviewed capture beside the real Pump session, starting with user-triggered app-window scenes before any DOM extension | Pump supplied selection/context; Joshi supplied measurement, exposure, and replay |
| on-chain observatory | one reproducibly ordered Joshi-defined board or manual/wallet nominations | independent universe; no Pump attention-funnel claim |
| stop/rethink | retain exact-mint exposure/replay only if Ember finds it independently useful | no discovery replacement claim |

Do not delay Slice 1R for the 100-entry replacement audit. Do not attach any discovery source until
that audit and the access review pass. A paste-mint workbench is honestly post-selection and can
produce useful management scenes while the longer product premise is tested.

The fastest fallback when Pump feed/social parity is inaccessible is not an on-chain firehose. It
is the same exact-mint corridor with one of:

1. a reviewed, deliberate Pump scene capture plus explicit mint nomination;
2. manual mint nomination with Pump remaining the discovery renderer; or
3. one small Joshi-defined on-chain recent/activity list whose ordering and omissions are owned and
   named.

If none becomes a natural place to look, stop the replacement ambition. The accounting, current
exposure, and replay artifact can remain useful without pretending to measure the whole market.

## Concrete compost donor extraction

No donor becomes a runtime import. The extraction unit is one fixture, pure behavior, or small UI
pattern with provenance and a new conformance test. The 74+ GiB estate remains in place and outside
the new canonical store.

| Donor in `~/dev/joshibot` | Extract now | Acceptance in `joshi` | Explicitly leave behind |
| --- | --- | --- | --- |
| `tests/fixtures/pump_native_sol_curve_trade.json` | one public raw Pump protocol fixture and locator/provenance | Rust and pinned TS oracle agree on exact supported fields; unknowns remain raw | old normalized schema as authority |
| `shitcoims_tape/schema.py`, `writer.py`, `health.py`; `tests/test_tape_schema.py`, `test_tape_writer.py`, `test_tape_health.py` | duplicate/equal-distinct/gap/cursor/clock/secret-canary cases as language-neutral fixtures | new writer and reducer pass the cases from raw inputs | `TapeEvent`, observation-time identity, rotate-only persistence, old store |
| `shitcoims_intelligence/pnl.py`; `tests/test_intelligence_pnl.py` | small sanitized wallet-effect and unknown-basis expectations for the three runner rows where provenance is adequate | fresh chain quantities remain canonical; expected basis gaps match | FIFO as universal meaning, wallet-local PnL headline, old database |
| `shitcoims_sentinel/lots.py`; `tests/test_lots.py` | flat-reset, partial-lot, and re-entry counterexamples | new episode/inventory model preserves flat watching and new basis epoch | sentinel engine, automatic policy, mint-runtime state as episode |
| `shitcoims_paperdesk/hunch.py`; `tests/test_hunch.py` | idempotent append-before-readback gesture/correction fixtures | one command ID yields one operator record and scene receipt | hunch kinds, confidence defaults, paper position lifecycle |
| `app/components/pricechart.tsx` | Lightweight Charts setup, crosshair/log-scale behaviors, marker rendering ideas | prove genuine event input, high-DPI resize, gap display, and stored chart domain in new component | `shitcoims_sentinel/candles.py` reconstructed percentage path and old domain props |
| `app/components/instrument.tsx`, `app/lib/measure.ts`, selected local style primitives | compact observed/derived/stale/absent visual grammar | view contract drives every state and exact amount stays a string to the renderer | old strategy verdicts, page hierarchy, SDK/domain objects |
| `app/views/explorer.tsx` | one target-freeze/list-epoch adversarial test, **only when a discovery surface attaches** | rank changes cannot retarget a pointer/keyboard act | the 1,986-line component, hunch coupling, old policy labels |
| `shitcoims_pumpsocial/endpoints.py`, `client.py` | field-shape and drift fixtures for the access dossier only | every reused route/method has a fresh cleared access record; fixtures remain offline | browser key, unsupported live calls, background crawl, current creator as history |
| `shitcoims_scalper/boards.py`; tape samples named by its tests/studies | measured payload-size classes, interval-censoring and 200/null/schema-drift cases | load-pack manifest cites sizes and source; no policy conclusion | 30-second polling as parity/crackle feed and old board policy |
| `shitcoims_lpexec/guard.py`; `tests/test_lpexec.py` | negative fixture asserting hostile/unknown byte surfaces and forbidden send dependencies | Slice 1 dependency/effect scan refuses builder/signer/broadcast capabilities | `builder.cjs`, signer, RPC send, planner, secrets, LP commands |

Do not copy current runner database rows merely because the UI needs three cards. Begin from fresh
read-only chain balances and named transaction fixtures. Old history may supply a candidate locator
or expected gap; it cannot silently become the new ledger.

The donor manifest records old path, old commit/dirty-state hash if available, extracted bytes or
behavior, sanitization, provenance, new fixture hash, and the claim it is allowed to support. A
donor without that row remains compost.

## Critical path, dates, and parallel work limits

### Corridor schedule

| Target | Critical output | Gate outcome |
| --- | --- | --- |
| **Aug 16** | begin manual Clock A sessions; freeze E0 fixture/contract spine and donor manifest | no automated Pump/source operation begins |
| **Aug 16–17** | run E0 Rust walking path and 50k writer smoke | select Rust or invoke the half-day TS fallback |
| **Aug 18** | record runtime/storage/UI/protocol ADR decision; open only the chosen Slice 1 graph | no second implementation retained “for reference” |
| **Aug 18–21** | current wallet/exposure path, exact-mint chart/quote adapter, scene command, witnessed replay, minimal React screen | runnable Slice 1R candidate |
| **Aug 22–23** | first ordinary Ember session; repair only material truth/latency/clerical defects | pass into continued natural use or stop/reduce |
| **Aug 23–25** | second ordinary session; source/access mode decision reaches its field matrix | decide whether discovery attachment is lawful and useful |
| **Aug 25–28** | attach exactly one replacement/companion/observatory mode **only if its gate passed**; otherwise keep exact-mint corridor | no parity-by-proxy |
| **Aug 27–29** | million-event chosen-stack capacity/recovery fixture, backup/restore of one scene, final ordinary session | approve bounded continuous S0 use or remain session-bound |
| **Aug 30** | runway review: voluntary use, missing cues, reconciliation, replay, source cost/burden | continue, hold useful artifact, pivot mode, or stop expansion |

Natural use is on the critical path before the million-event acceptance and before discovery
polish. The dates are decision targets, not permission to weaken truth or safety.

### Parallel work limit

Use one integrator and at most two code-writing lanes:

- **Integrator/semantic owner:** sole editor for cross-boundary contracts, schema versions,
  migrations, effect ceiling, and merge order.
- **Core/source/accounting lane:** runtime, pinned SQLite, raw append, read-only protocol/wallet
  adapters, exact quantities, and source health.
- **Product/replay lane:** React view, coarse acts, stored view DTO, scene command, and witnessed
  replay after the contract spine lands.
- **Read-only review lane:** may prepare fixture manifests, adversarial cases, access matrix, and
  inspect diffs, but does not independently change the shared schema.
- **Ember:** supplies short ordinary sessions and fast material-cue/usefulness judgments; Ember is
  not asked to manufacture trades or label every act.

Maximum concurrent production-code editors: **two**, with the integrator counting if editing shared
code. Maximum unfinished artifacts: one operator-facing slice and one bounded source/reliability
spike. A language challenger replaces the primary candidate after a failed gate; it does not run
in parallel as another architecture.

Parallel work must converge daily into one runnable state. Source/access research can continue
alongside code because it owns no production schema. Contract, migration, or generated-binding
changes are serialized before downstream edits.

## Decision gates and useful stopping artifacts

| Gate | Exact pass | Fallback | Stop condition | Useful artifact if stopped |
| --- | --- | --- | --- | --- |
| **A0 access inventory** | every automated operation used by the next step is cleared or excluded; no unresolved dependency | offline fixtures and manual exact-mint nomination | bypass/key/session replay or unresolved access is required | field/access matrix and explicit operating-mode limit |
| **E0 stack** | all ten E0 pass conditions by the decision deadline | half-day TypeScript fallback | neither candidate closes the walking trace or safe SQLite cannot be established | canonical fixture packet and stack-failure report |
| **P0 protocol** | exact supported fixture parity; unknown variants fail into raw/unquotable | remove the affected lifecycle/formula from the UI | unexplained atom mismatch is hidden or coerced | protocol differential and honest unsupported matrix |
| **S1R runnable** | all eleven Slice 1R conditions, first session by Aug 22–23 | quantity/scene notebook with quote/history gaps | mis-targeted/lost act, fabricated basis/fill, or unreconciled current quantity presented as truth | local exposure/scene prototype |
| **N1 natural use** | Ember voluntarily uses it in two ordinary sessions and capture does not obstruct a time-sensitive act | hold as occasional exposure tool and revise one material defect | repeated return to other tools for exact-mint context or clerical avoidance after bounded repair | trustworthy exposure/replay utility |
| **D1 discovery attach** | accepted 100/95 replacement gate, 19/20 reviewed companion captures, or explicitly named on-chain universe | manual nomination/exact-mint corridor | inaccessible material Pump texture makes every reduced loop unnatural | management companion rather than replacement |
| **C1 capacity** | chosen-stack million-event and ten-crash criteria pass inside local resource budget | session-bound collection while bottleneck is repaired | silent loss, cursor skip, false scene receipt, or pressure-induced biased omission | runnable local tool with bounded/no continuous capture |
| **R4 runway** | voluntary use, credible evidence, $0 incremental operation, one clear next marginal slice | hold or pivot mode | upkeep exceeds leverage, unknown material omissions persist, or financial pressure drives authority/evidence shortcuts | small keyless exposure/episode corpus |

No gate contains a profit target. PnL that happens during manual use is an observed episode outcome,
not an engineering acceptance signal.

## Deliverables

The corridor should finish with a small portfolio of artifacts, not a generic framework:

1. **E0 fixture pack and manifest** — hand-readable semantic trace, three or fewer protocol goldens,
   representative load generator/manifest, expected digests, and donor provenance.
2. **Architecture decision record** — selected runtime, TypeScript boundary, fixed SQLite runtime
   and pragmas, canonical integer encoding, one-writer topology, and the falsifier that would reopen
   each decision.
3. **Offline walking demo** — one command, no network or credentials, full raw-to-replay lineage.
4. **Slice 1R local artifact** — exact-mint workbench, current exposure/runner rail, genuine chart,
   supported quote/unquotability, coarse acts, source health, and witnessed replay.
5. **Source/access dossier** — ordinary workflow traces, selected loop, field/latency/access matrix,
   mode decision, and every excluded or unresolved cue.
6. **Protocol/source support matrix** — supported lifecycle/asset cases, exact oracle comparisons,
   unknown variants, quote assumptions, provider/read method, and gap/recovery behavior.
7. **Capacity/recovery report** — chosen-stack million-event results, crash traces, queue/latency and
   local resource measurements, backup/restore of one scene, and S0 collection limit.
8. **August natural-use note** — sessions attempted, voluntary use, material exits from the tool,
   capture burden, replay failures, and the one recommended next slice or stop decision.

Each deliverable remains useful if the next one fails. The access dossier can stop a bad
replacement. The fixture pack can survive a stack reversal. The exposure rail can remain useful
without discovery parity. The capacity report can justify staying session-bound without deleting
the cockpit.

## Scope traps exposed by the engineering cross-review

1. **Using the full bakeoff to postpone a decision.** The architecture evidence already favors
   Rust. The only useful pre-Slice comparison is a walking falsifier on this host.
2. **Letting protocol conformance become protocol breadth.** Slice 1 needs one supported spot path
   and explicit refusal elsewhere, not every PumpSwap fee mode and Meteora position.
3. **Treating Parquet support as proof of a runtime.** Columnar export matters to research later;
   it is not on the first gesture's path.
4. **Testing four UI hosts before one screen is useful.** Chrome/Safari/Tauri/Electron comparison
   answers packaging questions that natural browser use may make irrelevant.
5. **Combining Spike 0 with the runtime bakeoff.** Source access chooses the adapter and product
   claim. It does not require every candidate runtime to call live Pump.
6. **Calling a Python probe the Python core.** Promote bytes, manifests, and fixture expectations;
   do not let disposable convenience select permanent fact ownership.
7. **Making the TypeScript SDK a live economic oracle.** It is a pinned comparator. Supported Rust
   output must be bound to exact account state; mismatches become unsupported, not majority votes.
8. **Letting one million events imply market realism.** Repetition tests mechanics. Distinct
   protocol goldens and natural sessions test meaning.
9. **Bulk-extracting donor code.** The donor table is a maximum menu, not a migration checklist.
   Extract only the row required by the active gate.
10. **Waiting for complete historical PnL.** Current quantity and liquidation with an explicit
    basis gap are the runway-optimal truth.
11. **Letting discovery parity block management value.** Exact-mint post-selection use is honest
    and useful as long as its estimand is named.
12. **Letting management value masquerade as selection research.** Paste-mint episodes cannot
    estimate the Pump funnel or whole-market scaling.
13. **Turning a source runner into a second backend.** A runner emits manifest-bound raw/assertion
    artifacts and has no database, operator, or wallet authority.
14. **Adding a desktop shell to gain capture permission.** Packaging does not settle Pump access,
    cookie/session sharing, wallet extensions, or terms.
15. **Adding a graph, model, or research stack because the contracts now permit it.** A seam is not
    a user need. Prospective natural scenes come first.
16. **Using deadline pressure to downgrade SQLite durability or protocol refusal.** A green screen
    backed by skipped events or guessed quotes poisons the first irreplaceable corpus.

## Final recommendation

Approve, at the later engineering checkpoint, only the parallel manual/access Spike 0 and the
continuation-ready E0 walking falsifier. If E0 passes, continue directly into the exact-mint truth
corridor; do not pause for the full language, protocol, storage, or UI bakeoff. Put the one-million-
event pack inside Slice 1 as a chosen-stack capacity gate and keep continuous collection bounded
until it passes.

The August architecture is consequently small and explicit:

```text
stable Rust modular core + fixed SQLite/blobs + React browser
        + one cleared wallet/exact-mint read path
        + pinned TypeScript protocol oracle in offline tests
        + no economic authority
```

This plan can produce a genuine natural-use attempt by August 22–23 and still leave a week for
repair, one mode attachment, capacity validation, and a sober August 30 review. If source access,
protocol support, or natural use fails, the project stops at a useful exposure/replay artifact
instead of responding with more infrastructure.

The decisive engineering milestone is not “Rust won,” “SQLite handled a million rows,” or “the
feed looks like Pump.” It is that one exact-mint scene flows from honest evidence to a screen Ember
chooses to use, survives a crash, and reappears later without inventing what was known, owned,
intended, or executable.
