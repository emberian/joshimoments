# JOSHI handoff — 2026-08-19 shutdown

Status: **clean committed checkpoint; useful partial; no live C1 provider path**.

This handoff is for work resuming while Codex usage is paused through 2026-08-21. The worktree was
returned to clean `main` at `ca6e059` before this file was added. Do not infer a provider, product,
economic, or root-readiness claim from the green component tests below.

## Commit discipline

The repository owner expects the primary agent to make small commits frequently. Subagents may
edit bounded paths, but the primary agent alone stages and commits after inspecting the exact set.
Before every commit run:

```sh
git diff --cached --check
gitleaks git --staged --redact --no-banner
git commit --no-gpg-sign -m "<narrow message>"
```

Never stage unrelated work, rewrite an applied migration, enable a default live route, use a
credential, submit/sign a transaction, deploy, or treat public DTOs/reports as authority.

## Landed C1 chain

The following commits form one deliberately inert authority chain:

| Commit | Closed boundary |
| --- | --- |
| `4e8157d` | Declares one bounded credential-free public-Solana source/method contract. |
| `56f5e22` | Re-derives exact source and method fingerprints in provider plans. |
| `f553d71` | Freezes the one-page C1 response/runner behavior as package-test-only scaffolding. |
| `3ed6dc2` | Adds strict canonical exact-byte parsing for final provider plans. |
| `557e7fb` | Defines an inert exact C1 activation document with no I/O authority. |
| `5f7fd14` | Binds activation identity to the supervisor-shaped installation identifier. |
| `e948e69` | Migration V23 stores exact activation/plan bytes and atomically burns a one-shot claim. |
| `eba397a` | Closes the structural claim receipt over the exact registered run. |
| `ca6e059` | Consumes the opaque claim into a disabled admission bound to the actual durable supervisor journal. |

At the checkpoint, the store capability and supervisor admission are private-field,
non-serializable, non-cloneable authority carriers. The admitted value retains the burned claim by
value and exposes only a structural report. Foreign-installation refusal leaves the claim burned
after reopen. Public activation bytes, store receipts, readbacks, reports, plan digests, and
`inst-...` strings cannot recreate the capability.

The ceiling is still `read_only_no_execution`. There is no production C1 executor, endpoint
client, request API, attempt reservation, journal I/O-start, spool/store raw-response adapter,
application flag, CLI route, source fact, finality fact, cursor, coverage, or absence claim.
`CollectorRuntimeConfigV1` and `CollectorRuntime` remain C0-only and must not be widened in place.

## Last verified committed gates

Immediately before shutdown, the committed supervisor slice passed:

```sh
cargo fmt --all -- --check
cargo test --locked --offline -p joshi-supervisor --all-targets
cargo clippy --locked --offline -p joshi-supervisor --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline -p joshi-supervisor --no-deps
git diff --check
```

Observed results were 20 supervisor unit tests, one real V23 C1 activation/journal test, eight
continuity tests, and two process-kill tests, all passing. An independent read-only red-team found
no blocker at the explicit disabled/no-I/O ceiling. Earlier V23 landing gates also passed the store
suite, `schema/validate.sh` at 23 migrations, Core suites, strict Clippy, and rustdoc.

## The discarded wire-contract experiment

No wire-contract experiment was left in the worktree or committed. A proposed helper claimed that
`response_body_bytes + 16 KiB` conservatively bounded one spool segment. That is false: the raw
body is encoded inside `RetainedFrameEnvelope`, then inside observation/batch JSON, then the exact
batch is base64-wrapped by the spool entry. Byte expansion can materially exceed the raw body plus
a fixed allowance. The experiment was fully reverted before this handoff.

Do not resurrect that formula. Before any socket can open, derive a deterministic physical bound
from the actual serializers, or introduce an exact separately projected maximum spool-segment
size. Exercise ordinary JSON and worst-case byte patterns at several sizes, prove checked
arithmetic/monotonicity, and require the activation's durable reservation to cover the resulting
bound. The current C1 fixtures with 1,024-byte ingress and durable ceilings are not evidence that a
real retained response fits.

## Recommended next implementation order

1. **Physical-size proof.** Measure and bound exact response -> retained frame -> observation ->
   `DurableIngestBatch` -> `EvidenceBatchEntry` -> physical local segment. Choose a deliberately
   small one-page ingress ceiling if that is the only honest way to remain under the existing
   64 MiB durable profile ceiling.
2. **Pure wire contract, no I/O.** Extract canonical request construction and strict hostile-body
   validation from `crates/joshi-sources/src/public_solana_c1.rs`, while leaving its injected
   executor `#[cfg(test)]`. A valid response returns only unverified raw conformance data. Empty
   `result` never means absence or coverage; payload `confirmationStatus: finalized` is not a
   JOSHI finality fact.
3. **Dedicated C1 supervisor state machine.** Do not generalize the C0 `CollectorRuntime`. Add
   C1-specific journal events and replay validation for activation-bound, reserved,
   request-prepared, I/O-started, raw-local-durable-or-gap, budget-settled, and stopped. Reopen must
   never issue a second request.
4. **Fixed transport inside `joshi-supervisor`.** It must consume the non-cloneable admission and
   exact plan. Do not expose a generic executor, callback, endpoint argument, arbitrary method, or
   reusable permit. Use a fixed credential-free endpoint, POST body, ID, method, finalized request
   constraint, redirects disabled, retries disabled, proxy inheritance disabled, fixed safe
   headers, trusted monotonic/wall clocks, a strict deadline, and an honestly bounded streaming
   body. Errors must omit URL/body/headers.
5. **Raw evidence durability.** Persist the exact response only as an opaque public-source raw
   observation with no source events, assertions, cursor, coverage window, absence result, chain
   location, or semantic finality. The physical policy must close the exact observation IDs,
   protection, retention, writer context, batch bytes, and spool/catalog receipt before any
   positive result.
6. **Local-only adversarial tests.** Use a private loopback server or scripted private transport;
   do not contact a public endpoint in tests. Cover request bytes/headers, redirect, timeout,
   missing/chunked/lying length behavior, streaming overflow, status/media type, duplicate JSON
   fields, wrong ID, row bound/order/signature/finality, post-I/O gap/maximum settlement, every
   crash prefix, zero retries after reopen, and unchanged C0 replay.
7. **Only then consider one deliberate nonfixture read.** It must be opt-in, one page, public and
   credential-free, with exact activation, reservation, I/O-start, local durability, settlement,
   stop, and reopen evidence. Do not mount a default app/CLI route merely because the library path
   is green.

The official Solana cluster page observed on 2026-08-19 names
`https://api.mainnet.solana.com` as the rate-limited public mainnet endpoint and warns it is not
intended for production applications: <https://solana.com/docs/references/clusters>. One design
note incorrectly used the older `api.mainnet-beta.solana.com`; re-verify the official page before
freezing endpoint bytes.

## Crash and authority rules to preserve

- The SQLite activation claim commits first. SQLite and the supervisor journal are not atomic.
- Failure after claim but before journal binding permanently consumes the activation; never
  recreate or refund authority.
- No network I/O may occur before the C1 activation binding, worst-case reservation, exact request
  closure, and I/O-start boundary are journal-fsynced.
- A pre-I/O crash may cancel/refund only when replay proves I/O did not start.
- Any crash or error after I/O-start is terminal: no retry, explicit gap when possible, conservative
  maximum settlement, and stopped generation.
- A segment fsynced before its journal record must be rediscovered idempotently on reopen; it must
  not become a false gap or a second request.
- Structural reports and receipts remain evidence, never authority inputs.

## Reuse and traps

- Reuse supervisor `BudgetLedger`, journal/fsync/fault machinery, deterministic local spool,
  queue/drain, gap/stop, and conservative replay concepts, but use a separate C1 scanner/event
  family so C0 semantics do not silently change.
- Reuse the raw frame and evidence-envelope types only after adding a C1-specific adapter. The
  current runtime adapter deliberately accepts fixture transport only.
- Do not reuse `PublicSolanaHttpClient` unchanged for this authority path. It accepts caller
  endpoint configuration and arbitrary read methods, follows the ordinary client behavior, and
  reads the whole body without the required physical proof.
- `reqwest 0.13.4`, Rustls, Tokio, and bounded `response.chunk()` patterns already exist in the
  workspace. `joshi-pump-api` demonstrates `redirect(Policy::none())`, `retry(never())`, timeouts,
  and incremental body capture.
- Keep the source registry declaration and V1 runtime configuration immutable. The separate C1
  activation is the post-registration permission document; absence of its one-shot store claim is
  deny-live by default.

## Wider plan after C1

Wave 6 contract/recovery foundations are already committed through the domain-evaluation tranche
(`c53ef01`, `4586761`, `4554520`) and earlier Wave 6 commits. Their strongest current claims remain
intrinsic/fixture-recovered unless a store-resolved adapter says otherwise. After the C1 raw truth
boundary settles, resume the planned Wave 6 N10/N12 joins rather than promoting fixture analyses.

No live provider request, credential access, paid query, signing, transaction construction,
submission, trade, deployment, or external mutation occurred during this shutdown tranche.
