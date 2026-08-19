# Wave 5 collector acquisition

This lane turns the Wave 4 continuity shell into a foreground, bounded acquisition process. The
implemented authority remains `read_only_no_execution`: the collector may reserve source work and
append exact observations or explicit gaps to its local spool, but it has no catalog/SQLite writer,
Glass client, wallet reader, transaction builder, signer, submitter, or economic authority.

## Current promotion state

`C0` is the only runnable acquisition profile in this implementation wave. It uses a deterministic
provider runner that performs no network I/O and exercises the same plan, reservation, budget,
generation, queue, durability, gap, shutdown, and replay boundaries intended for later adapters.
`C1` and `C2` can be parsed and checked against their frozen ceilings, but remain provider-disabled.
The C1 validator now rederives the one credential-free public-Solana source and method from the
canonical source registry and accepts an exact one-page plan only as
`ValidationOnlyNoProviderIo`. C2 has no admitted source projection. A valid configuration, source
declaration, budget, or validation-only plan is never permission to contact a provider.

Live promotion additionally requires all of the following to close outside this lane:

- one exact `Wave5RunRegistrationV1` committed through the sole store before provider I/O, with a
  full `Wave5RunReferenceV1` bound to each collector attempt;
- operational admission of the exact registered source and method, including `Enabled` status,
  inactive kill switch, compatible access/credential authority, bounded method response and cost,
  and the registered protection and retention class;
- durable per-run budget recovery, or a fresh store-qualified run occurrence on every invocation,
  so process restart cannot reset a metered ceiling;
- supported provider-account evidence for remaining allowance, reset, included credits, and a
  capped or disabled autoscaling policy; and
- a reviewed live adapter whose provider I/O entry point requires the supervisor's opaque permit.

Credentialed PumpPortal is categorically absent. Its current API key is wallet-bearing signing
authority even for zero-priced routes. `PumpPortalConfig` rejects a key path, and no provider method
using that key is admitted to this read-only process. Wallet private-key dotfiles are never read.

## Foreground boundary

The `joshi-collector run` command accepts an existing collector root, the exact registration plus
its build/source-tree/configuration/budget/privacy/daily-use-surface child documents, the final
run-bound provider plan, and one bounded JSON fixture body. Unknown fields, invalid contract
versions, authority widening, unsupported profiles, incomplete child closure, template/final-plan
substitution, unbounded operations, unsafe protection/retention combinations, and ceilings above
the selected canary profile refuse before source execution. C0 contains no credential reference;
secret bytes never enter arguments, output, logs, evidence metadata, digests, or error messages.

The V2 registered configuration closes a domain-separated `planTemplateDigest` computed over every
provider-plan field except the run occurrence. Each operation contains both the exact canonical
source-contract fingerprint and exact method-schema fingerprint; validation rederives and compares
both before admitting the operation. After registration, the final plan adds the exact run ID and
registration digest and receives a separate final digest. Each attempt reservation carries the
complete run reference and both plan digests. This breaks the otherwise cyclic
configuration/registration/plan digest graph without allowing a same-name contract, source,
method, operation, cap, or cross-run substitution.

Each provider step is deliberately two phase:

```text
pure run-bound provider plan
  -> validate exact run/source/method/generation and worst-case cost
  -> reserve worst-case request/ingress/durable/credit/time capacity in memory
  -> append durable AttemptReservation containing the exact claim and plan/run closure
  -> append durable I/O-start boundary
  -> issue one opaque permit
  -> execute the provider step (C0 synthetic only in this wave)
  -> append evidence or a source-contract-specific gap/unavailable result
  -> fsync local spool
  -> append exact budget settlement durably
  -> release unused reserved capacity
```

Cancellation may release a permit only when provider I/O provably did not begin. An error after I/O
still consumes the request, received bytes, elapsed time, and observed provider credits; an
unbounded, underreported, or over-budget response stops the generation and emits an explicit gap.
Journal replay is an ordered reservation -> I/O-start -> local-durability -> settlement state
machine: foreign, duplicate, reordered, or forged transitions refuse. A crash-ambiguous started
attempt is charged its full bound, a missing terminal stop/gap is repaired on reopen, and a run with
any prior attempt remains terminal rather than replaying a fresh runner from ordinal one. Queue
saturation also stops the affected runner before the control reserve and persists its downtime/gap
boundary. The pre-existing source connection machines create a new generation on reconnect and
never erase the prior gap; C0 itself contains no socket or reconnect.

The accepted progress vocabulary is intentionally small: captured evidence; durable bounded-empty
only where the exact source contract authorizes that absence claim; explicit unknown; explicit
unavailable; or explicit gap. A quiet socket, generic heartbeat, authentication failure, one empty
page, `304`, full page without a cursor, or reconnect is never promoted to coverage without the
source-specific contract that would make it so.

## Frozen C0-C2 ceilings

| Profile | Scope | Requests | Provider credits | Ingress | Durable | Time | Rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C0 | one sealed deterministic no-network source operation | bounded by exact local plan | 0 | at most 64 MiB | at most 64 MiB | at most 1 h | local only |
| C1 | one exact public-wallet conformance page; currently validation-only public Solana | 25 | profile ceiling 250; admitted public method 0 | 64 MiB | 64 MiB | 60 s | bounded per attempt |
| C2 | at most three compact windows and 60 raw-log seconds | 10,000 | 10,000 | 256 MiB | 128 MiB | bounded registered run | 8 MiB/s |

Every dimension is independent; unused bytes cannot pay for requests or credits. Work terminates at
the first exhausted ceiling. Worst-case in-flight use is reserved before execution and reported
separately from provider-observed billing, which never impersonates an invoice. A method whose
cost, response size, timeout, or maximum in-flight overshoot cannot be bounded is unrunnable.

## Host and privacy sequence

The first runs are foreground and session-bound on the Mac. Sleep, crash, power loss, or process
exit opens an acquisition gap; the Mac is not an availability claim. `persvati` is eligible only
after supported-LTS, dedicated identity, release, credential, lid/suspend/reboot, disk, and network
gates. It remains outbound-only and spool-only. `hbox` is encrypted replica/batch capacity only
after its OS, memory/swap, and ZFS gates; it receives neither provider credential nor decryption
key and is never the sole copy. Hetzner is considered only after local evidence demonstrates gaps
or unacceptable agent contention, with the identical outbound-only spool protocol and no wallet
key.

Initially the Mac is the sole catalog/Glass writer. A remote collector may append bounded exact
spool segments while it is offline, but cannot mint catalog acknowledgements or advance a durable
catalog cursor. Replica acknowledgement never authorizes deletion. Authenticated social and raw
screenshots remain bounded Ember-present Mac-local captures until the retention controller closes;
continuous private capture is unavailable, not silently retained.

## Provider promotion order

The broad cheap layer is a minimal launch/lifecycle/pool census with raw evidence and clocks, not a
full program trade tape. The warm layer adds preserved Pump membership/order/pagination, one-time
exact-mint enrichment, lifecycle revisions, and an independently sampled chain control. Bounded hot
leases add at most five mints and ten watched wallets at the initial 60-second baseline. Episode
fidelity hydrates one to three subjects only when an operator episode earns it. Every hot lease
retains its census denominator, reason, TTL, desired/applied/control closure, cost, and coverage;
`Applied` means local collector state, never provider acceptance or coverage.

The paid-data sequence is therefore C0 fault walking, C1 one-page conformance, C2 compact-census
bakeoff, then a separately reviewed selective canary. The Helius candidate must be compared with a
bounded finalized-transaction reference; raw program logs are only mentions and may be truncated,
failed, or noncanonical. The outcome may honestly be `sample_only` or `unavailable`. Direct Pump
product routes are promoted one at a time from Ember-present paired acquisitions; the companion is
reconnaissance/drift/fallback rather than the primary continuous pipeline.

## Verification witnesses

The lane's tests prove strict unknown-field refusal, PumpPortal credential refusal, exact C1/C2 cap
refusal, sealed status/kill-switch admission, template/final/run substitution refusal, pre-I/O
reservation ordering, no-I/O cancellation, exact started request/page accounting, journal-first
post-I/O settlement, ordered adversarial restart recovery, bounded in-flight overshoot, rate
limiting, source-specific quiet/empty/gap semantics, generation changes in the lower source state
machines, queue-saturation stop, graceful shutdown, kill at durability boundaries, and exact
offline replay. Tests and fixtures make no provider call and spend no provider credits.

The sealed C0 fault matrix is finite and uses the same one-request/one-page fixture path as the
foreground command. It exercises: in-memory budget hold before durable reservation; reservation
temporary/rename/health interruption; I/O-start interruption; runner, report, adapter and usage
refusal after I/O; queue saturation; spool append interruption; local-durability journal
interruption after a sealed segment; settlement interruption; stop/downtime interruption; and two
successive reopens. On reopen, a reservation with no I/O-start is durably cancelled and refunded
without inventing a source gap. A started reservation with no terminal closure is charged at its
declared maximum, gets an explicit scoped gap or downtime boundary when that write can complete,
and makes the run replay-only. A sealed exact evidence segment discovered before its journal event
is recorded as local durability and never relabeled as a gap. Settlement is always appended to the
journal before the in-memory permit is released; if that append or subsequent health write is
ambiguous, the process remains terminal with its conservative hold until restart reconstruction.
A successfully settled finite C0 completion records a no-gap terminal generation boundary before
ordinary supervisor shutdown: it has no continuing stream interval, so shutdown or reopen must not
fabricate a downtime gap.

The foreground report is `RuntimeRunReport`: exact run ID, plan ID/final digest, finite completion
reason, one local-spool receipt and progress/usage row per C0 fixture step, final budget snapshot,
and shutdown report. It is a local spool witness only. Catalog admission, catalog ACK, source fact,
publication, export/import and live-provider qualification remain separate I2/I4/I5 integration
work and are not implied by this report.

The offline G0 Core component now supplies the exact reviewed Pump fixture batch to this sealed C0
carrier, then admits the supervisor's fsynced segment bytes through the sole store and records the
catalog ACK only after the run binding commits. That composition closes one fixture-only
reservation→origin→catalog handoff, but does not change this package report's authority or enable a
provider, live source, or product route.
