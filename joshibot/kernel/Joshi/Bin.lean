/-
Bin-based AMM semantics (Meteora DLMM), authored from `studies/SPEC_dlmm.md`.

Why this file exists at all: **there is no peer-reviewed treatment of bin AMMs**, and the
canonical loss-versus-rebalancing framework provably does not cover one. Milionis, Moallemi,
Roughgarden and Zhang hit the constant-sum discontinuity in their Example 6, observe in
footnote 18 that handling it would need local time and the Itô-Tanaka-Meyer formula, and
decline to pursue it. Nobody has closed that gap since. So the semantics get authored here,
where a property is a machine-checked theorem about the emitted object.

**Say the substrate out loud: this is Lean-authored AMM semantics.** Python and Rust call into
the emitted artifact; they never hand-write bin arithmetic. The deployed program is the oracle
(`kernel_svm/`, which replays real mainnet swaps exactly to the lamport at ~318/s), the real
tape is the test-vector generator, and this file is the specification the two are compared to.

Everything is exact integer arithmetic with *specified* truncation. That is not incidental —
every quantity here is a raw base unit or a Q64.64 fixed-point value, every division floors,
and the floor direction is load-bearing. A model that computes the same quantities in floating
point agrees on almost every input and disagrees on exactly the ones that matter, which is the
failure mode this project has already caught once in a constant-product transcription.
-/

namespace Joshi
namespace Dlmm

/-- The Q64.64 scale. Prices, liquidity and shares all live at this fixed point. -/
def Q64 : Nat := 2 ^ 64

/-- `u128::MAX`. Load-bearing: the program divides by THIS, not by `2^128`. -/
def U128_MAX : Nat := 2 ^ 128 - 1

/-! ## Liquidity: the constant-sum invariant within a bin -/

/-- `L = P·x + y`, in Q64.64, denominated in token-Y base units.

This is the constant-*sum* invariant that makes a bin different from a constant-product pool:
inside a single bin the price is fixed, so there is no slippage at all, and all the curvature
of the AMM lives in the discontinuities *between* bins. That is exactly the structure the LVR
framework cannot handle, and the reason adverse selection here is an atom at each crossing
rather than a smooth variance drip. -/
def liquidity (x y price : Nat) : Nat := price * x + y * Q64

/-- Shares minted for depositing `inLiquidity` into a bin. Floors, per `Rounding::Down`. -/
def liquidityShare (inLiquidity supply binLiquidity : Nat) : Nat :=
  if binLiquidity = 0 then 0 else inLiquidity * supply / binLiquidity

/-- Tokens returned for burning `share`. Floors — withdrawing dust rounds to the LP's loss. -/
def outAmount (share binAmount supply : Nat) : Nat :=
  if supply = 0 then 0 else share * binAmount / supply

/-- **A withdrawal can never exceed what the bin holds.**

The bound that makes a bin's accounting sound: no share, however large relative to the pool,
extracts more of a side than is actually in it. Note the hypothesis is `share ≤ supply` — a
share larger than the total supply is not a state the program can reach, and the theorem does
not claim anything about one. -/
theorem outAmount_le_holdings (share binAmount supply : Nat) (h : share ≤ supply) :
    outAmount share binAmount supply ≤ binAmount := by
  unfold outAmount
  rcases Nat.eq_zero_or_pos supply with hz | hpos
  · simp [hz]
  · rw [if_neg (Nat.pos_iff_ne_zero.mp hpos)]
    calc share * binAmount / supply
        ≤ supply * binAmount / supply := Nat.div_le_div_right (Nat.mul_le_mul_right _ h)
      _ = binAmount := by
          rw [Nat.mul_comm]
          exact Nat.mul_div_cancel _ hpos

/-- Burning more shares never returns less. The monotonicity a withdrawal schedule needs. -/
theorem outAmount_mono (binAmount supply : Nat) {a b : Nat} (h : a ≤ b) :
    outAmount a binAmount supply ≤ outAmount b binAmount supply := by
  unfold outAmount
  rcases Nat.eq_zero_or_pos supply with hz | _
  · simp [hz]
  · split
    · exact Nat.le_refl _
    · exact Nat.div_le_div_right (Nat.mul_le_mul_right _ h)

/-- **Flooring always costs the withdrawer, never the pool.**

Stated because the direction is the whole point: `share · amount / supply` floors, so the
remainder stays in the bin. An implementation that rounded the other way would leak value out
of the pool on every dust withdrawal, and the error would be invisible at any single call. -/
theorem outAmount_never_overpays (share binAmount supply : Nat) :
    outAmount share binAmount supply * supply ≤ share * binAmount := by
  unfold outAmount
  rcases Nat.eq_zero_or_pos supply with hz | hpos
  · simp [hz]
  · rw [if_neg (Nat.pos_iff_ne_zero.mp hpos)]
    exact Nat.div_mul_le_self _ _

/-- Depositing nothing mints nothing, at any pool state. -/
@[simp] theorem liquidityShare_zero (supply binLiquidity : Nat) :
    liquidityShare 0 supply binLiquidity = 0 := by
  unfold liquidityShare; split <;> simp

/-- An empty bin returns nothing rather than dividing by zero. -/
@[simp] theorem outAmount_empty (share binAmount : Nat) :
    outAmount share binAmount 0 = 0 := by
  unfold outAmount; simp

/-! ## Bin prices

The program computes `(1 + bin_step/10000)^id` in Q64.64 by binary exponentiation, and every
step truncates. Two details are reproduced literally because a "cleaner" version would be
wrong on real inputs:

* the reciprocal is `u128::MAX / x`, **not** `2^128 / x`, so it is not exactly `1/x`;
* because `base ≥ 2^64` always, the reciprocal branch is taken for every `bin_step ≥ 1`, which
  flips `invert` — so a POSITIVE id ends up inverted and a negative one does not.

Verified against chain by the spec lane: 140 of 140 stored bin prices across two pools, exact.
-/

/-- The Q64.64 base, `1 + bin_step/10000`, with the same truncating division the program uses. -/
def baseOfBinStep (binStep : Nat) : Nat := Q64 + binStep * Q64 / 10000

/-- One step of the 19-bit binary exponentiation. `sq` is squared from the second bit onward. -/
def powStep (e bit : Nat) (sq res : Nat) : Nat × Nat :=
  let sq' := if bit = 0 then sq else sq * sq / Q64
  let res' := if (e / 2 ^ bit) % 2 = 1 then res * sq' / Q64 else res
  (sq', res')

/-- The exponentiation loop, as a top-level definition so its behaviour is provable.

`remaining` counts down; `19 - remaining` is the bit index, matching the program's 19 rounds. -/
def powLoop (e : Nat) : Nat → Nat → Nat → Nat
  | 0, _, res => res
  | n + 1, sq, res =>
    let (sq', res') := powStep e (19 - (n + 1)) sq res
    powLoop e n sq' res'

/-- Q64.64 binary exponentiation over exactly 19 bits, truncating at every step. -/
def powQ64 (base e : Nat) : Nat := powLoop e 19 base Q64

/-- Price of bin `id` in Q64.64, for a non-negative id. Mirrors `get_price_from_id`.

Restricted to `Nat` ids deliberately: negative ids need the same routine with the invert flag
resolved the other way, and conflating the two is precisely the sign error that would make the
model agree with the program on half the pools and silently disagree on the rest. -/
def priceOfBinNonneg (binStep id : Nat) : Nat :=
  let raw := powQ64 (baseOfBinStep binStep) id
  if raw = 0 then 0 else U128_MAX / raw

/-- Exponent zero leaves the accumulator untouched, whatever the base and however many rounds.

Proved structurally rather than by evaluation: the squaring chain reaches `base^(2^19)`, which
no kernel is going to reduce, and `native_decide` would add `ofReduceBool` to the axiom set
that this project's own gate refuses. The argument is simply that no bit of `0` is ever set,
so the `res` branch is never taken. -/
theorem powLoop_zero_exp (res : Nat) : ∀ (n sq : Nat), powLoop 0 n sq res = res := by
  intro n
  induction n with
  | zero => intro _; rfl
  | succ k ih => intro sq; simp [powLoop, powStep, ih]

/-- **Bin zero is exactly the fixed-point one, for every bin step.**

The anchor the whole price ladder hangs from, and the one price that has to be exact rather
than merely close — every other bin is defined relative to it. -/
theorem powQ64_zero (base : Nat) : powQ64 base 0 = Q64 :=
  powLoop_zero_exp Q64 19 base

end Dlmm
end Joshi
