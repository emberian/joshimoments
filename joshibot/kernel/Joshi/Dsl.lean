/-
Interface #4 of the Phase 0 manifest: the strategy term algebra.

Two things this buys, and the second is the one that is hard to get any other way.

First, composition with the causal index: a `Pred` term is first-order and is evaluated
through the kernel's own `featuresOf`, so there is no parameter through which a history could
enter. A leaky strategy is genuinely inexpressible ON THIS PATH. (An adversarial audit found
the earlier version false: `toStrategy` took a caller-supplied feature function, and that
closure could capture a tape. The channel is now closed; arbitrary `Strategy` values remain
unconstrained, as `History.lean` says.)

Second, and more unusual: **the trial count is computable.** Honest multiple-testing
correction needs N, the number of configurations actually searched, and in practice nobody
knows it — the deflated Sharpe ratio is routinely applied with N guessed, which is why one
audited implementation of it in this project's own reference material was simply invented
(`sr / ln(trials)`, a formula from no paper). Bailey, Borwein, Lopez de Prado and Zhu show
the stakes: after only ~7 independent configurations the expected best in-sample Sharpe of 1
corresponds to an out-of-sample Sharpe of zero, and five years of data supports about 45.

When the search space is a grammar, N can be COUNTED rather than guessed, and `exprCount` /
`predCount` below do that counting.

Two honest limits on that, both found by adversarial audit and neither yet closed:

1. These recurrences are **verified by exhaustive enumeration** for small parameters (see the
   audit's `count.py`: every case matches, no double counting, `add`/`sub` symmetric, the
   at-most-depth reading consistent with `Expr.depth`/`Pred.depth`). They are NOT proved equal
   to the cardinality of the Lean type, and cannot be as written: `Expr.lit : Nat → Expr n`
   makes even the depth-0 subtype infinite, and `lits` has no referent in `Expr` at all. They
   describe an intended grammar with a bounded literal set. Treat the number as arithmetic
   that has been checked, not as a theorem about this type.
2. Syntactic count ≠ independent configurations. Measured at `n=2, lits=2, d=1`: 1568 terms
   but at most 86 distinct behaviours on a 6×6 feature grid — an 18× inflation from `neg neg`,
   `le a a`, commuted `add`. The direction is CONSERVATIVE for the deflated Sharpe (which
   increases in `trials`), so it cannot manufacture a false discovery — but Bailey et al.'s
   ~7/~45 figures are about *independent* configurations, and this is not that number.
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

/-- The kernel's own feature extractor. Four features, read from the view and nothing else.

This is the fix for a hole an adversarial audit found: `toStrategy` used to accept a
caller-supplied `features : (t : Nat) → View t → Fin n → Nat`, and that function could close
over an entire `History` and read the future — so the "grammar cannot express a leak" claim
was false through the feature channel rather than the term channel.

Defining the extractor HERE removes the channel. A `Pred` is first-order, `featuresOf` is a
closed definition over `v.events`, and there is nowhere left for a tape to enter. -/
def featuresOf {t : Nat} (v : View t) : Fin 4 → Nat
  | ⟨0, _⟩ => v.events.length
  | ⟨1, _⟩ => v.events.foldl (fun acc o => max acc o.value) 0
  | ⟨2, _⟩ => v.events.foldl (fun acc o => acc + o.value) 0
  | _      => (v.events.reverse.head?).elim 0 (fun o => o.value)

/-- Every DSL term is a causal strategy — now genuinely, because the closure channel is gone. -/
def Pred.toStrategy (p : Pred 4) : Strategy Bool :=
  { decide := fun _t v => p.eval (featuresOf v) }

/-- **A DSL strategy reads only the visible prefix.**

Unlike the general congruence lemma this one has content, because `Pred.toStrategy` admits no
parameter through which a history could be smuggled in: `p` is a first-order term and
`featuresOf` is a closed definition over the view's events. Two histories agreeing up to `t`
therefore produce the same decision for a reason stronger than "the strategy ignored its
argument". -/
theorem toStrategy_reads_only_the_visible_prefix (p : Pred 4)
    (h₁ h₂ : History) (t : Nat) (agree : h₁.visible t = h₂.visible t) :
    p.toStrategy.decide t (View.at h₁ t) = p.toStrategy.decide t (View.at h₂ t) :=
  decision_depends_only_on_the_view p.toStrategy h₁ h₂ t agree

/-- A worked trial count, so the number is concrete rather than rhetorical.

Eight features, four literals, predicate depth 1: 300 expressions, and 110,880 predicates.
Against Bailey et al.'s result that ~45 independent configurations already exhaust five
years of data, this is the honest statement of why an unrestricted grammar search cannot be
corrected after the fact — the search must be budgeted, and the budget declared before it
runs. Proved by `rfl` rather than `native_decide`, so it adds no axiom. -/
example : exprCount 8 4 1 = 300 := rfl
example : predCount 8 4 1 = 110880 := rfl

end Joshi
