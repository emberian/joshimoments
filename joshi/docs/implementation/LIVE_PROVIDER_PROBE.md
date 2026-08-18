# Bounded live-provider characterization

Date: 2026-08-16. Status: one authorized read-only run completed; no further live run is
authorized by this document.

## Outcome

The first bounded probe changed the acquisition plan in two useful ways:

1. The available PumpPortal key must not enter the read-only source plane. PumpPortal's current
   official documentation describes its API key as a capability for a Lightning wallet, including
   authority to trade. The probe checked only the credential file's metadata, did not read its
   contents, and made no PumpPortal connection.
2. Unabridged `logsSubscribe` traffic for both Pump and PumpSwap is too large to assume as the
   always-on market denominator. In the 5.979 seconds before the single Helius connection
   disconnected, the two filters delivered 4,911 log notifications and 11,943,303 inbound bytes:
   about 822 notifications/s and 2.00 MB/s. This is valuable hot-scope or bounded-recovery
   evidence, but the observed rate makes a continuous raw two-program stream an explicit capacity
   and cost decision rather than a default.

This does **not** show that broad market observation is infeasible. It shows that the broad census
should favor compact lifecycle events or provider-side semantic filters, while full transaction
and log evidence is acquired for bounded recovery and leased hot scopes. One short, involuntarily
ended interval cannot establish completeness, diurnal load, or a stable daily rate.

## Authorization and containment

The run used `crates/joshi-sources/examples/live_provider_probe.rs`. Its contract was stricter than
the outer authorization in the places that mattered:

| Control | Authorized ceiling | Actual |
| --- | ---: | ---: |
| Helius connections | 1 | 1 |
| Helius HTTP requests | 100 | 23, with no retries |
| Helius filtered WS time | 60 s | 5.979 s |
| PumpPortal connections | 1 maximum | 0 |
| Exact raw disk | 250 MiB hard; 240 MiB soft stop | 12,991,406 bytes |
| Transaction construction/submission | prohibited | none |
| Trading endpoint use | prohibited | none |
| Autoscaling, plan change, or overage authorization | prohibited | none |

The executable accepts no credential argument. It loads the fixed Helius credential file only at
adapter startup, confines the authenticated URL inside the transport client, and renders neither
the URL nor provider errors. The Helius value was not written to raw captures, summaries,
fixtures, process arguments, or this report. The PumpPortal credential value was not read at all;
only regular-file, symlink, and Unix permission metadata were inspected. Both files were regular
files with owner-only mode at probe time.

PumpPortal's [FAQ] says the Lightning API key contains an AES-256-encrypted private key, and its
[Trading API setup] says anyone with the API key can trade through the linked wallet. Its current
[Data API documentation] nevertheless directs data users to that same key. This is a capability
boundary, not merely a secret-redaction concern: a process compromise would expose trading
authority. Until PumpPortal documents and issues a distinct read-only credential, the source
runtime gets zero access to that file.

## What was requested

The Helius HTTP phase performed one finalized `getSlot`, two confirmed
`getSignaturesForAddress` calls with a limit of ten (one for each official Pump program), and
twenty confirmed `getTransaction` reads. The WS phase opened one standard Solana WebSocket and
sent two `logsSubscribe` requests at `processed` commitment:

- Pump program: `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`
- PumpSwap program: `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`

Those program identities come from Pump's official [Pump program] and [PumpSwap program]
documentation. The probe sent no
builder request, blockhash request, simulation, signed bytes, transaction, or relay request.

## Observations

### HTTP sample

| Measure | Result |
| --- | ---: |
| Requests / HTTP 200 responses | 23 / 23 |
| Response body bytes | 215,723 |
| Pump / PumpSwap signatures returned | 10 / 10 |
| Transactions requested / present / null | 20 / 20 / 0 |
| Transactions whose `meta.err` was non-null | 10 |
| RTT min / p50 / p95 / max | 97 / 124 / 212 / 393 ms |
| Block-time-to-local-receipt age min / p50 / p95 / max | 1,682 / 3,021 / 4,365 / 4,490 ms |

All twenty observed transaction results encoded `version` as a JSON number. The age measure is
not provider latency: Solana `blockTime` is second-resolution chain time, and the subtraction also
includes confirmation and query selection age. It is useful only as a freshness bound for these
particular backfill reads.

### WebSocket sample

| Measure | Result |
| --- | ---: |
| Requested / observed duration | 60,000 / 5,979 ms |
| Subscription acknowledgements | 2 |
| Log notifications | 4,911 |
| Inbound bytes | 11,943,303 |
| Mean arrival rate | 821.7 notifications/s; 1,997,541 bytes/s |
| Successful / failed transaction notifications | 2,705 / 2,206 |
| Unique signatures / repeated deliveries | 4,905 / 6 |
| Inter-arrival min / p50 / p95 / max | 0 / 0 / 3 / 121 ms |
| Malformed / rate-limit / ingress-saturation events | 0 / 0 / 0 |
| Disconnects | 1 |

Offline analysis correlated each outbound JSON-RPC request ID with its acknowledgement's
subscription ID. This is the authoritative route classification; scanning log text for program
names is not.

| Subscription route | Notifications | Successful | Failed |
| --- | ---: | ---: | ---: |
| Pump | 2,118 | 413 | 1,705 |
| PumpSwap | 2,793 | 2,292 | 501 |

Six signatures appeared once on each route, which accounts for all six global repeat deliveries;
there were no same-route duplicate deliveries. Three notifications contained Solana's log
truncation marker. Log arrays contained 7 to 149 entries (p50 11, p95 87). A notification proves
that the filtered program appeared in a transaction; it does not by itself identify an economic
event, actor intent, token lifecycle transition, or a successfully decoded instruction.

The socket disconnected once and the hard one-attempt policy then stopped the runner with
`connection_attempt_limit`. Probe v1 counted the disconnect but did not retain its already
sanitized runner reason in the aggregate. That is an instrumentation gap, and it is fixed for any
future run; it does not authorize a rerun. The exact bytes remain available for transport-level
inspection, but no claim about the provider-side cause is justified from this capture.

### Clocks and latency

The probe retained a local receipt wall clock and per-process monotonic arrival timing for every
frame, plus the Solana slot in each notification. Standard `logsSubscribe` does not include a
provider event wall time, so source-to-receipt latency cannot be calculated from this stream.
Inter-arrival time is queue/traffic characterization, not end-to-end latency. Future normalized
events must retain this distinction instead of substituting receipt time for event time.

## Credits and storage

Helius currently documents one credit for a standard RPC call, one credit to establish a WebSocket
connection, and two credits for each 0.1 MB of uncompressed standard WebSocket streaming. On that
basis:

```text
HTTP actual       = 23 calls * 1                         = 23 credits
WS sample         = 1 connection + 2 * ceil(11,943,303 / 100,000)
                  = 241 credits
sample total      = 264 credits
```

Linear projection of this 5.979-second interval gives 172,587,619,869 inbound bytes/day and about
3,451,754 WS credits/day. Projecting the exact frame file, index, and HTTP bodies gives
187,733,312,995 local bytes/day. These figures are deliberately shown to make the capacity risk
visible; they are **not forecasts**. The interval is short, ended on a disconnect, mixes failed and
successful transactions, and may have been unusually busy or quiet. It also says nothing about
the account's plan, remaining credits, autoscaling state, or invoices, none of which these RPC
responses exposed.

Sources for the accounting rule are Helius's [credits documentation] and [WebSocket billing FAQ].
Provider quotas and throttling remain plan-specific under the [Helius rate-limit documentation].

## Captures and reproducibility

Private exact evidence is under the ignored path
`state/probes/helius-readonly-1786932002910/`. It contains length-delimited inbound and outbound WS
frames, a frame index, the 23 exact HTTP bodies, and sanitized summaries. `state/` is ignored and
must remain local; these files may contain public transaction signatures, addresses, and log
content even though they contain no credentials.

The committed
`fixtures/sources/helius_live_characterization_2026-08-16.sanitized.json` contains only schema and
aggregate properties. It omits signatures, addresses, slots, log text, transaction bodies, and
payload values. It is explicitly marked `not_replay_evidence`; it can test our characterization
contract but cannot reproduce provider frames or establish coverage.

## Architectural consequences

The source plane should use three acquisition shapes rather than treating one firehose as the
answer:

```text
compact broad census --------> lifecycle / launch / migration candidate tape
                                  |
operator or policy lease --------+----> exact mint/account/transaction hot evidence
                                  |
bounded gap recovery ------------+----> explicit coverage and uncertainty records
```

- Broad census: find a compact, read-only launch/migration/lifecycle source and measure it under a
  separate cap. Prefer provider-side semantic selection whose completeness and cost can be tested.
  Do not infer that PumpPortal is acceptable just because its broad events may be free; credential
  authority is independently disqualifying for the source process.
- Leased hot scope: keep full logs, transaction fetches, and account/mint subscriptions available
  for coins selected by the operator or later attention policy. These are where exact evidence is
  worth its volume.
- Recovery: use bounded HTTP reads anchored by observed slots/signatures. A reconnect is not proof
  of recovered coverage.
- Storage: preserve exact raw bytes on the evidence path, but normalize and index them separately.
  Never discard failed transactions automatically; their rate is itself market and execution
  information.
- Provider abstraction: retain source-specific health, cost, commitment, and gap semantics. A
  generic `MarketEvent` interface must not erase the difference between live observation and
  complete history.

## Proposed next cap—not authorization

The smallest useful follow-up would validate instrumentation and time variation, not scale the
feed:

- PumpPortal: zero connections and zero credential reads until a separately scoped read-only key
  is documented and issued.
- Helius: one connection attempt, at most 25 HTTP reads, at most 60 seconds total, and at most
  64 MiB exact raw disk.
- Subscribe to the same two programs either on one socket or in two bounded phases, but record
  request-ID-to-subscription-ID route attribution and sanitized disconnect reasons online.
- Stop on authentication/permission/rate-limit response, unexpected billing ambiguity, 8 MiB/s
  sustained volume, queue saturation, or the disk soft limit. No retry, autoscaling, overage, plan
  change, transaction construction, or submission.

Even that run should happen only after an operator explicitly approves it. A more informative next
experiment may instead be a read-only compact lifecycle source conformance probe, because repeating
the same broad log sample is unlikely to change the architectural conclusion.

[FAQ]: https://pumpportal.fun/FAQ/
[Trading API setup]: https://pumpportal.fun/trading-api/setup/
[Data API documentation]: https://pumpportal.fun/data-api/bonk-fun-data-api/
[credits documentation]: https://www.helius.dev/docs/billing/credits
[WebSocket billing FAQ]: https://www.helius.dev/docs/billing/faq
[Helius rate-limit documentation]: https://www.helius.dev/docs/billing/rate-limits
[Pump program]: https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/PUMP_PROGRAM_README.md
[PumpSwap program]: https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/PUMP_SWAP_README.md
