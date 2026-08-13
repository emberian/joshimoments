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
-/

import Joshi.Fill

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

/-- A proposed action, carrying the pool state it would execute against. -/
structure Action where
  spendLamports : Nat
  poolSolLamports : Nat
deriving Repr

/-- What the desk currently has at risk, and what it has already lost today. -/
structure DeskState where
  exposureLamports : Nat
  realisedLossLamports : Nat := 0
deriving Repr

/-- The gate. Every clause is a reason a real trade has gone wrong on this desk. -/
def admits (l : Limits) (s : DeskState) (a : Action) : Bool :=
  decide (a.spendLamports ≤ l.maxTradeLamports)
    && decide (s.exposureLamports + a.spendLamports ≤ l.maxExposureLamports)
    && decide (a.spendLamports * l.poolFracDenom ≤ l.poolFracNumer * a.poolSolLamports)
    && decide (s.realisedLossLamports ≤ l.dailyLossBudget)

/-- State after an admitted action. Losses are recorded elsewhere and only read here. -/
def DeskState.apply (s : DeskState) (a : Action) : DeskState :=
  { s with exposureLamports := s.exposureLamports + a.spendLamports }

/-- Drive a whole sequence of proposals through the gate, admitting only what passes.

A learner is, extensionally, a thing that emits such a sequence. Proving a property of `run`
for every list is therefore proving it for every learner. -/
def run (l : Limits) (s : DeskState) : List Action → DeskState
  | [] => s
  | a :: rest => if admits l s a then run l (s.apply a) rest else run l s rest

theorem admits_exposure {l : Limits} {s : DeskState} {a : Action}
    (h : admits l s a = true) :
    s.exposureLamports + a.spendLamports ≤ l.maxExposureLamports := by
  unfold admits at h
  simp only [Bool.and_eq_true, decide_eq_true_eq] at h
  exact h.1.1.2

theorem admits_trade_size {l : Limits} {s : DeskState} {a : Action}
    (h : admits l s a = true) : a.spendLamports ≤ l.maxTradeLamports := by
  unfold admits at h
  simp only [Bool.and_eq_true, decide_eq_true_eq] at h
  exact h.1.1.1

/-- The impact cap, in the form the fill semantics can consume. -/
theorem admits_pool_fraction {l : Limits} {s : DeskState} {a : Action}
    (h : admits l s a = true) :
    a.spendLamports * l.poolFracDenom ≤ l.poolFracNumer * a.poolSolLamports := by
  unfold admits at h
  simp only [Bool.and_eq_true, decide_eq_true_eq] at h
  exact h.1.2

/-- **No sequence of proposals, from any learner, can exceed the exposure cap.**

The guarantee the whole proposer/gate split exists for. Note what it does *not* assume:
nothing about how actions are chosen, nothing about their number, nothing about the learner
being well-behaved, sane, or even trying to respect the limits. A learner that proposes the
entire book into one coin on every step is covered, because the gate simply never admits it.

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
      exact ih (s.apply a) (by
        show s.exposureLamports + a.spendLamports ≤ l.maxExposureLamports
        exact admits_exposure hadm)
    · simp only [hadm]
      exact ih s h

/-- Exposure only ever moves in one direction under `run`, so the cap is not maintained by
some cancelling pair of effects. Stated because a bound that holds only at the end would be
a weaker claim than it looks. -/
theorem exposure_monotone (l : Limits) :
    ∀ (as : List Action) (s : DeskState),
      s.exposureLamports ≤ (run l s as).exposureLamports := by
  intro as
  induction as with
  | nil => intro s; simp [run]
  | cons a rest ih =>
    intro s
    unfold run
    by_cases hadm : admits l s a
    · simp only [hadm, if_true]
      exact Nat.le_trans (Nat.le_add_right _ _) (ih (s.apply a))
    · simp only [hadm]
      exact ih s

/-- An admitted action never spends more than the pool's whole SOL side.

The join with `Fill.lean`. Because AMM impact is a deterministic function of reserves, a
fraction cap enforced at admission time is a real bound on execution cost rather than a hope
about liquidity — which is the best an equities venue can offer. Concretely: with the cap set
at or below 1, cross-multiplication and cancellation of the (positive) denominator give a
spend bounded by the pool itself, which is what stops a single admitted fill from crossing
the whole curve.

Every hypothesis is load-bearing here: drop `h` and there is no fraction bound to cancel,
drop `hfrac` and the cap could exceed the pool. -/
theorem admitted_spend_within_pool (l : Limits) (s : DeskState) (a : Action)
    (h : admits l s a = true) (hfrac : l.poolFracNumer ≤ l.poolFracDenom) :
    a.spendLamports ≤ a.poolSolLamports := by
  have hp := admits_pool_fraction h
  have h2 : l.poolFracNumer * a.poolSolLamports ≤ l.poolFracDenom * a.poolSolLamports :=
    Nat.mul_le_mul_right _ hfrac
  have h3 : a.spendLamports * l.poolFracDenom ≤ l.poolFracDenom * a.poolSolLamports :=
    Nat.le_trans hp h2
  rw [Nat.mul_comm a.spendLamports] at h3
  exact Nat.le_of_mul_le_mul_left h3 l.denom_pos

/-- The daily-loss clause, extracted. -/
theorem admits_within_loss_budget {l : Limits} {s : DeskState} {a : Action}
    (h : admits l s a = true) : s.realisedLossLamports ≤ l.dailyLossBudget := by
  unfold admits at h
  simp only [Bool.and_eq_true, decide_eq_true_eq] at h
  exact h.2

/-- **A tripped breaker admits nothing, from anyone.** -/
theorem tripped_breaker_admits_nothing (l : Limits) (s : DeskState)
    (h : l.dailyLossBudget < s.realisedLossLamports) (a : Action) :
    admits l s a = false := by
  unfold admits
  have hnot : ¬ (s.realisedLossLamports ≤ l.dailyLossBudget) := Nat.not_le.mpr h
  simp [hnot]

/-- **And it stays tripped: once the budget is blown, `run` is the identity.**

A circuit breaker that can be talked back open is not a circuit breaker. Because `apply`
only ever touches exposure, the loss field is invariant across the whole run, so no admitted
action can lower it back under the budget — and by the previous theorem no action is admitted
anyway. The conclusion is the strongest available form: the desk state is left *literally
unchanged* by every remaining proposal, for any learner and any sequence length.

This is what lets a loss budget be an actual stop rather than a number on a dashboard. -/
theorem tripped_breaker_is_absorbing (l : Limits) :
    ∀ (as : List Action) (s : DeskState),
      l.dailyLossBudget < s.realisedLossLamports → run l s as = s := by
  intro as
  induction as with
  | nil => intro s _; rfl
  | cons a rest ih =>
    intro s h
    unfold run
    rw [tripped_breaker_admits_nothing l s h a]
    simpa using ih s h

end Joshi
