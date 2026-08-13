/-
Interface #6 of the Phase 0 manifest: the policy envelope.

The architecture this exists to support: an online learner proposes arbitrary actions — that
is the point of exploration, and a learner that only proposes safe-looking trades is not
exploring — and a small, verified gate decides which are admitted. It is the same pattern the
sentinel already uses on Jupiter, whose returned transaction is treated as adversarial and
re-validated locally before signing, lifted one level up: **our own learner is an untrusted
proposer behind a checked gate.**

That framing is what makes the guarantee worth proving. A statement about a particular
learner is worth little, because the learner is precisely the component we do not fully
understand and intend to keep changing. `exposure_bounded` below is quantified over every
finite sequence of proposed actions, so it holds for any learner anyone writes, now or later,
including one that proposes putting the whole book into a single coin to see what happens.

The limits themselves are ordinary and deliberately few. Everything here is `Nat` lamports;
the pool-fraction cap is a rational compared by cross-multiplication so no float enters.

──────────────────────────────────────────────────────────────────────────────────────────
THE DESK CAN NOW SELL. What changed, and why it had to.

The previous version modelled an action as a spend and nothing else, with

    DeskState.apply s a = { s with exposureLamports := s.exposureLamports + a.spendLamports }

so exposure was a ratchet: every admitted action raised it and nothing ever lowered it. The
old `exposure_bounded` was sound, but it was sound about a desk that buys until it reaches
`maxExposureLamports` and then never trades again — and it could not express selling at all,
which is this desk's primary action (the live bot is sell-only). A cap that is only ever
approached is not a risk limit, it is a countdown.

An `Action` is now an **entry** (commit lamports to a mint) or a **release** (take lamports of
risk back out of an open position), and exposure is derived from a book of open positions
(`Joshi/Release.lean`) rather than stored as a running total. The four consequences worth
naming up front, each proved below:

* `exposure_bounded` survives *verbatim* — same statement, same universal quantification over
  every action sequence, now with a release branch that has to be shown harmless.
* `exposure_monotone` is **false** under this model and has been replaced, not deleted. See
  the note above `run_exposure_conserved`.
* `capacity_recoverable` is the new property the change exists for, and is exactly what the
  old model could not state: the desk can always wind down and enter again.
* The daily-loss breaker no longer blocks exits. See the note above
  `tripped_breaker_admits_no_entry`; that is a deliberate semantic change and the old
  absorbing theorem is preserved in the form that is still true.
-/

import Joshi.Fill
import Joshi.Release

namespace Joshi

/-- What the desk is allowed to do. Small on purpose: this is the trusted surface. -/
structure Limits where
  maxTradeLamports : Nat
  maxExposureLamports : Nat
  /-- Impact cap as `numer/denom` of the pool's SOL side. Compared by cross-multiplication. -/
  poolFracNumer : Nat
  poolFracDenom : Nat
  denom_pos : 0 < poolFracDenom
  /-- Realised loss the desk may absorb before it stops trading for the day. -/
  dailyLossBudget : Nat

/-- A proposed action: take risk on, or take risk off.

⚠ `poolSolLamports` is SUPPLIED BY THE PROPOSER, and the gate's liquidity clause reads it. A
learner that self-reports a 10,000 SOL pool it is really about to move 1 SOL of passes the
fraction cap trivially — demonstrated by adversarial audit. Nothing in this file binds it to a
`Reserves`. Until a caller checks it against observed reserves BEFORE calling `admits`, the
impact cap is advisory and only the trade-size, exposure, book and loss clauses are
adversarial.

`release` carries no pool figure, and that is deliberate: see the liquidity paragraph on
`admits`. -/
inductive Action where
  /-- Commit `spendLamports` to `mint`, against a proposer-reported pool of `poolSolLamports`. -/
  | entry (mint spendLamports poolSolLamports : Nat)
  /-- Take `releaseLamports` of risk back out of the open position in `mint`. -/
  | release (mint releaseLamports : Nat)
deriving Repr

/-- Lamports of new risk the action commits: zero for a release. -/
def Action.entrySpend : Action → Nat
  | .entry _ spend _ => spend
  | .release _ _ => 0

/-- Lamports of risk the action takes back off: zero for an entry. -/
def Action.releaseAmount : Action → Nat
  | .entry _ _ _ => 0
  | .release _ amount => amount

/-- Which side of the book the action is on. -/
def Action.isEntry : Action → Bool
  | .entry _ _ _ => true
  | .release _ _ => false

/-- What the desk currently holds, and what it has already lost today.

Exposure is *not* a field. It is `bookTotal s.book`, so a desk whose recorded exposure
disagrees with the positions it holds is not a state this type can represent. -/
structure DeskState where
  book : List OpenPosition
  realisedLossLamports : Nat := 0
deriving Repr

/-- Total lamports the desk has at risk right now. Derived, never stored. -/
def DeskState.exposureLamports (s : DeskState) : Nat := bookTotal s.book

/-- Whether a release is legal against the book: the position must be open, and the release
must not exceed it. This is the clause that keeps `Nat` subtraction honest — see the header of
`Joshi/Release.lean` for why the kernel stays in `Nat` rather than moving to `Int`. -/
def releasable (s : DeskState) (mint amount : Nat) : Bool :=
  match bookFind? mint s.book with
  | none => false
  | some p => decide (amount ≤ p.costLamports)

/-- The gate. Every clause is a reason a real trade has gone wrong on this desk.

**Entries** must name a mint the desk is not already in (concurrent positions in one mint are
one bet wearing two hats — the live shadow book refuses them for the same reason), fit the
trade-size cap, fit under the exposure cap, respect the impact cap, and be inside the day's
loss budget.

**Releases are gated on the book alone**, and this asymmetry is the design. Every other clause
exists to refuse *taking on* risk; refusing to let the desk *reduce* risk is never safety, and
a gate that can trap the desk in a position is a worse failure than any it prevents. So the
loss breaker does not apply (a stopped-out desk must still be able to get flat), and neither
does the exposure cap (a release cannot breach a ceiling it moves away from). Liquidity on the
exit is not skipped, it is enforced somewhere better: `Fill.accepts` checks the payout against
*observed* reserves before signing, rather than against the proposer-reported number this file
is stuck with. -/
def admits (l : Limits) (s : DeskState) (a : Action) : Bool :=
  match a with
  | .entry mint spend pool =>
      (bookFind? mint s.book).isNone
        && decide (spend ≤ l.maxTradeLamports)
        && decide (s.exposureLamports + spend ≤ l.maxExposureLamports)
        && decide (spend * l.poolFracDenom ≤ l.poolFracNumer * pool)
        && decide (s.realisedLossLamports ≤ l.dailyLossBudget)
  | .release mint amount => releasable s mint amount

/-- State after an admitted action. Losses are recorded elsewhere and only read here. -/
def DeskState.apply (s : DeskState) (a : Action) : DeskState :=
  match a with
  | .entry mint spend _ => { s with book := ⟨mint, spend⟩ :: s.book }
  | .release mint amount => { s with book := bookRelease mint amount s.book }

/-- Drive a whole sequence of proposals through the gate, admitting only what passes.

A learner is, extensionally, a thing that emits such a sequence. Proving a property of `run`
for every list is therefore proving it for every learner. -/
def run (l : Limits) (s : DeskState) : List Action → DeskState
  | [] => s
  | a :: rest => if admits l s a then run l (s.apply a) rest else run l s rest

/-! ### Reading the gate back out -/

/-- Everything the gate checked before admitting an entry. -/
theorem admits_entry {l : Limits} {s : DeskState} {mint spend pool : Nat}
    (h : admits l s (.entry mint spend pool) = true) :
    (bookFind? mint s.book).isNone = true
      ∧ spend ≤ l.maxTradeLamports
      ∧ s.exposureLamports + spend ≤ l.maxExposureLamports
      ∧ spend * l.poolFracDenom ≤ l.poolFracNumer * pool
      ∧ s.realisedLossLamports ≤ l.dailyLossBudget := by
  simp only [admits, Bool.and_eq_true, decide_eq_true_eq] at h
  exact ⟨h.1.1.1.1, h.1.1.1.2, h.1.1.2, h.1.2, h.2⟩

theorem admits_trade_size {l : Limits} {s : DeskState} {mint spend pool : Nat}
    (h : admits l s (.entry mint spend pool) = true) : spend ≤ l.maxTradeLamports :=
  (admits_entry h).2.1

theorem admits_exposure {l : Limits} {s : DeskState} {mint spend pool : Nat}
    (h : admits l s (.entry mint spend pool) = true) :
    s.exposureLamports + spend ≤ l.maxExposureLamports :=
  (admits_entry h).2.2.1

/-- The impact cap, in the form the fill semantics can consume. -/
theorem admits_pool_fraction {l : Limits} {s : DeskState} {mint spend pool : Nat}
    (h : admits l s (.entry mint spend pool) = true) :
    spend * l.poolFracDenom ≤ l.poolFracNumer * pool :=
  (admits_entry h).2.2.2.1

/-- The daily-loss clause, extracted. Entries only, by design — see `admits`. -/
theorem admits_within_loss_budget {l : Limits} {s : DeskState} {mint spend pool : Nat}
    (h : admits l s (.entry mint spend pool) = true) :
    s.realisedLossLamports ≤ l.dailyLossBudget :=
  (admits_entry h).2.2.2.2

/-- **An admitted release names a position that is open, and does not exceed it.**

The hypothesis the `Nat` subtraction needs. Everything downstream that touches the book's
arithmetic goes through this. -/
theorem admits_release {l : Limits} {s : DeskState} {mint amount : Nat}
    (h : admits l s (.release mint amount) = true) :
    ∃ p, bookFind? mint s.book = some p ∧ amount ≤ p.costLamports := by
  simp only [admits, releasable] at h
  revert h
  cases hf : bookFind? mint s.book with
  | none => intro h; exact absurd h (by simp)
  | some p => intro h; exact ⟨p, rfl, by simpa using h⟩

/-! ### Illegal actions are rejected, not silently mis-computed

Requirement: a release against a position that is not open, or one larger than the position,
must be refused by the gate rather than falling through to truncated arithmetic that would
report a book the desk does not have. -/

/-- **You cannot release a position you do not hold.** -/
theorem release_of_unopened_rejected (l : Limits) (s : DeskState) (mint amount : Nat)
    (h : bookFind? mint s.book = none) : admits l s (.release mint amount) = false := by
  simp only [admits, releasable, h]

/-- **You cannot release more than the position holds.**

Without this clause `bookRelease` would truncate and the desk would report having released
more capital than it ever committed. -/
theorem release_oversize_rejected (l : Limits) (s : DeskState) (mint amount : Nat)
    {p : OpenPosition} (h : bookFind? mint s.book = some p) (hbig : p.costLamports < amount) :
    admits l s (.release mint amount) = false := by
  simp only [admits, releasable, h, decide_eq_false_iff_not]
  exact Nat.not_le.mpr hbig

/-- **You cannot stack a second position on a mint you are already in.**

Keeps the book a genuine map from mint to position, which is what makes "the position in this
mint" a well-defined thing for a release to name. -/
theorem entry_duplicate_mint_rejected (l : Limits) (s : DeskState) (mint spend pool : Nat)
    {p : OpenPosition} (h : bookFind? mint s.book = some p) :
    admits l s (.entry mint spend pool) = false := by
  simp [admits, h]

/-- **And that clause is an invariant, not a spot check: no learner can break the map.**

`entry_duplicate_mint_rejected` says the gate refuses one duplicate. This says the consequence
holds along every run: start with a book that is a genuine map from mint to position and it
stays one, under any sequence of proposals from anyone. That is what makes "the position in
this mint" — the thing a release names, and the thing `bookFind?` resolves to the *first*
match — well defined at every point at which a release can be proposed. -/
theorem run_preserves_book_map (l : Limits) :
    ∀ (as : List Action) (s : DeskState),
      bookNoDup s.book = true → bookNoDup (run l s as).book = true := by
  intro as
  induction as with
  | nil => intro s h; simpa [run] using h
  | cons a rest ih =>
    intro s hnd
    unfold run
    by_cases hadm : admits l s a
    · simp only [hadm, if_true]
      refine ih (s.apply a) ?_
      cases a with
      | entry mint spend pool =>
        have hfresh := (admits_entry hadm).1
        show bookNoDup (⟨mint, spend⟩ :: s.book) = true
        exact bookNoDup_cons (by simpa using hfresh) hnd
      | release mint amount =>
        show bookNoDup (bookRelease mint amount s.book) = true
        exact bookNoDup_bookRelease mint amount s.book hnd
    · simp only [hadm]
      exact ih s hnd

/-! ### One step of the book -/

@[simp] theorem apply_loss (s : DeskState) (a : Action) :
    (s.apply a).realisedLossLamports = s.realisedLossLamports := by
  cases a <;> rfl

@[simp] theorem apply_entry_exposure (s : DeskState) (mint spend pool : Nat) :
    (s.apply (.entry mint spend pool)).exposureLamports = spend + s.exposureLamports := rfl

/-- A release never raises exposure — unconditionally, gate or no gate. -/
theorem apply_release_exposure_le (s : DeskState) (mint amount : Nat) :
    (s.apply (.release mint amount)).exposureLamports ≤ s.exposureLamports :=
  bookTotal_bookRelease_le mint amount s.book

/-- **The truncation discharge, at desk level: an admitted release moves exactly its amount.**

Additive form (`after + amount = before`), never `after = before - amount`, because the
subtractive form stays true when `Nat` truncates and so would prove nothing. -/
theorem admitted_release_exact {l : Limits} {s : DeskState} {mint amount : Nat}
    (h : admits l s (.release mint amount) = true) :
    (s.apply (.release mint amount)).exposureLamports + amount = s.exposureLamports := by
  obtain ⟨p, hf, hle⟩ := admits_release h
  show bookTotal (bookRelease mint amount s.book) + amount = bookTotal s.book
  exact bookTotal_bookRelease_exact s.book hf hle

/-- Exposure after any admitted step is exactly exposure before, plus what was entered, minus
what was released. The single-step core of `run_exposure_conserved`. -/
theorem apply_exposure_step {l : Limits} {s : DeskState} {a : Action}
    (h : admits l s a = true) :
    (s.apply a).exposureLamports + a.releaseAmount
      = s.exposureLamports + a.entrySpend := by
  cases a with
  | entry mint spend pool =>
    simp only [apply_entry_exposure, Action.releaseAmount, Action.entrySpend]
    omega
  | release mint amount =>
    have := admitted_release_exact h
    simp only [Action.releaseAmount, Action.entrySpend]
    omega

/-! ### The guarantee -/

/-- **No sequence of proposals, from any learner, can exceed the exposure cap.**

The guarantee the whole proposer/gate split exists for, and its statement is unchanged from
the ratchet model: nothing about how actions are chosen, nothing about their number, nothing
about the learner being well-behaved, sane, or even trying to respect the limits. A learner
that proposes the entire book into one coin on every step is covered, because the gate simply
never admits it.

What is new is that it now has to survive a desk that *moves in both directions*. The entry
branch is the gate's exposure clause as before; the release branch holds because
`apply_release_exposure_le` is unconditional, so no interleaving of exits and re-entries can
walk the desk over the cap.

This is the property that makes it safe to let a model-free method generate arbitrary trades. -/
theorem exposure_bounded (l : Limits) :
    ∀ (as : List Action) (s : DeskState),
      s.exposureLamports ≤ l.maxExposureLamports →
      (run l s as).exposureLamports ≤ l.maxExposureLamports := by
  intro as
  induction as with
  | nil => intro s h; simpa [run] using h
  | cons a rest ih =>
    intro s h
    unfold run
    by_cases hadm : admits l s a
    · simp only [hadm, if_true]
      refine ih (s.apply a) ?_
      cases a with
      | entry mint spend pool =>
        have hcap := admits_exposure hadm
        simp only [apply_entry_exposure]
        omega
      | release mint amount =>
        exact Nat.le_trans (apply_release_exposure_le s mint amount) h
    · simp only [hadm]
      exact ih s h

/-- Lamports of new risk `run` actually admitted, in order. -/
def entered (l : Limits) (s : DeskState) : List Action → Nat
  | [] => 0
  | a :: rest =>
      if admits l s a then a.entrySpend + entered l (s.apply a) rest else entered l s rest

/-- Lamports of risk `run` actually released, in order. -/
def released (l : Limits) (s : DeskState) : List Action → Nat
  | [] => 0
  | a :: rest =>
      if admits l s a then a.releaseAmount + released l (s.apply a) rest else released l s rest

/-- **Exposure is conserved: it moves by exactly the flows the gate admitted, and by nothing
else.**

⚠ THIS REPLACES `exposure_monotone`, which said `s.exposureLamports ≤ (run l s as).exposure‑
Lamports` — exposure only ever grows under `run`. That statement is now **false**, and it is
false *on purpose*: a desk that can sell is a desk whose exposure comes back down, and the
whole point of this rewrite was to stop modelling that as impossible. Deleting it silently
would have been the wrong move too, because it was carrying a real claim: that the cap is not
maintained by some cancelling pair of effects, and that exposure does not drift on its own.

Conservation is the right statement of that claim, and it is strictly stronger than the
monotonicity it replaces. Every lamport of exposure at the end is accounted for: it was there
at the start, or it came in through an admitted entry, and it left only through an admitted
release. No path exists by which exposure appears from nowhere, and — the failure mode
monotonicity was really guarding against — none by which the gate lets a book be silently
zeroed. Rejected proposals contribute nothing to either side.

The original monotone statement survives exactly where it is still true, as
`exposure_monotone_of_entries` below. -/
theorem run_exposure_conserved (l : Limits) :
    ∀ (as : List Action) (s : DeskState),
      (run l s as).exposureLamports + released l s as
        = s.exposureLamports + entered l s as := by
  intro as
  induction as with
  | nil => intro s; simp [run, entered, released]
  | cons a rest ih =>
    intro s
    unfold run entered released
    by_cases hadm : admits l s a
    · simp only [hadm, if_true]
      have hstep := apply_exposure_step hadm
      have hrec := ih (s.apply a)
      omega
    · simp only [hadm]
      exact ih s

/-- The old `exposure_monotone`, verbatim, on the sequences where it is still true: a run of
nothing but entries can only raise exposure. Kept so the claim the previous model made is
visibly preserved rather than quietly dropped. -/
theorem exposure_monotone_of_entries (l : Limits) :
    ∀ (as : List Action) (s : DeskState),
      (∀ a ∈ as, a.isEntry = true) →
      s.exposureLamports ≤ (run l s as).exposureLamports := by
  intro as
  induction as with
  | nil => intro s _; simp [run]
  | cons a rest ih =>
    intro s hall
    have hrest : ∀ b ∈ rest, b.isEntry = true := fun b hb => hall b (by simp [hb])
    have ha : a.isEntry = true := hall a (by simp)
    unfold run
    by_cases hadm : admits l s a
    · simp only [hadm, if_true]
      cases a with
      | entry mint spend pool =>
        refine Nat.le_trans ?_ (ih (s.apply (.entry mint spend pool)) hrest)
        simp only [apply_entry_exposure]
        omega
      | release mint amount => simp [Action.isEntry] at ha
    · simp only [hadm]
      exact ih s hrest

/-! ### Capacity is recoverable

The properties the extension exists for. Under the ratchet model every one of these was either
false or unstatable: a desk at its cap had no continuation that let it trade again. -/

/-- **A release of a positive amount strictly reduces exposure.**

The `0 < amount` hypothesis is doing real work: a zero release is admitted (it is legal
against any open position) and leaves the book alone, so the strict inequality genuinely needs
it. -/
theorem release_strictly_reduces {l : Limits} {s : DeskState} {mint amount : Nat}
    (h : admits l s (.release mint amount) = true) (hpos : 0 < amount) :
    (s.apply (.release mint amount)).exposureLamports < s.exposureLamports := by
  have := admitted_release_exact h
  omega

/-- The sequence of releases that closes every open position, in book order. -/
def exitPlan : List OpenPosition → List Action
  | [] => []
  | p :: rest => .release p.mint p.costLamports :: exitPlan rest

theorem exitPlan_no_entries : ∀ (b : List OpenPosition), ∀ a ∈ exitPlan b, a.isEntry = false := by
  intro b
  induction b with
  | nil => intro a ha; simp [exitPlan] at ha
  | cons p rest ih =>
    intro a ha
    rcases List.mem_cons.mp ha with h | h
    · subst h; rfl
    · exact ih a h

/-- **The wind-down always runs: every action in the exit plan is admitted, and the book ends
empty.**

Note this is an equation, not a bound: the desk lands in exactly the flat state, with its
realised-loss ledger untouched. -/
theorem run_exitPlan (l : Limits) :
    ∀ (b : List OpenPosition) (s : DeskState), s.book = b →
      run l s (exitPlan b) = { s with book := [] } := by
  intro b
  induction b with
  | nil =>
    intro s hb
    cases s with
    | mk book loss => subst hb; rfl
  | cons p rest ih =>
    intro s hb
    have hadm : admits l s (.release p.mint p.costLamports) = true := by
      simp only [admits, releasable, hb, bookFind?_cons_self, decide_eq_true_eq]
      exact Nat.le_refl _
    have hbook : (s.apply (.release p.mint p.costLamports)).book = rest := by
      show bookRelease p.mint p.costLamports s.book = rest
      rw [hb, bookRelease_head]
    have hrec := ih (s.apply (.release p.mint p.costLamports)) hbook
    unfold exitPlan run
    simp only [hadm, if_true, hrec]
    cases s with
    | mk book loss => rfl

/-- A desk that is flat admits any entry that fits its limits. -/
theorem empty_book_admits_entry (l : Limits) (s : DeskState) (mint spend pool : Nat)
    (hbook : s.book = [])
    (hsize : spend ≤ l.maxTradeLamports)
    (hcap : spend ≤ l.maxExposureLamports)
    (hpool : spend * l.poolFracDenom ≤ l.poolFracNumer * pool)
    (hloss : s.realisedLossLamports ≤ l.dailyLossBudget) :
    admits l s (.entry mint spend pool) = true := by
  have hexp : s.exposureLamports = 0 := by
    show bookTotal s.book = 0
    rw [hbook]; rfl
  simp only [admits, hbook, bookFind?_nil, Option.isNone_none, hexp, Nat.zero_add,
    Bool.and_eq_true, decide_eq_true_eq, true_and]
  exact ⟨⟨⟨hsize, hcap⟩, hpool⟩, hloss⟩

/-- **Capacity is genuinely recoverable: from ANY state, the desk can get flat and enter again.**

This is the theorem the rewrite exists to make true. In the ratchet model it was false in the
sharpest possible way — for a desk sitting at `maxExposureLamports` there was no sequence of
actions at all, from any learner, after which a further entry could be admitted, because no
action could lower exposure. The desk was done trading, permanently, and the model could not
say so.

The witness is not an assumption about the learner: `exitPlan` is constructed from the book
the desk actually holds, every one of its actions is admitted by `run_exitPlan`, and it
contains no entries (`exitPlan_no_entries`), so the desk winds down without taking on any new
risk on the way. The hypotheses are only that the entry fits the standing limits — with none
about current exposure, which is precisely what has been recovered. -/
theorem capacity_recoverable (l : Limits) (s : DeskState) (mint spend pool : Nat)
    (hsize : spend ≤ l.maxTradeLamports)
    (hcap : spend ≤ l.maxExposureLamports)
    (hpool : spend * l.poolFracDenom ≤ l.poolFracNumer * pool)
    (hloss : s.realisedLossLamports ≤ l.dailyLossBudget) :
    ∃ as : List Action,
      (∀ a ∈ as, a.isEntry = false)
      ∧ (run l s as).exposureLamports = 0
      ∧ admits l (run l s as) (.entry mint spend pool) = true := by
  refine ⟨exitPlan s.book, exitPlan_no_entries s.book, ?_, ?_⟩
  · rw [run_exitPlan l s.book s rfl]; rfl
  · rw [run_exitPlan l s.book s rfl]
    exact empty_book_admits_entry l _ mint spend pool rfl hsize hcap hpool hloss

/-- **Rejected before, admitted after: one release is enough to reopen the door.**

The local form of recoverability, and the one that shows the exposure clause is what moved. An
entry that clears every other clause but does not fit under the cap is refused; release enough
capacity and the identical entry is admitted. Both halves are stated, because the "admitted
after" half alone would be consistent with a gate that admitted it all along. -/
theorem release_restores_capacity (l : Limits) (s : DeskState)
    {rmint ramt emint espend epool : Nat}
    (hrel : admits l s (.release rmint ramt) = true)
    (hfresh : (bookFind? emint (s.apply (.release rmint ramt)).book).isNone = true)
    (hsize : espend ≤ l.maxTradeLamports)
    (hpool : espend * l.poolFracDenom ≤ l.poolFracNumer * epool)
    (hloss : s.realisedLossLamports ≤ l.dailyLossBudget)
    (hblocked : l.maxExposureLamports < s.exposureLamports + espend)
    (hfits : s.exposureLamports + espend ≤ l.maxExposureLamports + ramt) :
    admits l s (.entry emint espend epool) = false
      ∧ admits l (s.apply (.release rmint ramt)) (.entry emint espend epool) = true := by
  have hexact := admitted_release_exact hrel
  constructor
  · simp only [admits, Bool.and_eq_false_iff, decide_eq_false_iff_not]
    exact Or.inl (Or.inl (Or.inr (Nat.not_le.mpr hblocked)))
  · have hcapAfter :
        (s.apply (.release rmint ramt)).exposureLamports + espend ≤ l.maxExposureLamports := by
      omega
    simp only [admits, hfresh, apply_loss, Bool.and_eq_true, decide_eq_true_eq, true_and]
    exact ⟨⟨⟨hsize, hcapAfter⟩, hpool⟩, hloss⟩

/-! ### The daily-loss breaker -/

/-- **A tripped breaker admits no new risk, from anyone.**

⚠ THIS REPLACES `tripped_breaker_admits_nothing`, which said a tripped breaker admits *no
action whatsoever*. That was the right theorem about a desk that could only buy. It is the
wrong rule for a desk that can sell, and it would now be a dangerous one: a bot whose daily
loss budget is blown is a bot holding positions it has every reason to exit, and a gate that
refuses its sells has locked it into the bag it is losing money on. The clause the breaker
gates is the entry clause; `admits` refuses new risk and keeps the exit open. The live shadow
book already works this way — its breaker pauses `admits`, never `close`.

The safety content that would otherwise have been lost to that change is not lost; it is
`tripped_breaker_cannot_increase_exposure` below, which is the stronger statement anyway. -/
theorem tripped_breaker_admits_no_entry (l : Limits) (s : DeskState)
    (h : l.dailyLossBudget < s.realisedLossLamports) (mint spend pool : Nat) :
    admits l s (.entry mint spend pool) = false := by
  simp only [admits, Bool.and_eq_false_iff, decide_eq_false_iff_not]
  exact Or.inr (Nat.not_le.mpr h)

/-- Once tripped, the only proposals that get through are exits. -/
theorem tripped_breaker_admits_only_releases {l : Limits} {s : DeskState} {a : Action}
    (htrip : l.dailyLossBudget < s.realisedLossLamports) (h : admits l s a = true) :
    a.isEntry = false := by
  cases a with
  | entry mint spend pool =>
    rw [tripped_breaker_admits_no_entry l s htrip mint spend pool] at h
    exact absurd h (by simp)
  | release mint amount => rfl

/-- **And it stays tripped: once the budget is blown, the desk can only wind down.**

⚠ THIS REPLACES `tripped_breaker_is_absorbing` (`run l s as = s` once tripped), which is false
now that exits are admitted — and its falsity is the intended behaviour, not a regression. The
property that made the old theorem worth having was that a circuit breaker cannot be talked
back open: no admitted action can lower `realisedLossLamports` back under the budget, because
`apply` never touches it, so the breaker stays tripped for the whole remaining run. That is
still true and still proved here — it is why the induction goes through — and the conclusion
is now the strongest one that is actually desirable: for any learner and any sequence length,
a tripped desk's exposure never rises again. It can get flat; it cannot re-risk.

The old conclusion is preserved in the case where it still holds, as
`tripped_breaker_is_absorbing_on_entries`. -/
theorem tripped_breaker_cannot_increase_exposure (l : Limits) :
    ∀ (as : List Action) (s : DeskState),
      l.dailyLossBudget < s.realisedLossLamports →
      (run l s as).exposureLamports ≤ s.exposureLamports := by
  intro as
  induction as with
  | nil => intro s _; simp [run]
  | cons a rest ih =>
    intro s htrip
    unfold run
    by_cases hadm : admits l s a
    · simp only [hadm, if_true]
      cases a with
      | entry mint spend pool =>
        rw [tripped_breaker_admits_no_entry l s htrip mint spend pool] at hadm
        exact absurd hadm (by simp)
      | release mint amount =>
        have htrip' :
            l.dailyLossBudget < (s.apply (.release mint amount)).realisedLossLamports := by
          simpa using htrip
        exact Nat.le_trans (ih _ htrip') (apply_release_exposure_le s mint amount)
    · simp only [hadm]
      exact ih s htrip

/-- The old `tripped_breaker_is_absorbing`, verbatim, on the sequences where it still holds: a
tripped desk fed nothing but entries is left literally unchanged. -/
theorem tripped_breaker_is_absorbing_on_entries (l : Limits) :
    ∀ (as : List Action) (s : DeskState),
      l.dailyLossBudget < s.realisedLossLamports →
      (∀ a ∈ as, a.isEntry = true) →
      run l s as = s := by
  intro as
  induction as with
  | nil => intro s _ _; rfl
  | cons a rest ih =>
    intro s htrip hall
    have ha : a.isEntry = true := hall a (by simp)
    have hrest : ∀ b ∈ rest, b.isEntry = true := fun b hb => hall b (by simp [hb])
    unfold run
    cases a with
    | entry mint spend pool =>
      rw [tripped_breaker_admits_no_entry l s htrip mint spend pool]
      simpa using ih s htrip hrest
    | release mint amount => simp [Action.isEntry] at ha

/-- An admitted entry never spends more than the pool's whole SOL side.

Pure arithmetic over `Limits` and `Action`: with the cap at or below 1, cross-multiplication
and cancellation of the positive denominator bound the spend by the reported pool.

⚠ This was previously described as "the join with `Fill.lean`". It is not — it mentions no
`Reserves`, no `sellOut`, no `accepts`, and the `import Joshi.Fill` above is unused by it.
There is currently NO theorem connecting the envelope to the fill semantics, and the bound is
against the proposer-reported pool size (see `Action`). Both gaps are real and open, and the
release side of the book makes the second one sharper: `admits` deliberately delegates exit
liquidity to `Fill.accepts` without a proof that the delegation is honoured.

Every hypothesis is load-bearing here: drop `h` and there is no fraction bound to cancel,
drop `hfrac` and the cap could exceed the pool. -/
theorem admitted_spend_within_pool (l : Limits) (s : DeskState) (mint spend pool : Nat)
    (h : admits l s (.entry mint spend pool) = true)
    (hfrac : l.poolFracNumer ≤ l.poolFracDenom) : spend ≤ pool := by
  have hp := admits_pool_fraction h
  have h2 : l.poolFracNumer * pool ≤ l.poolFracDenom * pool :=
    Nat.mul_le_mul_right _ hfrac
  have h3 : spend * l.poolFracDenom ≤ l.poolFracDenom * pool := Nat.le_trans hp h2
  rw [Nat.mul_comm spend] at h3
  exact Nat.le_of_mul_le_mul_left h3 l.denom_pos

/-! ### Anti-vacuity witnesses

Every theorem above is quantified, and a quantified theorem whose hypotheses are unsatisfiable
proves nothing while compiling perfectly. What follows are concrete values that discharge the
hypotheses of the load-bearing statements, and concrete violations the gate is shown to
actually reject. They are `example`s, so they are checked on every build and export nothing.

The desk: 2 SOL max clip, 3 SOL max exposure, impact cap 1/100 of the pool, 0.5 SOL daily loss
budget. The state: exactly at the exposure cap, 2 SOL in mint 7 and 1 SOL in mint 9. -/

private def wLimits : Limits :=
  { maxTradeLamports := 2_000_000_000
    maxExposureLamports := 3_000_000_000
    poolFracNumer := 1
    poolFracDenom := 100
    denom_pos := by decide
    dailyLossBudget := 500_000_000 }

/-- 500 SOL of reported pool: deep enough that the impact cap binds on nothing below. -/
private def wPool : Nat := 500_000_000_000

private def wFull : DeskState :=
  { book := [⟨7, 2_000_000_000⟩, ⟨9, 1_000_000_000⟩], realisedLossLamports := 0 }

private def wRelease : Action := .release 7 2_000_000_000
private def wEntry : Action := .entry 11 1_000_000_000 wPool

-- The desk is at its cap, and a further 1 SOL entry is therefore refused.
example : wFull.exposureLamports = 3_000_000_000 := by decide
example : admits wLimits wFull wEntry = false := by decide

-- The release is admitted, and strictly reduces exposure. (Under the old ratchet model there
-- was no such action: this `= true` is the modelling gap being closed, in one line.)
example : admits wLimits wFull wRelease = true := by decide
example : (wFull.apply wRelease).exposureLamports = 1_000_000_000 := by decide

-- And now the identical entry that was refused above is admitted: capacity came back.
example : admits wLimits (wFull.apply wRelease) wEntry = true := by decide

/-- The hypotheses of `release_restores_capacity` are satisfiable — here is a witness for all
seven of them at once, and the theorem's conclusion instantiated at it. -/
example :
    admits wLimits wFull (.entry 11 1_000_000_000 wPool) = false
      ∧ admits wLimits (wFull.apply (.release 7 2_000_000_000))
          (.entry 11 1_000_000_000 wPool) = true := by
  refine release_restores_capacity wLimits wFull ?_ ?_ ?_ ?_ ?_ ?_ ?_ <;> decide

-- The gate really rejects, rather than mis-computing: releasing a mint the desk is not in,
-- releasing more than is open, and doubling up on an open mint are all refused.
example : admits wLimits wFull (.release 42 1) = false := by decide
example : admits wLimits wFull (.release 7 2_000_000_001) = false := by decide
example : admits wLimits wFull (.entry 7 1_000 wPool) = false := by decide

-- Were the oversize clause absent, `bookRelease` would truncate and hand the desk a free
-- 2 SOL of capacity it never released. The refused action is the one that would have done it:
-- 2.000000001 SOL out of a 2 SOL position.
example : bookTotal (bookRelease 7 2_000_000_001 wFull.book) = 1_000_000_000 := by decide

-- And the exact-arithmetic lemma on the branch where truncation would actually bite: a
-- PARTIAL release, which is the one that computes `costLamports - amount`.
example :
    bookTotal (bookRelease 7 500_000_000 wFull.book) + 500_000_000 = bookTotal wFull.book := by
  decide

example : (wFull.apply (.release 7 2_000_000_000)).exposureLamports < wFull.exposureLamports :=
  release_strictly_reduces (l := wLimits) (by decide) (by decide)

example : (1_000_000_000 : Nat) ≤ wPool :=
  admitted_spend_within_pool wLimits (wFull.apply wRelease) 11 1_000_000_000 wPool
    (by decide) (by decide)

/-- **`exposure_bounded` is not holding because nothing is ever admitted.**

The failure mode a universally quantified safety theorem invites: a gate that rejected
everything would satisfy it perfectly. Here is a four-proposal run — one entry refused for
breaching the cap, then a partial exit, then the *same* entry admitted, then a full exit —
where the book is genuinely churned, both flows are non-zero, and the desk still lands inside
the cap. It is also the conservation law with both sides loaded: 1.5 + 2.5 = 3.0 + 1.0 SOL. -/
private def wMixed : List Action :=
  [ .entry 11 1_000_000_000 wPool
  , .release 7 1_500_000_000
  , .entry 11 1_000_000_000 wPool
  , .release 9 1_000_000_000 ]

example : (run wLimits wFull wMixed).book = [⟨11, 1_000_000_000⟩, ⟨7, 500_000_000⟩] := by decide
example : bookNoDup wFull.book = true ∧ bookNoDup (run wLimits wFull wMixed).book = true := by
  decide
example : (run wLimits wFull wMixed).exposureLamports = 1_500_000_000 := by decide
example : entered wLimits wFull wMixed = 1_000_000_000 := by decide
example : released wLimits wFull wMixed = 2_500_000_000 := by decide

/-- A flat desk, for the entry-only witnesses. -/
private def wFlat : DeskState := { book := [], realisedLossLamports := 0 }

-- `exposure_monotone_of_entries` has a satisfiable hypothesis that is not the empty list, and
-- on it the conclusion is a real increase rather than the reflexive one.
example : ∀ a ∈ [Action.entry 1 1_000_000_000 wPool, Action.entry 2 1_000_000_000 wPool],
    a.isEntry = true := by decide
example :
    (run wLimits wFlat [Action.entry 1 1_000_000_000 wPool,
      Action.entry 2 1_000_000_000 wPool]).exposureLamports = 2_000_000_000 := by decide

example : admits wLimits wFlat (.entry 3 2_000_000_000 wPool) = true :=
  empty_book_admits_entry wLimits wFlat 3 2_000_000_000 wPool rfl
    (by decide) (by decide) (by decide) (by decide)

/-- A tripped desk: same book, 0.6 SOL of realised loss against a 0.5 SOL budget. -/
private def wTripped : DeskState :=
  { book := [⟨7, 2_000_000_000⟩, ⟨9, 1_000_000_000⟩], realisedLossLamports := 600_000_000 }

-- The breaker is tripped, entries are refused — and the exit stays open, which is the whole
-- point of the change to `tripped_breaker_admits_nothing`.
example : wLimits.dailyLossBudget < wTripped.realisedLossLamports := by decide
example : admits wLimits wTripped wEntry = false := by decide
example : admits wLimits wTripped wRelease = true := by decide

-- The wind-down plan for the full desk is two releases, and running it lands flat.
example : exitPlan wFull.book = [.release 7 2_000_000_000, .release 9 1_000_000_000] := by rfl
example : (run wLimits wFull (exitPlan wFull.book)).exposureLamports = 0 := by decide

-- Including from the tripped desk: `tripped_breaker_cannot_increase_exposure` is not bounding
-- a run in which nothing happens. The stopped-out desk can still get all the way flat.
example : (run wLimits wTripped (exitPlan wTripped.book)).exposureLamports = 0 := by decide

/-- `capacity_recoverable` instantiated at a desk that is at its cap: the entry hypotheses are
satisfiable, so the existential is not vacuous. -/
example :
    ∃ as : List Action,
      (∀ a ∈ as, a.isEntry = false)
      ∧ (run wLimits wFull as).exposureLamports = 0
      ∧ admits wLimits (run wLimits wFull as) (.entry 11 1_000_000_000 wPool) = true :=
  capacity_recoverable wLimits wFull 11 1_000_000_000 wPool
    (by decide) (by decide) (by decide) (by decide)

end Joshi
