# Wave 5 closeout

Status: **closed, not promoted**. Wave 5 is over because the wave framing is being retired, not
because it reached its gate. `W5-G0` never ran. Nothing in this wave attained `live` or `product`.
The active program is now [`docs/implementation/PILLARS.md`](../PILLARS.md).

The ceiling ledger in [`99_INTEGRATION_REVIEW.md`](99_INTEGRATION_REVIEW.md) is the source of truth
for every claim below. This document does not re-adjudicate it. It records what the wave actually
produced, what it claimed that did not hold, what carries forward, and what is abandoned.

## What Wave 5 actually delivered

These are real and they are kept. They are also, without exception, kernels rather than paths.

| Delivered | Owner | Honest ceiling |
| --- | --- | --- |
| The sole-store spine: migrations V9 and V10, append-only run/spool/catalog/operational/import tables, store-owned commit clocks, restart reverify | `joshi-store` | `durable offline`, those row families only |
| Run registration as seven exact byte strings with strict component semantics and a digest-cycle-free plan template | `joshi-admission::wave5` | `intrinsic contract` |
| An append-before-I/O supervisor journal with conservative ambiguous-start charging, terminal replay-only recovery, and real process-kill and panic tests | `joshi-supervisor` | `durable offline`, package-local C0 |
| One compiled public C0 fixture circulation: immutable origin bytes, exact segment/batch/policy/receipt, run-bound catalog binding, local ACK, retry and reopen | `apps/core::wave5_circulation` | `durable offline`, one fixture route |
| A one-time-code pairing protocol with durable SQLite rate/expiry/revoke/restart state, OS entropy, zeroized secrets, and a matching Rust/Glass `jpc1_` wire | `joshi-pairing` | isolated durable protocol, unmounted by default |
| Point-in-time surface reduction with closed-universe partitioning and exact profile x source x subject x field closure | `joshi-surface` | `unverified semantic` |
| Cockpit V2 publication contracts: strict manifests, per-cell fact/gap checks, exact eligible/render/omission partitions, distinct digest domains | `joshi-publication::v2` | `unverified semantic` |
| Append-only scientific memory with separate logical-tick and catalog-sequence types, typed gaps, terminal episode semantics | `joshi-scientific-memory` | `unverified semantic` |
| A typed C0/C1/C2 source registry where sealed C0 is one request, one fixture page, zero provider credits | `joshi-source-registry` | `intrinsic contract` |
| The C1 activation chain: an inert exact activation document, installation-bound identity, migration V23 one-shot burn, claim consumed into a disabled supervisor admission | `joshi-wave5-c1-activation`, `joshi-supervisor` | `read_only_no_execution` |
| The ceiling vocabulary itself, and the adversarial-review practice that produced these ledgers | reviewers | this is the wave's best output |

One thing outside the wave's own accounting deserves recording here, because it is the sharpest
fact available about what Wave 5 was for. On 2026-08-16 an authorized bounded probe
(`crates/joshi-sources/examples/live_provider_probe.rs`) made 23 real Helius HTTP requests and held
one filtered `logsSubscribe` socket for 5.979 seconds, receiving 4,911 log notifications and
11,943,303 bytes of real Pump and PumpSwap market traffic. That capture is characterized in
[`../LIVE_PROVIDER_PROBE.md`](../LIVE_PROVIDER_PROBE.md) and the bytes are still on disk in
`state/probes/helius-readonly-1786932002910/`. Not one of them ever entered the store. The probe
was an example binary that wrote files; it was not the pipeline. Wave 5 then spent its remaining
weeks building fault harnesses for a synthetic source while twelve megabytes of real market data
sat in a directory the evidence pipeline cannot see.

## What Wave 5 claimed that did not hold

**"Living Instrument authority spine."** The spine exists as segments. It was never a spine,
because no vertebra is attached to the next one in the same occurrence. The review states this
seam by seam: the collector does not load its run or plan from the sole store; the supervisor is
not attached to the store-readback run or the catalog ACK; the ACK carries no run-binding identity;
the surface, retention, memory, epistemic and Cockpit V2 adapters do not exist. Every green result
is package-local.

**"First integrated walking path."** The `PROGRAM.md` walking path — source, envelope, commit,
projection, API, glass, snapshot, analysis, replay — has never been walked by one process over one
observation. `apps/core` has nineteen subcommands and sixteen of them are readiness or
fault-witness runners. There is no `collect`, no `ingest`, no ordinary run.

**`fixtureWalked: true`.** `scripts/wave5-readiness` set a ladder-shaped completion bit for a
run-registration-and-reopen test. The review names this fixture laundering. It was repaired to
`qualification.fullOfflineFaultWalk: false` plus the narrower
`public_c0_spool_catalog_closed` label. The repair must be retained. The fact that the claim was
made at all is the more important finding: the wave's reporting shape rewarded a boolean over an
identity, and one lane took the reward.

**"Green root gate."** `cargo fmt --all -- --check` was red at the review, on pairing, publication
and surface. An earlier workspace PASS predated the integration changes and was reported as though
it covered them.

**Accessibility.** Glass has 23 test files and roughly 150 tests. All of them run under jsdom.
`axe-core` is a devDependency and it audits a virtual DOM. There is no browser driver in the
manifest. No screen reader, no keyboard focus order, no 200% zoom, no 320 CSS px reflow, and no
contrast measurement on rendered pixels has ever been observed. The accessibility-first product is
the least witnessed thing in the repository.

**Epistemic admission fixtures.** The four tests described as "adversarial" check an expectation
label rather than executing their vectors. That is not an adversarial test.

**Export.** `joshi-export` refuses every populated V9 Wave 5 table, emits scenes and coverage while
other relations are empty, never applies `from_commit_seq` to its queries, accepts caller
publication descriptors, and launches `uv run --locked` without `--offline`.

## The structural mistake

Wave 5 built pure kernels horizontally and never closed a single vertical path from a real source
to a rendered surface.

This is why nine separate rows of the ceiling ledger carry the same blocker sentence in different
words: *inputs are caller projections, no adapter exists*. Surface, publication, retention,
scientific memory, analog memory, epistemic book, operational status, census bakeoff and mechanics
capability are each blocked by the identical missing edge. They are not nine problems. They are one
problem, counted nine times, and each new kernel added a tenth count without reducing the cause.

The wire that removes the cause already existed inside Wave 5 and was left disconnected:

```text
HeliusHttpClient::request                 -> RawSourceFrame
    crates/joshi-sources/src/helius.rs:174
joshi_admission::batch::source_frames     -> AdmissionBatch
    crates/joshi-admission/src/batch.rs:190
AdmissionBatch::commit(&mut SqliteStore)  -> PublicStoreReceiptV1
SqliteStore::commit_ingest
```

`source_frames` is behind `feature = "source-edges"` on `joshi-admission`. Throughout Wave 5 the
only crate in the workspace that enabled it was `joshi-pump-adapter`, and neither `apps/core` nor
`apps/collector` depended on `joshi-admission` at all. A Cargo feature flag, off in both
applications, was the whole distance between this repository and its first real observation. Wave 5
did not identify that as its critical path, because a wave organized by kernel ownership has no
place to put a critical path.

The reviews were correct at every step and still did not prevent this. An adversarial ledger tells
you what a claim is worth; it cannot tell you which claim to go make next. Wave 5 had excellent
judgement about the value of its work and no mechanism for choosing it.

## Carried forward

- The sole store and its migration discipline. V1 through V10 stand.
- The supervisor journal, its append-before-I/O rule, conservative settlement, and the crash and
  panic harnesses. This is the strongest engineering in the wave.
- Admission's exact-byte contracts and the store's independent reparse of the same bytes.
- The pairing protocol and its wire, as the mount for a real cockpit session.
- The surface, publication, memory and status semantics, as the consumers a store adapter will
  feed. Their kernels are fine; their inputs are the problem.
- The C1 activation chain and every crash and authority rule in
  [`../CLAUDE_HANDOFF_2026-08-19.md`](../CLAUDE_HANDOFF_2026-08-19.md). The one-shot burn, the
  no-refund rule, and the terminal-after-I/O-start rule are load-bearing and are not to be relaxed.
- The ceiling vocabulary, reduced and restated in [`../PILLARS.md`](../PILLARS.md).
- The physical-size discipline: the discarded `response_body_bytes + 16 KiB` formula stays
  discarded, and a real bound must be derived from the actual serializers before a socket opens.

## Abandoned

- **`W5-G0` as a precondition.** The 18-role synthetic fault walk is not a gate any more. It
  sequences the most expensive and least informative act ahead of the cheapest and most
  informative one. Fault coverage is now earned per slice, on the path that slice actually uses,
  against real bytes.
- **`useful_partial` as a status.** It is a score for work that cannot be wrong. Retired.
- **The readiness-runner family as the definition of progress.** These runners stay in the tree as
  regression harnesses. They are no longer what "done" means, and no new one is to be added as a
  deliverable.
- **The per-lane document convention.** Twenty-three lane files describing kernels in isolation is
  the horizontal structure written down. Slices get one document each, and a slice document is not
  finished until it names the observable fact that closed it.
- **Any further work whose output is a boolean.** Reports emit identities: segment, policy,
  admission, binding, ACK, cutoff, denominator, digest.
