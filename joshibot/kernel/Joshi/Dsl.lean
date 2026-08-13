/-
Interface #4 of the Phase 0 manifest: the strategy term algebra.

Two things this buys, and the second is the one that is hard to get any other way.

First, composition with the causal index: a term is evaluated against a `View t`, so every
strategy expressible in this DSL inherits the no-lookahead theorem from `History.lean`. You
cannot write a leaky strategy in it.

Second, and more unusual: **the trial count is computable.** Honest multiple-testing
correction needs N, the number of configurations actually searched, and in practice nobody
knows it — the deflated Sharpe ratio is routinely applied with N guessed, which is why one
audited implementation of it in this project's own reference material was simply invented
(`sr / ln(trials)`, a formula from no paper). Bailey, Borwein, Lopez de Prado and Zhu show
the stakes: after only ~7 independent configurations the expected best in-sample Sharpe of 1
corresponds to an out-of-sample Sharpe of zero, and five years of data supports about 45.

When the search space is a grammar, N is not estimated. It is the cardinality of the set of
terms of bounded depth, and `exprCount` / `predCount` below compute it exactly. A search that
enumerates this grammar can report its own N, so the correction stops being a hopeful guess.
-/

import Joshi.History

namespace Joshi

/-- Arithmetic over `n` named features. `Nat` throughout: these are lamports and raw units. -/
inductive Expr (n : Nat) where
  | lit (v : Nat)
  | feat (i : Fin n)
  | add (a b : Expr n)
  | sub (a b : Expr n)
deriving Repr

/-- Conditions. A strategy is a condition; the action it gates lives outside the grammar. -/
inductive Pred (n : Nat) where
  | le (a b : Expr n)
  | and (a b : Pred n)
  | neg (a : Pred n)
deriving Repr

namespace Expr

def eval {n : Nat} (φ : Fin n → Nat) : Expr n → Nat
  | .lit v => v
  | .feat i => φ i
  | .add a b => eval φ a + eval φ b
  | .sub a b => eval φ a - eval φ b

def depth {n : Nat} : Expr n → Nat
  | .lit _ => 0
  | .feat _ => 0
  | .add a b => 1 + max (depth a) (depth b)
  | .sub a b => 1 + max (depth a) (depth b)

end Expr

namespace Pred

def eval {n : Nat} (φ : Fin n → Nat) : Pred n → Bool
  | .le a b => decide (a.eval φ ≤ b.eval φ)
  | .and a b => eval φ a && eval φ b
  | .neg a => !eval φ a

def depth {n : Nat} : Pred n → Nat
  | .le a b => max a.depth b.depth
  | .and a b => 1 + max (depth a) (depth b)
  | .neg a => 1 + depth a

end Pred

/-- Number of distinct expressions of depth at most `d`, over `n` features and `lits`
admissible literals. Two binary constructors, hence the `2 * e * e`. -/
def exprCount (n lits : Nat) : Nat → Nat
  | 0 => lits + n
  | d + 1 => (lits + n) + 2 * exprCount n lits d * exprCount n lits d

/-- Number of distinct predicates of depth at most `d`. **This is N.** -/
def predCount (n lits : Nat) : Nat → Nat
  | 0 => exprCount n lits 0 * exprCount n lits 0
  | d + 1 =>
    exprCount n lits (d + 1) * exprCount n lits (d + 1)
      + predCount n lits d * predCount n lits d
      + predCount n lits d

/-- The search space only grows with depth — so a reported N is a floor, never an accident
of enumeration order. -/
theorem exprCount_mono (n lits d : Nat) :
    exprCount n lits d ≤ exprCount n lits (d + 1) := by
  simp only [exprCount]
  rcases Nat.eq_zero_or_pos (exprCount n lits d) with h | h
  · omega
  · have hsq : exprCount n lits d ≤ 2 * exprCount n lits d * exprCount n lits d := by
      calc exprCount n lits d
          = 1 * exprCount n lits d := (Nat.one_mul _).symm
        _ ≤ 2 * exprCount n lits d * exprCount n lits d :=
            Nat.mul_le_mul_right _ (by omega)
    omega

/-- A grammar with any feature or literal at all is non-empty, so N is a usable divisor. -/
theorem exprCount_pos (n lits d : Nat) (h : 0 < lits + n) : 0 < exprCount n lits d := by
  induction d with
  | zero => simpa [exprCount] using h
  | succ d ih => simp only [exprCount]; omega

/-- Every DSL term is a causal strategy.

`features` may read only the view, so the composed strategy satisfies
`decision_ignores_the_future` by construction. This is the join between #3 and #4: the
grammar cannot express a leak because the only data it can reach is causally restricted. -/
def Pred.toStrategy {n : Nat} (p : Pred n)
    (features : (t : Nat) → View t → Fin n → Nat) : Strategy Bool :=
  { decide := fun t v => p.eval (features t v) }

/-- The no-lookahead guarantee transported to every term of the grammar. -/
theorem toStrategy_ignores_the_future {n : Nat} (p : Pred n)
    (features : (t : Nat) → View t → Fin n → Nat)
    (h₁ h₂ : History) (t : Nat) (agree : h₁.visible t = h₂.visible t) :
    (p.toStrategy features).decide t (View.at h₁ t)
      = (p.toStrategy features).decide t (View.at h₂ t) :=
  decision_ignores_the_future (p.toStrategy features) h₁ h₂ t agree

/-- A worked trial count, so the number is concrete rather than rhetorical.

Eight features, four literals, predicate depth 1: 300 expressions, and 110,880 predicates.
Against Bailey et al.'s result that ~45 independent configurations already exhaust five
years of data, this is the honest statement of why an unrestricted grammar search cannot be
corrected after the fact — the search must be budgeted, and the budget declared before it
runs. Proved by `rfl` rather than `native_decide`, so it adds no axiom. -/
example : exprCount 8 4 1 = 300 := rfl
example : predCount 8 4 1 = 110880 := rfl

end Joshi
