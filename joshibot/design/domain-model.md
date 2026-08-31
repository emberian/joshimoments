# JOSHI domain model — type sketches

Companion to `JOSHI.md` §3. Sketches, not code: names and shapes are normative, member lists
are illustrative. Language is C# per the cut (JOSHI.md §5), with the Lean side sketched where
the kernel is the authority. Everything here is journal-facing; tape (market observation)
types are already landed in `shitcoims_tape/schema.py` and are not re-specified.

Conventions used throughout:

- **No floats in money.** `readonly record struct` wrappers over integers; amounts cross the
  wire as decimal strings (the f64 cliff).
- **Sums are `sealed` hierarchies** switched exhaustively; an analyzer forbids `_ =>` over
  domain sums (C#'s DU gap, mitigated).
- **Provenance types over flags.** Where v1 had a boolean and a comment, v2 has a
  constructor that cannot be called with the wrong inputs.
- **Tri-state observation.** `bool?` where the producer may not have looked; `null` is "not
  observed", never coerced.

---

## 0. Money and identity primitives

```csharp
public readonly record struct Lamports(ulong Value);          // native SOL, integer
public readonly record struct BaseUnits(ulong Value);         // SPL raw units — meaningless without a Mint
public readonly record struct TokenAmount(Mint Mint, BaseUnits Units);  // the only way units travel

public readonly record struct Mint
{
    public string Address { get; }
    private Mint(string address) => Address = address;
    // Validated by base58-DECODE to 32 bytes, never by character class —
    // a regex passes ~1 in 4 lowercased addresses (Track B scar).
    public static Mint? TryParse(string s) => Base58.DecodeLen(s) == 32 ? new Mint(s) : null;
}

public readonly record struct Bps(int Value);
public readonly record struct Probability(double Value);      // [0,1]; the ONE sanctioned double
public readonly record struct RunId(string Value);
public readonly record struct Sig(string Value);              // transaction signature
```

There is no `SolAmount` in doubles anywhere. UI formatting converts at the last moment in the
glass, from strings.

---

## 1. EventEnvelope — every journal event

```csharp
public sealed record EventEnvelope(
    Ulid       EventId,
    string     Stream,          // "journal" | "signer" — one writer per stream
    ulong      Seq,             // monotone per stream
    string     Schema,          // "expectation.recorded@1" — must exist in the registry (build error otherwise)
    Instant    TEvent,          // world clock — NEVER fabricated; reconcilers refuse rows without one
    Instant    TRecorded,       // our clock
    RunId      Run,
    Actor      Actor,
    Ulid?      CausationId,
    Ulid       CorrelationId,   // the saga: order, expectation, playbook run …
    Probability? Propensity,    // MANDATORY when Actor is Playbook/Daemon making a decision
    string     PrevHash,        // hash chain per stream
    JsonElement Body);          // schema-validated; amounts as strings

public abstract record Actor
{
    public sealed record Operator : Actor;
    public sealed record Daemon(string Name, string Version) : Actor;
    public sealed record PlaybookActor(PlaybookId Id, SemVer Version) : Actor;
}
```

Registry entry, one per schema (source generator consumes these to emit the C# record, TS
type, Python TypedDict, and — for kernel-facing events — a Lean structure):

```json
{ "name": "order.planned", "version": 3,
  "body": { "order_id": "ulid", "plan": {"$ref": "plan@2"} },
  "requires": { "propensity": "when actor != operator" } }
```

---

## 2. Command pipeline

```csharp
public abstract record CommandResult
{
    public sealed record Accepted(IReadOnlyList<EventEnvelope> Events) : CommandResult;
    public sealed record Refused(RefusalReason Reason) : CommandResult;   // refusals are DATA — journaled
}

public interface ICommand { Ulid CommandId { get; } Actor ProposedBy { get; } }

// Validation = projections + envelope oracle. The envelope check calls the Lean artifact;
// C# never re-implements the arithmetic (the AIR-in-Lean tripwire, by analogy).
public interface ICommandPipeline
{
    CommandResult Submit(ICommand cmd);   // the ONLY writer of the "journal" stream
}
```

`CommandProposal` is a command not yet submitted — what playbooks and the expectation
compiler emit, and what the glass renders for approval. Proposal is never execution.

---

## 3. Projection

```csharp
public interface IProjection<TState>
{
    string Name { get; }          // "positions", "toll-ledger", …
    int Version { get; }          // bump ⇒ rebuild from genesis (a CI test, not a hope)
    TState Initial { get; }
    TState Apply(TState state, EventEnvelope e);   // PURE — no clock, no IO, no tape reads
}
// Market context (tape) joins at the READ side, in query services — never inside Apply,
// so replay is deterministic and a projection can never smuggle in lookahead.
```

Projection health (`last seq applied`, lag) is itself surfaced to the glass; lag is rendered,
never hidden.

---

## 4. ORDER — the full lifecycle, with the scars as types

```csharp
public sealed record OrderId(Ulid Value);

public abstract record OrderState
{
    // What the actor wants, in domain terms. No route, no numbers beyond intent.
    public sealed record Intent(
        OrderKind Kind,                 // Swap | LpAdd | LpRemove | LpClaim | TollClaim
        Ulid? FromExpectation,          // provenance: which belief/playbook caused this
        Ulid? FromPlaybookRun) : OrderState;

    // Priced. A plan that cannot show its friction line items does not validate.
    public sealed record Planned(Plan Plan) : OrderState;

    // Simulation BINDS the plan: the signer later verifies the exact signed bytes simulate
    // to at least this outcome (v1 transaction.py discipline).
    public sealed record Simulated(Plan Plan, SimReport Sim) : OrderState;

    // Constructible ONLY via GateProof — see §4.1. Not by the domain core.
    public sealed record Armed(Plan Plan, SimReport Sim, GateProof Gates) : OrderState;

    // The signature exists LOCALLY before any submission (double-submit scar):
    public sealed record Sent(Sig Signature, Instant SubmittedAt) : OrderState;

    public sealed record Landed(Sig Signature, FillRef Fill) : OrderState;      // terminal
    public sealed record Failed(FailureClass Why) : OrderState;                  // terminal
    public sealed record Expired(Instant At) : OrderState;                       // terminal
    // Terminal-PENDING: submission ambiguous. Resolved ONLY by the chain reconciler
    // (isBlockhashValid as proof-of-death, balance observation as proof-of-life).
    // NEVER auto-resumed, NEVER retried while unresolved.
    public sealed record Unresolved(Sig Signature) : OrderState;
}

public sealed record Plan(
    OrderKind Kind,
    WalletId Wallet,                    // which wallet acts — the per-wallet allowlist and
                                        //   the per-key signer spool follow from this (§10)
    IReadOnlyList<PlannedLeg> Legs,
    Lamports PriorityFee,               // from the friction artifact — MEASURED 21–53k, not 500k
    Lamports RentTotal,                 // position rent + binArray pioneer rent, itemized in Legs
    TokenAmount MinOut,                 // computed from live reserves + slot-drift allowance;
                                        // wide slippage exists only on the explicit panic path
    string FrictionVersion,             // which friction artifact priced this — stamped, auditable
    Bps PoolImpact,                     // ρ = B/Y; envelope refuses ρ > θ
    RouteProvenance Route);             // what Jupiter/sidecar proposed, kept for the reconciler
```

### 4.1 The three gates as a proof object

```csharp
// GateProof has NO public constructor. joshi-signer's client mints it after checking,
// and the signer process RE-CHECKS all three itself before signing — it never trusts
// the proof it is handed (defense in depth; the sidecar/Jupiter treatment applied to
// our own domain core).
public sealed record GateProof
{
    public bool ConfigEnabled { get; }        // execution.enabled: true (durable intent)
    public bool ProcessLive { get; }          // --live (per-incarnation intent)
    public ArmFileBinding ArmFile { get; }    // mode-0600 file bound to the CURRENT pubkey
    internal GateProof(...) { }
}
```

### 4.2 Reconciliation — every landing is checked against its plan

```csharp
public sealed record Reconciliation(
    OrderId Order,
    Plan Expected,
    ChainObserved Observed,               // from the tape, via the reconciler — the only tape→journal bridge
    Lamports Divergence,
    DivergenceClass Class,                // classification is MANDATORY; "unclassified" is a
    string Note);                         //   visible bucket, never folded into the nearest one

public enum DivergenceClass { None, Bug, ModelingError, ParameterGap, Irreducible, Unclassified }
```

The divergence stream is a first-class research input: `ParameterGap` rows feed the friction
artifact's next version; a run of `Bug` rows pages the operator.

The reconciler that produces these rows — the only tape→journal bridge, the only
`Unresolved` resolver, the classifier whose own mislabels are scar class #11 — has its own
design page: **design/reconciler.md**. Its contract, not repeated here: deterministic
event derivation (idempotent under replay), the discriminating-test battery, and
`Unclassified`/unreconcilable as rendered states, never retry loops.

---

## 5. BASIS — the provenance type that makes the worst bug inexpressible

```csharp
public abstract record Basis
{
    // Only the chain reconciler can construct this, from observed fills of OUR wallet.
    public sealed record FromChainFills(IReadOnlyList<FillRef> Fills, Lamports Paid) : Basis;

    // Operator-typed. Attested ≠ measured; the glass never sums the two populations.
    public sealed record OperatorAttested(Lamports Paid, Probability Confidence, Ulid AttestationId) : Basis;

    // Unknown ⇒ RUG-ONLY: with no basis there is no PnL, so no stop / take-profit /
    // trail / dispose rule can fire at ANY price. Reported as unknown, never guessed.
    public sealed record Unknown : Basis;
}
```

**There is no member of this hierarchy that accepts a `Quote`.** The −7.47 SOL mechanism —
basis stamped from the current exit quote — is not forbidden by policy, it is unwritable.
Draft/edit types in the glass API carry **no basis field at all** (the dashboard-prefill fix,
kept): attestation is its own command with its own ceremony.

```csharp
public sealed record Lot(
    Mint Mint, Ulid LotId,
    TokenAmount Balance,
    Basis Basis,
    Population Population,      // MANDATORY — see below
    LotState State);            // Open | ScalingOut | Closed

// Two populations, two OPPOSITE disciplines (measured: quality is held unless it rugs;
// ghost-town scalps die at 5 minutes — 7/13 +$3.09 under, 1/20 −$61 over).
// A playbook declares its Population and the pipeline refuses a cross-population action.
public enum Population { Quality, Scalp }
```

---

## 6. EXPECTATION — belief, compilation, scoring

```csharp
public sealed record ExpectationId(Ulid Value);

public sealed record Expectation(
    ExpectationId Id,
    Scope Scope,
    Claim Claim,
    Duration Horizon,               // picked in the gesture; defaults per scope
    Probability Confidence,         // declared at record time — this is what Brier scores
    string Utterance,               // VERBATIM, always kept alongside the parse
    IReadOnlyList<EvidenceRef> Evidence,   // chart window, tape rows, RESULT_* docs — at creation
    Instant RecordedAt);

public abstract record Scope
{
    public sealed record MintScope(Mint Mint) : Scope;
    public sealed record PairScope(Mint A, Mint B) : Scope;
    public sealed record ClusterScope(string Name) : Scope;      // "techproject"
    public sealed record TollScope(TollId Stream) : Scope;
    public sealed record BookScope : Scope;
}

// Small on purpose. A claim that binds to no observable is inexpressible (the §9-rung-2
// rule applied to the operator's own beliefs). Grows only when scoring exists for the
// new member first.
public abstract record Claim
{
    public sealed record Drift(Direction Dir) : Claim;                    // "keeps going down"
    public sealed record Range(decimal Low, decimal High) : Claim;        // "chops in here"
    public sealed record EventBy(DeskEventKind Kind, Instant By) : Claim; // "rugs by Friday"
    public sealed record Relative(Scope A, Scope B, Direction Dir) : Claim; // "weave outperforms nosis"
}
```

Lifecycle events: `expectation.recorded` → `expectation.compiled` (proposals emitted) →
`expectation.structure_approved` (operator accepted the diff) → one of
`expectation.resolved` (scored) | `expectation.withdrawn` | `expectation.censored`
(horizon unobservable — recorded as censored, **never dropped**: censoring is data).

### 6.1 Compilation — the nosis example, end to end

```csharp
public interface IExpectationCompiler
{
    // PURE. Emits proposals; arms nothing. The operator approves the diff on the glass.
    IReadOnlyList<CommandProposal> Compile(Expectation e, DeskView view);
}
```

Input — the operator's gesture on the nosis chart:

```csharp
new Expectation(
    Id:         ExpectationId.New(),
    Scope:      new Scope.MintScope(nosis),
    Claim:      new Claim.Drift(Direction.Down),
    Horizon:    Duration.FromDays(3),
    Confidence: new Probability(0.65),
    Utterance:  "idk i think this is gonna keep goin down",
    Evidence:   [chartWindow, hoveredTapeRows],
    RecordedAt: now);
```

Output — four proposals, rendered as one reviewable diff:

```csharp
[
  // 1. Ask-only conversion on every pool holding nosis: bins only ABOVE spot on the
  //    nosis side — the book sells nosis into strength and never adds bids below.
  //    Includes the rebalance pulling existing bid-side bins. Flows through the same
  //    order lifecycle as any LP action (plan shows rent + duty-cycle impact).
  new CommandProposal.SetLpShape(pool: weaveNosis, shape: LpShape.AskOnly(side: nosis)),
  new CommandProposal.SetLpShape(pool: nosisSol,  shape: LpShape.AskOnly(side: nosis)),

  // 2. Suspend buy-side playbooks scoped to nosis while the expectation is active.
  new CommandProposal.SuspendPlaybooks(
        where: p => p.ActionSet.HasBuys && p.Touches(nosis),
        until: ExpectationResolved(e.Id)),

  // 3. The falsifier: an expectation is a position in belief-space and gets a stop.
  new CommandProposal.Alert(
        when: ExitValuation(nosis).RisesThrough(invalidationLevel(e)),
        then: PromptReevaluation(e.Id)),

  // 4. The scoring hook. Scored on EXECUTABLE-EXIT valuation, never last-trade closes
  //    (the bid-ask-bounce scar: VR 0.80–1.01 bounce-free where closes said reversion).
  new CommandProposal.ScheduleScore(e.Id, at: e.RecordedAt + e.Horizon)
]
```

Scoring: for `Drift`, Brier on the sign of the exit-valuation change over the horizon
against the declared confidence; pessimistic marking throughout (ties and unobservables
score against the claim). The scorecard projection aggregates by scope × horizon ×
population, **n beside every rate**, calibration curve on the glass. The point is not to
grade the operator — it is that the operator's taste is the desk's best-measured signal and
this is what "measured" means.

### 6.2 The HUNCH — the minute-scale species, and the zap

Already live in v1 (`state/hunches.jsonl`, the coin-explorer build); v2 imports that tape —
its row shape is this record's, deliberately. A hunch **is** an Expectation, specialized:

```csharp
// Claim vocabulary gains the two minute-scale members:
//   public sealed record Wiggle : Claim;      // "this will oscillate tradably"
//   public sealed record Activity : Claim;    // "something is happening here"

public sealed record Hunch(
    Expectation Belief,                 // claim: Wiggle | Activity | Drift, horizon in MINUTES
    PositionProposal? Proposal);        // immediate: paper by default; live only inside an
                                        //   armed Scalp playbook's pre-authorized budget

// Scored by the POSITION OUTCOME, not Brier-on-drift — the hunch's claim is "this is
// tradable by me, now," and the position is the measurement. Separate scorecard section;
// the two scoring regimes are never summed.
```

The **zap** is the hunch's other half — the one-keystroke exit on every operator position,
and the reason it is a domain object rather than a UI event:

```csharp
public sealed record ZapRecord(
    Ulid LotRef, Instant TEvent,
    TapeStateRef StateAtExit,           // FULL tape-state snapshot ref at the moment of exit:
                                        //   reserves, flow, board membership, age, drawdown —
                                        //   everything a reactive policy could have seen
    Lamports Realized);
```

The accumulated (state, exit) pairs are the training set for the reactive-exit-policy
search (rung 0: the fitted exit policy whose health monitor replaces the clock — the
5-minute wiggle clock is the *backstop*, not the policy; hold-duration was an outcome
miscast as a rule). Doctrine, normative: **the zap never has ceremony** — entry may carry
ceremony (placed per population, JOSHI.md §4); exit is one keystroke, always, per position.

---

## 7. PLAYBOOK — typed program over commands, Lean-checked

```csharp
public sealed record PlaybookId(string Value);      // "ghost-town-wiggle"

public sealed record Playbook(
    PlaybookId Id,
    SemVer Version,                    // every run stamps it; analysis is per-version
    LeanTermRef Term,                  // the AUTHORITY — a term in kernel/Joshi/Playbook.lean
    Population Population,             // Quality | Scalp — cross-population action refused
    IReadOnlyList<GateRef> Gates,      // preconditions over View t (no-lookahead by construction)
    SizingRule Sizing,                 // evolves around a fractional-Kelly spine (§9 rung 3), later
    PlaybookStatus Status);

public enum PlaybookStatus
{
    Draft,        // term exists
    Checked,      // lake build green: well-typed over View t, envelope-compatible,
                  // grammar cardinality N computed (feeds deflated-Sharpe honestly)
    Simulated,    // replay harness: exact kernel fills, purged walk-forward, trials counted
    Shadow,       // paperdesk pattern: propensity-logged, no money
    Armed,        // per-playbook live flag + budget/caps through the full three-gate ceremony.
                  // Ceremony PLACEMENT is per population (proposed-normative, JOSHI.md §4):
                  //   Quality — ceremony per order (typed size confirmation);
                  //   Scalp   — ceremony HERE, at arm time; thereafter clicks spend
                  //             pre-authorized budget inside the playbook. Gates stay
                  //             structural either way; disarm/zap one keystroke, always.
    Retired
}

public sealed record PlaybookRun(
    Ulid RunId, PlaybookId Playbook, SemVer Version,
    Probability Propensity,            // of the action ACTUALLY taken — the paperdesk contract
    IReadOnlyList<CommandProposal> Proposed,
    Ulid? ExpectationBinding);         // which belief parameterized this run, if any
```

The Lean side (sketch — signatures, not proofs; extends the existing `Dsl.lean`/
`Envelope.lean`, which port as-is):

```lean
-- kernel/Joshi/Playbook.lean  (new in v2; everything it imports already exists)
structure Playbook where
  gate    : Pred                      -- from the Dsl grammar: N countable, no lookahead by type
  trigger : Pred
  action  : ActionTemplate            -- emits envelope Actions, never raw transactions
  exit    : ExitRule                  -- clock | model-death subscription | level

-- Inherited for free, because playbooks emit envelope actions and the theorem is
-- quantified over ALL learners:
--   tripped_breaker_is_absorbing, exposure_bounded  (Envelope.lean, proved 2026-08-13)

-- The property worth adding:
theorem playbook_decisions_depend_only_on_view (p : Playbook) :
    ∀ t h₁ h₂, view t h₁ = view t h₂ → decide p t h₁ = decide p t h₂ := ...

def grammarCount (depth : Nat) : Nat := ...   -- N for deflated-Sharpe, counted not guessed
```

Execution follows the proven v1 pattern: the checked term is evaluated by `joshi-oracle`
(the exported C ABI); any fast path is held to exact parity by adversarial tests, and a
skipped parity test is a gate failure. C# orchestrates; it never re-implements a gate.

---

## 8. MODEL — fitted models with residual streams and health

```csharp
public sealed record ModelId(string Value);         // "wiggle-clock/nosis", "ou-ratio/weave-nosis"

public sealed record ModelInstance(
    ModelId Id,
    string Class,                      // "clock" | "ou" | … — rung 0 classes first
    JsonElement Params,
    FitWindow Fit,                     // tape range it was fitted on — provenance
    ModelHealth Health);

public enum ModelHealth { Fitted, Live, Degraded, Dead }

// Written to the journal as the model predicts; the monitor folds them.
public sealed record ResidualObserved(ModelId Model, Instant TEvent, decimal Residual);

// e-CUSUM over the residual stream. VALIDATED against planted shifts before it is
// trusted (both-controls-always: a monitor that never fires passes a null perfectly).
public sealed record ModelDied(ModelId Model, Instant At, string Diagnostic);
```

`ModelDied` is an ordinary journal event, which means playbook gates and expectations can
subscribe to it: *"exit when the model stops predicting"* is a gate clause, not a special
case. The first real instance is the **reactive-exit policy** fitted to the zap-recorded
(state, exit) pairs (§6.2) — the operator's exits were never duration-based, so the model
to monitor is the reaction, and the wiggle book's 5-minute clock is demoted to the backstop
that fires when the fitted policy has nothing to say (a clock is a model whose residual is
elapsed time — the degenerate case, kept as the floor, not the policy).

---

## 9. TOLL — fee streams as income objects

```csharp
public sealed record TollId(string Value);          // "dregg-creator-vault", "lp/weave-nosis", "dregg-vesting"

public sealed record TollStream(
    TollId Id,
    TollKind Kind,                     // CreatorVault | LpFees | VestingEscrow
    TollStatus Status,                 // Discovered | Metered | Decaying | Dead
    Duration? VolumeHalfLife);         // measured, with CI — decay is real (t½ ~12d from launch)

public sealed record TollClaimObserved(TollId Stream, Instant TEvent, Lamports Amount, Sig Signature);

// THE structural rule from the memory: obligations attach to fee streams, NEVER the book.
// An LP-strategy agent once recommended dismantling 2/3 of the book to cover 5 days of
// fee income because a brief handed it cash dates. The constructor makes that unwritable:
public readonly record struct Usd(decimal Value);   // obligations are FIAT — rent is dollars
public sealed record Obligation(
    string Name, Usd PerMonth, DayOfMonth Due,
    TollId CoveredBy);                 // TollId, not Book. There is no overload taking Book.

// The right control is a TRIGGER, not a schedule: monitor run-rate vs upcoming dates,
// act only if coverage actually fails. Income is SOL and obligations are USD, so a
// CoverageReading carries its own conversion exposure — days-covered is a function of a
// rate that moves, and the glass renders the sensitivity, never just the point estimate.
public sealed record CoverageReading(
    TollId Stream, Instant At,
    Lamports RunRatePerDay,
    decimal SolUsd, string SolUsdSource,        // provenance — never a hardcoded constant (scar #8)
    decimal DaysCovered,
    decimal DaysCoveredIfSolMinus30Pct);        // the exposure, in the unit that matters

// Default mitigation (JOSHI.md §9.5), the boring one: a SCHEDULED USDC conversion sized
// to ~30 days of obligations, executed as ordinary orders through the pipeline. The buffer
// is what makes "the book is never dismantled for the calendar" survivable.
```

---

## 10. WALLET — five wallets, two live keys, roles as types

The desk is not one wallet. It runs **five** (trading "shitcoims", LP "tha funds", the
pumpfun_main lineage, and their kin — `RESULT_position_history.md` reconstructed all five),
with **at least two live keys** (`~/.shitcoims-wallet` trading, `~/.thafunds-wallet` LP).
v1's signer machinery was single-key by silent assumption; v2 makes the wallet a domain
object and the assumption a field:

```csharp
public readonly record struct WalletId(string Address);

public sealed record Wallet(
    WalletId Id,
    string Label,                       // "shitcoims", "tha funds", …
    WalletRole Role,                    // Trading | Lp | FeeVault | Escrow | Legacy
    KeyCustody Custody,                 // LiveKey(path, box) | WatchOnly — most of the five
                                        //   are watch-only; the reconciler tracks ALL of them
    AllowlistRef Allowlist);            // PER-WALLET: the LP key's list has no swap
                                        //   discriminator, the trading key's no DLMM ixs —
                                        //   a key can only do its role's job

public abstract record KeyCustody
{
    public sealed record LiveKey(string KeyfilePath, string Box) : KeyCustody;  // Box: "mac"
    public sealed record WatchOnly : KeyCustody;    // reconciled, never signed for
}
```

Consequences elsewhere in the model: every `Plan` names its `WalletId` (§4) and validates
against that wallet's allowlist; `joshi-signer` keeps **one spool stream per key**
(`signer/<key>`), so a signed-send on either key survives a link drop independently; the
Book projection is per-wallet subledgers aggregated, never a blind sum; and the reconciler
(design/reconciler.md) watches all five addresses and their token accounts — the
watch-only wallets are where labeling errors hid last time.

---

## 11. ATTESTATION — the operator's labels, kept apart from measurement

```csharp
public sealed record Attestation(
    Ulid Id,
    AttestationSubject Subject,        // Address | Mint | Entity | BasisOf(LotId)
    string Label,                      // "mine", "scammer", "payee: X", …
    Probability Confidence,
    Instant At);
```

HANDOFF's lesson verbatim: *the operator holds labels no instrument can produce* — make
attaching one cheap (a glass gesture), record confidence beside it, and keep measured and
attested in different columns that are never summed. The attested address book is also the
**only** source of transfer destinations (address-poisoning scar).

---

## 12. What is deliberately NOT in the domain model

- **Quote** is not a domain object — it is transient plan input, and keeping it out of the
  model is load-bearing (see §5).
- **Wallet-graph entities** — research-side until an estimator survives its nulls at real n.
- **Payments to people** — observed by the reconciler as transfers with attestations, but
  there is no Payment command: paying humans stays in wallet software, by hand, forever.
- **Strategy PnL as a stored number** — PnL is always a projection over reconciled fills;
  a stored PnL field is a cache that will one day disagree with the ledger and win.
