# JOSHI reconciler — the only bridge, designed as an instrument

Companion to `JOSHI.md` §2.2/§7 and `design/domain-model.md` §4.2/§10. The reconciler is the
component that turns chain observations about **our five wallets** into desk facts. It is:

- the **only tape→journal bridge** — nothing else may lift an observation into a desk fact;
- the **only resolver of `Unresolved` orders** — no retry loop, no executor, no operator
  click resolves an ambiguous submission; chain evidence does, through here;
- the **divergence classifier** — every landing reconciled against its plan, every
  divergence classified `{bug, modeling error, parameter gap, irreducible, unclassified}`;
- the establisher of **basis** — `Basis.FromChainFills` has exactly one constructor site,
  and this is it.

It gets its own design page because its failure mode is the project's oldest one. HANDOFF's
verdict from a night of forensics: **every error found was a labelling error — not one was
arithmetic.** The chain measures perfectly and cannot tell you what anything *is*. And the
class is live, not historical: two reconciler-shaped misclassifications happened this week —
the 757-SOL fee label and the fabricated addresses. A component whose whole job is labeling
is a scar generator unless it is built as an instrument: deterministic, falsifiable, audited,
and honest about its residual. That is scar #11 in JOSHI.md §9.2, and this page is its
embodiment.

---

## 1. Inputs and outputs

**Watches:** all five wallet addresses and their token accounts (167 at last census —
`RESULT_position_history.md` is the reference reconstruction), live keys and watch-only
alike. The watch-only wallets are where labeling errors hid last time; coverage is uniform.

**Reads:** the tape (trades, reserve readings, transfers touching watched addresses), the
signer spools (`signer/<key>` streams — what we *tried* to do), and the order projection
(what we *planned* to do). Never vendor APIs directly; the tape is the one throat.

**Emits (journal events, complete list — anything else is out of its mandate):**

| event | when |
|---|---|
| `fill.attributed` | a watched wallet's swap matched to an order (or flagged orderless) |
| `basis.established` | chain fills prove what was paid — the only `FromChainFills` site |
| `order.resolved` | an `Unresolved` order proven landed or dead (§4) |
| `reconciliation.recorded` | plan vs observed, divergence classified (§5) |
| `toll.claim_observed` | a fee-vault claim by a watched wallet |
| `transfer.observed` | value moved to/from a watched wallet outside the order path — payments, dust, vesting releases; labeled only via the battery + attestations |
| `reconcile.defect` | a row the reconciler refuses to interpret (§6) — the defect stream, never a silent drop |

---

## 2. Idempotency — deterministic derivation, replay-safe

Every emitted event's id is **derived, not generated**:
`event_id = f(signature, wallet, leg_index, event_kind)` — a pure function of the evidence.
Consequences, each load-bearing:

- **Re-running over the same tape emits byte-identical events.** The journal append is
  refuse-on-duplicate-id, so a re-run is a no-op, not a double-book. Crash anywhere,
  restart from any checkpoint, nothing double-counts.
- **Incremental and from-genesis runs must agree.** The parity between "tail the tape" and
  "re-derive everything" is a scheduled CI check, same discipline as
  projection-rebuild-from-genesis. Divergence between the two modes is a reconciler bug by
  definition.
- **`t_event` comes from the chain (block time), never from processing time**, and a row
  without a block time goes to the defect stream — never fabricated, never fitted from
  slots (measured residual p90 ≈ 24 s against responses measured in minutes; the Track B
  rule holds here).

---

## 3. The classification battery — HANDOFF's tests, mechanized

Classification runs a fixed, ordered battery of the discriminating tests that actually
worked, each cheap, each recorded with its answer on the emitted event (provenance for the
glass's hover):

1. **Whose lamports went down?** Presence in `accountKeys` proves nothing; balance deltas
   prove payment. "Touched" is never "moved."
2. **Who owns the account?** System-owned = a wallet, possibly a person. Program-owned =
   plumbing (a PDA, an escrow, a vault), **never a counterparty**. This single check would
   have prevented several of the catalogued errors, including fee-escrow-as-rando.
3. **Does it receive from anyone but us?** A deposit address receives from one owner; a
   payee receives from many. Separates the two categories in one pass.
4. **Is it one delta over many legs?** A route/arb carries one native SOL delta and no way
   to attribute it per leg. **Refused, kept visible as smaller n** — the v1
   `prints_from_wallet_payload` rule: never split a delta evenly and invent a per-leg price.
5. **Attestation lookup.** The operator's labels (address book, "that one is mine," "that
   one is a scammer") apply last, with their confidence carried onto the event — attested
   never masquerades as measured.

A row that exits the battery unlabeled is **`Unclassified` — a first-class, rendered
outcome**, counted in every denominator it belongs to. The catalogue's corollary is the
rule: *absence of a label is not absence of meaning* — three separate reports improved the
moment they were forced to name their residual instead of forcing it to zero. The reconciler
never folds a residual into the nearest bucket; that fold is precisely what produced the
fee-escrow, exchange-deposit, and gift mislabels.

---

## 4. Resolving `Unresolved` — the protocol

An `Unresolved` order is a submission whose outcome is unknown (v1's hardest-won state).
The reconciler is its only exit, by exactly two proofs:

- **Proof of life:** the signature appears on chain *and* the expected balance movement is
  observed on the watched wallet. Both — a landed signature with no balance change is a
  defect row, not a fill.
- **Proof of death:** the transaction's blockhash is expired (`isBlockhashValid` false, the
  v1 mechanism) *and* the signature has not landed by then.

Until one proof exists, the order stays `Unresolved` and the glass keeps it in the
right-pane pin. **No time-based auto-resolution, no retry, no operator override** — the v1
double-submit happened because a timeout was treated as an answer. Ambiguity is a state,
not an error to be aged out.

## 5. Divergence classification

Every landed order gets a `Reconciliation` row: plan vs observed, in lamports, classified.
The classes have owners and consequences:

| class | meaning | consequence |
|---|---|---|
| `None` | within stated tolerance | — |
| `ParameterGap` | a friction constant was wrong (priority, rent, fee tier) | feeds the friction artifact's next version — this is how the constants stay measured |
| `ModelingError` | our fill/impact model missed structurally | opens a study lead; the kernel's fill model is the reference |
| `Bug` | the plan and the send disagree | pages the operator; a run of these suspends arming |
| `Irreducible` | slot-drift / MEV residue at stated bounds | tracked; growth in this bucket is itself a signal |
| `Unclassified` | the battery could not decide | rendered, counted, resolvable only by operator attestation |

Classification rules are code with tests, not judgment calls at 2am — and where the rules
cannot decide, `Unclassified` is the honest answer (§3).

## 6. Error states — enumerated, never retried into submission

The defect stream (`reconcile.defect`) is typed; each state names what evidence would
resolve it, and **retry happens only on new evidence** — a new tape row referencing the
signature, a new attestation — never on a timer against the same bytes. *Unreconcilable is
a rendered state, not a retry loop*:

- `MissingBlockTime` — resolvable by a block-time backfill row; never fitted, never guessed.
- `AmbiguousLegs` — multi-leg single-delta (§3.4); resolvable only by better decoding,
  visible as reduced n meanwhile.
- `UnknownCounterparty` — battery exhausted; resolvable by operator attestation.
- `SignatureUnseen` — a spool row with no chain echo yet; becomes proof-of-death at
  blockhash expiry (§4).
- `ConflictingSources` — two tape sources disagree on the same signature; both readings
  kept, neither trusted, surfaced (the cross-vendor reconciliation discipline: 93/100 exact
  was reported as 93/100, not 100).

## 7. Who audits the auditor

The reconciler's own mislabels are the scar class, so it gets the full instrument
treatment, on a schedule (SWARM.md cadence — the audit runs on a calendar, not on a feeling
that the work looks finished):

- **Both controls, always.** Planted-world tests in both directions: a known-zero world
  (synthetic tape where nothing is ours — any attribution is a false positive) *and* a
  known-effect world (planted fills, planted payments, planted poisoned addresses — all
  must be found and correctly classed). A reconciler that labels nothing passes a
  false-positive test perfectly; only planted recovery catches it.
- **Adversarial fixtures from the catalogue.** Every row of HANDOFF's error table — the arb
  no-op, the fee-escrow PDA, the operator's-own-payee "exchange deposit," the LP-deposit
  "gift," the sell "distribution" — plus this week's two, as named regression fixtures. The
  catalogue is the test suite; a new mislabel joins it the week it is found.
- **Mutation discipline** — battery steps knocked out one at a time must each fail their
  planted fixture (and `__pycache__`-class invalidation hazards handled per SWARM.md).
- **The scheduled adversarial audit reads the classifications, not the green.** It samples
  real emitted events, re-derives them by hand against chain, and reports per-class
  precision with n — rendered on the glass beside the reconciler's own health, because an
  instrument that will not state its error rate is a vibe with a socket.
