# The pillar program

Status: **active**. This replaces the wave-based program. Waves 5 and 6 are closed and their
history is kept in [`wave5/CLOSEOUT.md`](wave5/CLOSEOUT.md) and
[`wave6/CLOSEOUT.md`](wave6/CLOSEOUT.md). The wave program itself is retired in
[`PROGRAM.md`](PROGRAM.md).

Date: 2026-08-19.

## Why the framing changed

JOSHI has 38 crates and four applications, about 168,000 lines of Rust, 763 Rust tests, roughly
150 Glass tests, and 23 migrations. Until this program began it had never ingested one byte of
real market data through its evidence pipeline.

That is not a resourcing problem or a rigor problem. The rigor has been excellent. It is a
sequencing problem with one cause: **the waves built pure kernels horizontally and never closed a
single vertical path from a real source to a rendered surface.** The Wave 5 ceiling ledger carries
the same blocker sentence in nine separate rows — *inputs are caller projections, no adapter
exists* — for surface, publication, retention, scientific memory, analog memory, epistemic book,
operational status, census bakeoff and mechanics capability. Those are not nine problems. They are
one missing edge, counted nine times. Wave 6 then built a research apparatus on top of the same
missing edge and added ten more rows saying it about a different layer.

Organizing by wave gave the project no place to put a critical path. This program is organized by
**pillar** — the eight things the README says the system is for — and by **vertical slice** — the
one path per pillar that raises it. A pillar is a standing concern with an honest ceiling. A slice
is a single closed path with an observable outcome. Work is chosen by slice, never by kernel.

## The rule

> **A slice is done when a real observation, acquired from a real source, reaches a rendered
> surface, and can be read back after a restart.**

All four clauses, in the same occurrence, over the same observation:

1. **real observation** — bytes a provider actually sent, not a fixture, not a caller projection,
   not a synthetic tape;
2. **real source** — an admitted provider or authenticated product route, through the source
   registry, with its exact request, budget and receipt;
3. **rendered surface** — something a person can read: a Glass view, a published Cockpit V2
   body, a CLI rendering with real identities, or an export a human opens;
4. **read back after a restart** — the process dies, the store reopens, and the same observation
   renders with the same identities, counts, cutoff and digests.

**Nothing else promotes a ceiling.** Not a green test suite, not a fixture receipt, not a valid
digest, not a caller-supplied clock or commit sequence, not a new migration, not a new crate, not a
passing readiness runner, not a design document, and not a review that says PASS. Those are all
useful and none of them is evidence that the system observed anything.

A slice that closes three of four clauses is not seventy-five percent done. It is not done, and its
pillar's ceiling does not move.

## Ceiling vocabulary

Five terms, kept from the Wave 5 and Wave 6 ledgers and reduced. Every pillar and every slice
carries exactly one.

| Ceiling | Means | Typical evidence |
| --- | --- | --- |
| **intrinsic contract** | Pure code validates or transforms values the caller supplied. Correctness of a function, and nothing else. | Unit tests, property tests, typed refusals, exact byte parsers |
| **unverified semantic** | Useful, honest semantics exist, but the inputs are caller projections. The meaning is right; the truth is unavailable. | Kernel with a real ontology and no adapter beneath it |
| **durable offline** | An exact occurrence survives commit, readback and restart in the sole store — but its content is fixture or synthetic. | Migration plus store adapter plus reopen test over checked-in bytes |
| **live** | A real observation from a real source is durably retained, with its exact request, budget settlement, coverage and gaps, and renders after restart. | The rule above, closed once |
| **product** | Ember uses it in the ordinary way, on ordinary days, and the observation reaches her senses under the conditions she actually works in. | A recorded session: real browser, her machine, her morning. Ember is PRIMARILY VISUAL and uses a pointer; she uses a screen reader SOMETIMES, not exclusively, and is not keyboard-only. Do not design as if she were: an earlier version of this line said 'screen reader, keyboard only' and that overstatement propagated into real design decisions before she corrected it (2026-08-23) |

`live` is a per-slice fact, not a per-crate fact. A crate is `live` for the exact path that closed;
it stays `unverified semantic` for every other input it accepts.

`product` cannot be inferred from `live`. It requires a human witness under real conditions, and
for Pillar 8 it requires assistive technology in a real browser.

## Standing prohibitions

These are not phase policy. They hold until each is separately and explicitly retired.

- **No economic authority in any pillar.** No wallet key, signer, transaction builder, blockhash
  request, simulation, submission, relay, or trading endpoint. No pillar acquires one by being
  promoted. The PumpPortal Lightning key stays entirely out of the read-only source plane until
  PumpPortal issues a distinct read-only credential, because that key carries trading authority
  over a linked wallet.
- **Model output may not influence acquisition, ranking, presentation, alerts, hot leases, or
  action** until Pillar 7's own slice is closed and a specific, separately registered intervention
  says otherwise. A learned score may be computed and stored. It may not decide what JOSHI looks
  at, what order it shows, what it warns about, what it leases capacity for, or what it offers to
  do. Pillar 7 closing does not lift this by itself; it makes it discussable.
- **No claim beyond its ceiling.** Fixture arithmetic is not a market fact. A stored digest is not
  provenance. A green Rust test proves nothing about all inputs. Never call a case test
  verification, refinement, or translation validation.
- **No boolean deliverables.** A report emits identities: segment, policy, admission, binding, ACK,
  cutoff, denominator, membership, digest, build, restart evidence, and disqualifiers. A
  completion bit is how `fixtureWalked: true` happened; it does not come back.

## Pillar index

| # | Pillar | Owning crates and apps | Ceiling today | First slice |
| --- | --- | --- | --- | --- |
| 1 | Market-wide information surface | `joshi-surface`, `joshi-publication`, `joshi-projection`, `joshi-market-state`, `joshi-census-bakeoff`, `joshi-market-math`, `joshi-export` | **unverified semantic** | **S1 — First real census** |
| 2 | High-fidelity observation of the attention slice | `joshi-attention`, `joshi-acquisition-policy`, `joshi-retention`, `joshi-sources`, `joshi-supervisor`, `joshi-spool` | **intrinsic contract** | **S4 — One hot lease** |
| 3 | Operator gestures | `joshi-operator`, `joshi-scientific-memory`, `joshi-episode-closure`, `joshi-liquidity`, `joshi-wallet-topology`, `joshi-wallet-source`, `joshi-wallet-admission`, `joshi-accounting` | **unverified semantic** | **S3 — One gesture, end to end** |
| 4 | Executable quote, fill, fee, latency and portfolio accounting | `joshi-accounting`, `joshi-market-math`, `joshi-liquidity`, `joshi-pump-api`, `wave6_shadow_policy`, `wave6_routed_shadow` | **intrinsic contract** | **S7 — One honest would-quote** |
| 5 | Social, community and identity transition histories | `joshi-attention`, `joshi-market-state`, `joshi-pump-api` | **intrinsic contract** | **S5 — One authenticated product read** |
| 6 | Immediate annotations and replay-backed postmortem interviews | `joshi-scientific-memory`, `joshi-episode-closure`, `apps/glass` replay | **unverified semantic** | **S6 — One episode replayed blind** |
| 7 | Model-free empirical study before learned models | `analysis/`, `joshi-epistemic-book`, `joshi-epistemic-admission`, `joshi-census-bakeoff`, `joshi-mechanics-capability`, `joshi-wave6-registry`, `joshi-wave6-campaign` | **durable offline** (fixture content) | **S8 — One estimand on real data** |
| 8 | The accessibility-first keyboard cockpit | `apps/glass`, `joshi-pairing`, `apps/core::service`, `joshi-publication::v2` | **intrinsic contract / fixture UI** | **S2 — One attached-browser session** |

Slice numbers are execution order, not pillar order. See [slice order](#slice-order).

---

## Pillar 1 — market-wide information surface

**Owns:** `joshi-surface`, `joshi-publication`, `joshi-projection`, `joshi-market-state`,
`joshi-census-bakeoff`, `joshi-market-math`, `joshi-export`.

**Ceiling today: unverified semantic.** The kernels are good and their inputs are invented. Wave 5
records that surface inputs are caller projections, that open sample cuts do not recompute subject
order, count or digest, and that stale age is not recomputed from a cutoff. Publication's fact,
coverage, gap and membership digests are unresolved caller values; there is no atomic store
prepare, body, checkpoint and head writer and no mounted immutable route. `joshi-census-bakeoff`
caps at `SampleOnly` because store and source derivation is absent. `joshi-export` refuses every
populated V9 table and emits scenes and coverage while other relations are empty.

**Slice S1 — First real census.** Connect the wire that already exists. Enable
`joshi-admission/source-edges` in `apps/collector`, take one bounded Helius HTTP read of Pump and
PumpSwap activity, adapt the frames through `joshi_admission::batch::source_frames`, commit them
through `AdmissionBatch::commit` into the sole store under a registered run with real supervisor
reservation and settlement, then have `joshi-surface` derive one day's population, facts, gaps and
cutoff *from the store* and render it. No caller supplies the denominator, the count, the cutoff or
the digest.

**Done looks like:** a mint that traded on a real day is named in a surface JOSHI rendered, next to
a count and a cutoff nobody typed. The process is killed, the store reopened, and the same mint,
the same count and the same digest come back. If a source was not covered, an explicit gap row says
so with its exact window.

---

## Pillar 2 — high-fidelity observation of the attention slice

**Owns:** `joshi-attention`, `joshi-acquisition-policy`, `joshi-retention`, `joshi-sources`,
`joshi-supervisor`, `joshi-spool`.

**Ceiling today: intrinsic contract.** `joshi-acquisition-policy` reduces intents into desired
scope but requires a source adapter receipt that does not exist, so no applied record can exist.
`joshi-retention` is a pure typed kernel whose public construction is `UnknownInventory`, with no
verified inventory adapter, no filesystem, replica, export or key controller, and no fault walk.
The only real high-fidelity capture the project has ever taken — 4,911 `logsSubscribe`
notifications and 11,943,303 bytes on 2026-08-16 — is sitting in
`state/probes/helius-readonly-1786932002910/` where the evidence pipeline cannot see it, because
the probe was an example binary that wrote files rather than the pipeline.

That probe also produced the design constraint this pillar has to respect: unabridged two-program
log traffic ran at about 822 notifications/s and 2.00 MB/s. Continuous raw streaming of both
programs is a deliberate capacity decision, not a default. Broad census favors compact lifecycle
events or provider-side filters; full log and transaction evidence is for bounded recovery and
leased hot scopes.

**Slice S4 — One hot lease.** One subject, named by an operator gesture (S3), is promoted to hot
by `joshi-acquisition-policy` against a real resource snapshot. The supervisor opens exactly one
filtered subscription for a bounded window under a preregistered finite budget, retains frames
through the same admission path S1 opened, settles conservatively, and stops. A disconnect produces
an explicit typed gap with its exact window, never a silence.

**Done looks like:** Ember names one mint; for the next bounded interval JOSHI holds a real
subscription for that mint and nothing else; every frame it received is in the store and readable
after restart; and the exact interval it did not observe is a row, with a reason.

---

## Pillar 3 — operator gestures

**Owns:** `joshi-operator`, `joshi-scientific-memory`, `joshi-episode-closure`, `joshi-liquidity`,
`joshi-wallet-topology`, `joshi-wallet-source`, `joshi-wallet-admission`, `joshi-accounting`.

This is crackles, partial exits, retained runners, exits and re-entries, catalyst and fancoin
positions, LP inventory, and later-discovered dispositions — the vocabulary the whole project
exists to measure.

**Ceiling today: unverified semantic.** `joshi-operator` is 2,491 lines with 3 tests. Wave 5
records that scientific memory has no store or Glass ACK path, that its retrospective reveal names
an earlier hidden replay rather than a real reveal occurrence, that global append order tracks
mixed semantic clocks rather than actual commit order, and that replay blob provenance is opaque.
Wave 6's V22 is the closest thing to a real gesture in the repository, and it explicitly refuses to
repair the presentation gap on the one durable act it holds, refuses to equate the memory and
pairing session domains, and refuses to claim a human viewed anything. `joshi-episode-closure` is
exact pure DTO validation disconnected from scientific memory.

**Slice S3 — One gesture, end to end.** A keypress in Glass, over the S1 surface, on a real mint,
travels the paired evidence route into the sole store as one operator act bound to the exact scene
bytes that were on screen at the moment it happened — same session domain, real commit order, no
presentation gap. It survives restart and is re-rendered next to the observation it was about.

**Done looks like:** Ember marks a real coin, reboots, opens the cockpit, and sees her own mark
attached to the thing she was looking at when she made it, with the time she made it and the state
of the screen that provoked it.

---

## Pillar 4 — executable quote, fill, fee, latency and portfolio accounting

**Owns:** `joshi-accounting`, `joshi-market-math`, `joshi-liquidity`, `joshi-pump-api`, and the
frozen `wave6_shadow_policy` and `wave6_routed_shadow` prototypes.

**Ceiling today: intrinsic contract.** The arithmetic is exact and the refusals are typed. The
inputs are entirely authored: Wave 6 records that a caller may author a self-consistent source
artifact, digest and carrier ratio and thereby author scalar PnL, that routed `universe_complete`,
coverage, candidate IDs, scenario identity and terminal manifest ID are supplied directly, and that
no route atlas, isolated ghost, coherent router parity, sequential result or joint portfolio shadow
exists. There has never been a real quote, a real fill, a real fee, or a measured end-to-end
latency. The probe measured RTT (97/124/212/393 ms) and a block-time-to-receipt age, and correctly
refused to call either one provider latency.

**Slice S7 — One honest would-quote.** One real pool state, read through the admitted source path
at a stored slot, retained as exact bytes. One quote recomputed from those stored bytes by
`joshi-market-math` and `joshi-liquidity`, retained as a **would-quote** carrying its slot, its
knowledge cutoff, its receipt clock, and the exact age between chain time and local receipt. No
fill is inferred. No PnL is produced. No counterfactual execution is claimed.

**Done looks like:** a quote in the store whose every input is bytes JOSHI received from a provider,
with an honest age attached, that a person can read and check against what the venue showed. The
first honest sentence this pillar can say is "at this slot, from these bytes, this is the quote" —
and it cannot say it today.

---

## Pillar 5 — social, community and identity transition histories

**Owns:** `joshi-attention` (versioned identity and topology assertions), `joshi-market-state`,
`joshi-pump-api`.

**Ceiling today: intrinsic contract.** `joshi-pump-api` owns honest source-edge mechanics — exact
response bytes, documented routes separated from observed routes, `GET` only — and its normalized
records stay quarantined until an observed schema fingerprint is promoted. No fingerprint has been
observed, because the route has never been called. `joshi-attention` keeps provider observations,
versioned identity assertions, marked attention events and response rows correctly separate, over
nothing. This pillar is the one with the least code and the clearest boundary, and it is invisible
in both wave reviews, which is itself the finding: the social layer was never sequenced at all.

**Slice S5 — One authenticated product read.** One documented Pump product route, fetched with the
honest authenticated session under a bounded budget, response bytes retained as a raw observation
through the same admission path, one schema fingerprint observed and then explicitly promoted or
refused, and one versioned identity or topology assertion derived from those exact bytes. The
credential never leaves the transport client and never appears in bytes, fixtures, arguments or
logs.

**Done looks like:** a real creator or community fact — a name, a link, a transition — in the
store as a versioned assertion, with the exact provider bytes that said so, readable after
restart, and a recorded decision about whether that schema is trusted.

---

## Pillar 6 — immediate annotations and replay-backed postmortem interviews

**Owns:** `joshi-scientific-memory`, `joshi-episode-closure`, `apps/glass` replay.

**Ceiling today: unverified semantic.** The semantics are the most carefully specified in the
repository — separate logical-tick and catalog-sequence types, typed gaps, terminal episode
semantics, outcome-hidden replay, `known <= maturity <= reveal` — and there has never been an
episode. Wave 5 records that the retrospective reveal names the earlier hidden replay rather than a
real reveal or outcome occurrence, that it does not require reveal to follow the retrospective
record, and that replay blob provenance is opaque. `analysis/.../analog_memory` correctly enforces
earlier-only decisions over caller-materialized provenance.

This pillar is the reason the project exists: Ember's actual process has not yet been measured, and
this is the instrument that measures it. It cannot run until Pillar 3 stores a gesture and Pillar 1
stores an outcome.

**Slice S6 — One episode replayed blind.** One real episode, assembled from stored observations
and stored acts: what Ember saw, what she did, and what happened afterwards. Replay it to her with
the outcome hidden, using the store's own retained bytes as the replay source — not a re-fetch,
not a re-render from a projection. Retain her answers. Then reveal, strictly after, and retain the
reveal as its own occurrence with its own clock.

**Done looks like:** one interview in the store whose replay bytes are the store's own observations,
whose answers were given before the reveal existed, and where the ordering is a property of the
data rather than a promise in a document.

---

## Pillar 7 — model-free empirical study before learned models

**Owns:** `analysis/`, `joshi-epistemic-book`, `joshi-epistemic-admission`, `joshi-census-bakeoff`,
`joshi-mechanics-capability`, `joshi-wave6-registry`, `joshi-wave6-campaign`.

**Ceiling today: durable offline over fixture content.** Twelve of the repository's twenty-three
migrations are Wave 6 fixture bookkeeping. Every Wave 6 receipt is
`unverified_semantic_fixture_only`. The two genuine bridges, V20 and V22, resolve *two* fixture
Pump discovery facts from the store and are honest that they admit zero of six market-atlas strata.
`joshi-epistemic-book` requires the store to derive occurrence, frozen evidence, visibility, reveal,
adjudication and earlier-only support, and the store does not. `joshi-epistemic-admission` has no
migration or writer and no positive durable path, and its four "adversarial" tests check an
expectation label rather than executing their vectors. `joshi-export` cannot yet produce a nonempty
snapshot of the populated tables.

**Slice S8 — One estimand on real data.** Take the census S1 produced. Export a nonempty V10
snapshot — with `from_commit_seq` actually applied, publication metadata resolved from the store,
and the Python validator run `--offline` — and reproduce exactly one descriptive number about the
real market in the locked analysis environment, in two runtimes, printed with its complete
denominator, its coverage and gaps, and its cutoff.

**Done looks like:** one number about the actual market, computed twice from bytes JOSHI acquired,
with its denominator beside it, reproducible from the manifest alone. Model-free. No estimator, no
score, no policy.

**Model restriction, restated:** closing S8 authorizes descriptive study on real data. It does not
authorize a model to influence acquisition, ranking, presentation, alerts, hot leases or action.
That requires its own later slice and a separately registered intervention.

---

## Pillar 8 — the accessibility-first keyboard cockpit

**Owns:** `apps/glass`, `joshi-pairing`, `apps/core::service`, `joshi-publication::v2`.

This is the originating product. It is why the project is accessibility-first rather than
accessibility-compatible. It is also the least witnessed thing in the repository, by a wide margin.

**Ceiling today: intrinsic contract / fixture UI.** Glass has 23 test files and roughly 150 tests.
Every one of them runs under jsdom. `axe-core` is present and it audits a virtual DOM. There is no
browser driver in the manifest. Wave 5 states it directly: no attached-browser screen-reader,
keyboard and focus, zoom, reflow, contrast, or pointer and touch witness qualifies accessibility or
product use. `Serve` is unmounted by default, its opt-in is exact-loopback only, and no daily-use
witness exists. The pairing protocol underneath is genuinely strong — human-checkable single-use
codes, durable rate, expiry, revoke and restart state, OS entropy, zeroized non-serializing
secrets, an exact `jpc1_` wire shared by Rust and Glass — and it has never carried a session a
human sat in.

Nothing in Rust can close this pillar. It is the one place where 158,000 lines of exact contract
buy nothing, and the only evidence that counts is a person, a browser and an assistive technology.

**Slice S2 — One attached-browser session.** A real browser, on Ember's machine, paired through
the ordinary one-time code, rendering the S1 surface. Witnessed and recorded: screen reader
announcement of the live regions and the feed, keyboard-only traversal with a visible and correct
focus order, 200% zoom, 320 CSS px reflow without horizontal scrolling, contrast measured on
rendered pixels rather than declared tokens, and a crash, reload and re-pair. Failures are recorded
as failures; this is a measurement, not a demonstration.

**Done looks like:** Ember opens the cockpit on an ordinary morning, with her screen reader on and
her hands on the keyboard, reads a real number about a real coin, and marks it — and that session
exists as a recorded occurrence with its exact findings, including everything that was wrong.

---

## Slice order

| Order | Slice | Pillar | Why here |
| --- | --- | --- | --- |
| 1 | **S1 — First real census** | 1 | It is the only work in the repository that removes nine blockers at once, because nine ceilings are blocked by the same missing edge. Everything else in this table depends on it. |
| 2 | **S2 — One attached-browser session** | 8 | The originating product, and the only pillar whose evidence cannot be produced by writing Rust. It becomes possible the moment S1 renders something real, and it must not wait again. |
| 3 | **S3 — One gesture, end to end** | 3 | Closes the loop: see something real, mark it, get it back. This is the first moment JOSHI measures Ember rather than the market. |
| 4 | **S4 — One hot lease** | 2 | Needs a gesture to name the subject and a census to define the cold denominator. The 2.00 MB/s measurement means this is a capacity decision, taken deliberately, on one subject. |
| 5 | **S5 — One authenticated product read** | 5 | Independent of S3 and S4 and can run in parallel with them. Sequenced here because it opens a second, differently-shaped source and will find the schema-drift problems early. |
| 6 | **S6 — One episode replayed blind** | 6 | Requires stored acts (S3) and stored outcomes (S1, S4). This is the instrument the project was built to run. |
| 7 | **S7 — One honest would-quote** | 4 | Requires real pool state. Deliberately last among the acquisition slices, because it is the one closest to economic authority and it gets none. |
| 8 | **S8 — One estimand on real data** | 7 | Study comes after observation. Everything Wave 6 built is waiting here and none of it should run before there is a real denominator to run it on. |

The order is a dependency order, not a priority order. S2 in particular is not permitted to slip:
the accessibility-first product has now been deferred through two full waves and 900 tests.

## The critical path, concretely

S1 is not a design problem. Every link in the wire already exists and was built and
tested separately; only the last connection was missing:

```text
HeliusHttpClient::request                 -> RawSourceFrame
    crates/joshi-sources/src/helius.rs:174          (ran live 2026-08-16)
joshi_admission::batch::source_frames     -> AdmissionBatch
    crates/joshi-admission/src/batch.rs:190         (behind feature "source-edges")
AdmissionBatch::commit(&mut SqliteStore)  -> PublicStoreReceiptV1
SqliteStore::commit_ingest
```

`source-edges` is declared in `crates/joshi-admission/Cargo.toml`. At the time this program was
written the only crate in the workspace that enabled it was `joshi-pump-adapter`, and neither
`apps/core` nor `apps/collector` depended on `joshi-admission` at all. Closing that gap in the
collector is S1's first move and is in flight. Enabling the feature is not the slice; the slice is
the observation that comes out the other end and renders after a restart.

Two things must be settled before a socket opens, and both are already written down in
[`CLAUDE_HANDOFF_2026-08-19.md`](CLAUDE_HANDOFF_2026-08-19.md):

- **The physical size bound.** The discarded `response_body_bytes + 16 KiB` formula was wrong,
  because the raw body is encoded into `RetainedFrameEnvelope`, then into observation and batch
  JSON, then base64-wrapped by the spool entry. Derive the bound from the actual serializers, or
  project a separate maximum segment size, and make the activation's durable reservation cover it.
- **The C1 authority rules.** The SQLite claim commits before the journal binding and they are not
  atomic; a crash between them permanently consumes the activation and authority is never refunded.
  No I/O before activation binding, worst-case reservation, exact request closure and a fsynced
  I/O-start boundary. Any failure after I/O-start is terminal: no retry, explicit gap, conservative
  maximum settlement, stopped generation.

Real market data and real API keys are authorized. Stay inside sane request volume and the
provider's documented quotas, and do not architect around imaginary risk. The containment that
matters is already built.

## How a slice is run and closed

A slice gets one document, `docs/implementation/slices/SN_<name>.md`, and it contains:

1. **The observable fact** that will close it, written before the work starts, in the form of the
   rule: which real observation, from which real source, on which rendered surface, read back after
   which restart.
2. **The exact path** — every crate, function, migration, route and process the observation passes
   through, named with paths, not descriptions.
3. **The budget** — request count, byte ceiling, wall-clock ceiling, disk ceiling, and what stops
   it, preregistered.
4. **The receipt identities** the run must emit: segment, policy, admission, catalog binding, ACK,
   cutoff, denominator, membership, digests, build, restart evidence.
5. **The fault coverage earned on this path** — the crash boundaries that actually exist in this
   slice, walked. Not a 37-row synthetic matrix for a source nobody uses.
6. **The result**, including everything that failed, and the exact ceiling the pillar now holds.

An adversarial review reads the *statements*, not the summaries, and it reads them against the
rule. A review that cannot name the real observation, the real source, the rendered surface and the
restart does not close the slice.

## What is not a slice

Written down because each of these has already been shipped as though it were progress.

- A new crate with a good ontology and no adapter beneath it.
- A migration whose content is a document about the program.
- A readiness runner, a fault ledger, or a witness bundle over a synthetic source.
- A pure reducer over a tape the caller wrote, however exact its arithmetic.
- A durable, restart-safe, idempotent, cross-runtime-validated fixture.
- A design document that specifies a contract nothing executes.
- A ceiling label. `useful_partial`, `unverified_semantic_fixture_only` and `intrinsic_contract` are
  accurate descriptions and they are not deliverables.
- A boolean.
