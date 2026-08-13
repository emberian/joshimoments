/-
Interface #2 of the Phase 0 manifest: AMM fill semantics.

This is authored in Lean because it is the one part of the desk where a wrong answer is
silent. A backtest whose fill model is subtly wrong still produces a number, and the number
is what a strategy is selected on — so the fill model is where an error compounds into every
downstream conclusion.

The mechanics are exact integer algebra, which is why this needs no mathlib and no floats.
A constant-product pool holding `tokenRaw` tokens and `solLamports` lamports, sold `Δ`
tokens, pays out `solLamports * Δ / (tokenRaw + Δ)` under floor division. Everything the
replay harness and the sentinel rely on is a consequence of that one definition.

`Nat` throughout, deliberately. Lamports and raw base units are natural numbers on chain;
representing them as floats is the silent-corruption path the tape schema also refuses, and
a proof about floats would be a proof about the wrong object.
-/

namespace Joshi

/-- Pool state. Both sides in their on-chain integer units, never a price. -/
structure Reserves where
  tokenRaw : Nat
  solLamports : Nat
deriving Repr, DecidableEq

namespace Reserves

/-- Lamports paid out for selling `amount` tokens into a constant-product pool.

Floor division, matching the chain: the pool never pays out the rounding remainder. -/
def sellOut (r : Reserves) (amount : Nat) : Nat :=
  r.solLamports * amount / (r.tokenRaw + amount)

/-- Pool state after the sale. -/
def afterSell (r : Reserves) (amount : Nat) : Reserves :=
  { tokenRaw := r.tokenRaw + amount
    solLamports := r.solLamports - r.sellOut amount }

/-- Selling nothing pays nothing. -/
@[simp] theorem sellOut_zero (r : Reserves) : r.sellOut 0 = 0 := by
  simp [sellOut]

/-- Selling into an empty pool pays nothing. -/
@[simp] theorem sellOut_empty (amount : Nat) :
    (Reserves.mk 0 0).sellOut amount = 0 := by
  simp [sellOut]

/-- **You can never extract more than the pool holds.**

The bound that makes an exit budget meaningful: no size, however large, drains more than
the whole SOL side. A fill model without this can hand a backtest free money. -/
theorem sellOut_le_reserve (r : Reserves) (amount : Nat) :
    r.sellOut amount ≤ r.solLamports := by
  unfold sellOut
  rcases Nat.eq_zero_or_pos (r.tokenRaw + amount) with hz | hpos
  · simp [hz]
  · calc r.solLamports * amount / (r.tokenRaw + amount)
        ≤ r.solLamports * (r.tokenRaw + amount) / (r.tokenRaw + amount) :=
          Nat.div_le_div_right (Nat.mul_le_mul_left _ (Nat.le_add_left _ _))
      _ = r.solLamports := Nat.mul_div_cancel _ hpos

/-- Selling more never pays less: the payout is monotone in size.

Both the numerator and the denominator grow with `amount`, so this is not a `div_le_div`.
Writing `Y = q + d` for the payout `q` turns it into a linear fact: the floor bound gives
`q * X ≤ d * a`, and `a ≤ b` carries it to `d * b`, which is exactly what the larger sale
needs. The envelope's size cap depends on this — a bigger clip must never look cheaper. -/
private theorem payout_mono_aux {Y X a b q d : Nat}
    (h : a ≤ b) (hpos : 0 < X + b) (hd : Y = q + d)
    (hfloor : q * (X + a) ≤ Y * a) :
    q ≤ Y * b / (X + b) := by
  have hexp : q * (X + a) = q * X + q * a := Nat.mul_add _ _ _
  have hrhs : Y * a = q * a + d * a := by rw [hd, Nat.add_mul]
  have hqx : q * X ≤ d * a := by omega
  have hab : d * a ≤ d * b := Nat.mul_le_mul_left d h
  have hgoal : q * (X + b) ≤ Y * b := by
    have hexpb : q * (X + b) = q * X + q * b := Nat.mul_add _ _ _
    have hrhsb : Y * b = q * b + d * b := by rw [hd, Nat.add_mul]
    omega
  exact (Nat.le_div_iff_mul_le hpos).mpr hgoal

theorem sellOut_mono (r : Reserves) {a b : Nat} (h : a ≤ b) :
    r.sellOut a ≤ r.sellOut b := by
  rcases Nat.eq_zero_or_pos (r.tokenRaw + b) with hz | hpos
  · have hb : b = 0 := by omega
    have ha : a = 0 := Nat.le_zero.mp (hb ▸ h)
    simp [sellOut, ha, hb]
  · unfold sellOut
    obtain ⟨d, hd⟩ := Nat.exists_eq_add_of_le (sellOut_le_reserve r a)
    exact payout_mono_aux h hpos hd (Nat.div_mul_le_self _ _)

/-- The SOL side never goes negative, because `Nat` subtraction is truncated and the
payout is bounded by the reserve. Stated so the truncation can never hide an underflow. -/
theorem afterSell_sol (r : Reserves) (amount : Nat) :
    (r.afterSell amount).solLamports + r.sellOut amount = r.solLamports :=
  Nat.sub_add_cancel (sellOut_le_reserve r amount)

/-- The token side grows by exactly what was sold in. -/
@[simp] theorem afterSell_token (r : Reserves) (amount : Nat) :
    (r.afterSell amount).tokenRaw = r.tokenRaw + amount := rfl

end Reserves

/-- A minimum-output bound attached to a submitted exit.

The desk's execution bug was a blanket 15% slippage allowance, which is a budget an
adversary can spend. A `MinOut` is instead computed from observed reserves, so the
acceptance test below is a statement about the pool rather than a tolerance. -/
structure MinOut where
  floor : Nat
deriving Repr, DecidableEq

/-- An exit is acceptable exactly when the pool pays at least the floor. -/
def accepts (r : Reserves) (amount : Nat) (m : MinOut) : Prop :=
  m.floor ≤ r.sellOut amount

instance (r : Reserves) (amount : Nat) (m : MinOut) : Decidable (accepts r amount m) :=
  inferInstanceAs (Decidable (m.floor ≤ _))

/-- **A tighter floor is never satisfied by a fill that missed a looser one.**

The monotonicity that makes reason-conditional bounds sound: raising the floor can only
reject more, never accept something a lower floor rejected. -/
theorem accepts_mono (r : Reserves) (amount : Nat) {m n : MinOut}
    (h : n.floor ≤ m.floor) (ha : accepts r amount m) : accepts r amount n :=
  Nat.le_trans h ha

/-- Slippage is deterministic here, so the acceptance test is decidable *before* signing.
This is the property an equities venue cannot offer and an AMM can. -/
theorem accepts_iff (r : Reserves) (amount : Nat) (m : MinOut) :
    accepts r amount m ↔ m.floor ≤ r.solLamports * amount / (r.tokenRaw + amount) :=
  Iff.rfl

end Joshi
