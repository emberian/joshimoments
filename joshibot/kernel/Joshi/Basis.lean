/-
Interface #5 of the Phase 0 manifest: cost basis with provenance in the type.

On 2026-08-12 the desk lost 7.47 SOL because `engine.py` stamped cost basis from the current
Jupiter exit quote. PnL therefore started at 0% by construction, and every stop fired that
far below wherever the coin had already fallen. Split by basis source over the same window:
operator-typed +18.1% mean over 3 round trips, quote-stamped -29.1% over 16.

The fix in Python was to delete the offending assignment at four call sites. What this file
adds is weaker than it originally claimed, and an adversarial audit was right to say so.

`BasisSource` has no `fromQuote` constructor, so a basis must NAME its provenance. But the
source is a label with no relationship to `lamportsPaid`, and nothing stops a caller stamping
the current exit quote and labelling it `operator`:

    { lamportsPaid := r.sellOut bag, tokensAcquired := bag, source := .operator, .. }

That compiles, and it reproduces the -7.47 SOL failure exactly — PnL starts at 0 bps and the
stop never fires. What the type buys is a REQUIRED, AUDITABLE declaration of where a number
came from, not an impossibility. The guarantee has to come from the construction site: the
sentinel's only path to `observedFill` is the chain reconstructor, and `observedFill` carries a
signature and slot precisely so a mislabel can be checked against chain after the fact.

The second property this file buys is fail-closed PnL. A position whose basis could not be
established has `none`, not a guess, and every threshold rule is a function of PnL. So an
unknown basis cannot fire a stop; it can only leave rug protection running. That is the
behaviour the Python engine now implements, stated here as a theorem instead of a convention.
-/

namespace Joshi

/-- Where a cost basis came from.

Deliberately total and deliberately small. There is no `fromQuote`, and adding one would be
a visible, reviewable change to this type rather than a line buried in a 1500-line engine. -/
inductive BasisSource where
  /-- Reconstructed from a fill we actually observed on chain. -/
  | observedFill (signature : String) (slot : Nat)
  /-- Typed by the operator, who is asserting what they paid. -/
  | operator
deriving Repr, DecidableEq

/-- What was actually paid to acquire a holding.

`tokensAcquired` is carried as a proof-bearing field: a basis over zero tokens has no
per-unit price, so the division that computes entry price cannot be reached without it. -/
structure CostBasis where
  lamportsPaid : Nat
  tokensAcquired : Nat
  source : BasisSource
  tokens_pos : 0 < tokensAcquired
deriving Repr

namespace CostBasis

/-- Entry price in lamports per raw token unit, floor-divided.

Per-unit rather than per-lot on purpose: a scale-out shrinks the bag, and a lot-denominated
basis would drift the entry that the stop measures against every time part of it is sold. -/
def entryPrice (b : CostBasis) : Nat :=
  b.lamportsPaid / b.tokensAcquired

end CostBasis

/-- A holding, which may or may not have a known basis.

`none` is a first-class outcome, not an error path. Reconstruction genuinely fails — no
history in the window, inconsistent balances, tokens acquired by airdrop with no SOL
outflow — and in each case the honest answer is that we do not know what was paid. -/
structure Position where
  tokensHeld : Nat
  basis : Option CostBasis
deriving Repr

namespace Position

/-- Profit or loss in basis points, available only when the basis is known.

There is no fallback branch. That absence is the whole design: every threshold rule below
consumes this `Option`, so an unknown basis propagates to "no threshold can fire" rather
than to a fabricated zero. -/
def pnlBps (p : Position) (exitLamports : Nat) : Option Int :=
  match p.basis with
  | none => none
  | some b =>
    let paid := b.lamportsPaid
    if paid = 0 then none
    else some ((exitLamports * 10000 : Nat) / paid - 10000)

/-- Whether a stop-loss at `thresholdBps` should fire. Unknown basis never fires. -/
def stopFires (p : Position) (exitLamports : Nat) (thresholdBps : Int) : Bool :=
  match p.pnlBps exitLamports with
  | none => false
  | some pnl => decide (pnl ≤ thresholdBps)

/-- **A position with no established basis cannot fire a stop, at any price.**

This is the fail-closed property, quantified over every exit valuation and every threshold.
It is what makes "we could not read the basis" safe to ship: the worst case is that a bag
keeps only its rug protection, never that it is liquidated against an invented number. -/
theorem no_basis_never_stops (p : Position) (h : p.basis = none)
    (exitLamports : Nat) (thresholdBps : Int) :
    p.stopFires exitLamports thresholdBps = false := by
  simp [stopFires, pnlBps, h]

/-- Every basis names a provenance: an observed fill, or an operator assertion.

Constructor exhaustiveness over a two-constructor inductive, and nothing more — it depends on
no axioms and it holds of a MISLABELLED basis too. It says the declaration is present, never
that it is true. The earlier docstring claimed unconstructibility of a quote-derived basis;
that was false, and the module header now records the counterexample. -/
theorem basis_source_is_observed_or_operator (b : CostBasis) :
    (∃ sig slot, b.source = BasisSource.observedFill sig slot) ∨
      b.source = BasisSource.operator := by
  cases h : b.source with
  | observedFill sig slot => exact Or.inl ⟨sig, slot, rfl⟩
  | operator => exact Or.inr rfl

end Position

end Joshi
