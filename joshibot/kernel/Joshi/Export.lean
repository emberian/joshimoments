/-
The C ABI. This is what makes the kernel load-bearing rather than a parallel document.

Without it, `Fill.lean` proves things about a model of the fill semantics while Python runs a
separate implementation of the same arithmetic, and nothing connects them — the proofs would
decorate the repository instead of constraining it. With it, the Python side computes nothing
and calls into the artifact these theorems are about.

A note on the signature, because it is the interesting part. The C boundary is `UInt64`, but
the arithmetic inside is `Nat`, which is arbitrary-precision. That matters: the intermediate
`solLamports * amount` overflows 64 bits easily — a mid-size SOL reserve times a 1e15 raw
token balance is around 1e32 — so computing this in fixed-width C would silently wrap. Doing
it in `Nat` and narrowing only at the end is safe for a reason we already proved:
`sellOut_le_reserve` bounds the result by `solLamports`, which arrived as a `UInt64`. So the
theorem is not decoration here either; it is the justification for the return type.
-/

import Joshi.Fill

namespace Joshi

/-- Lamports paid out for selling `amount` raw tokens into a constant-product pool.

Exported to C as `joshi_sell_out`. Inputs and output are `UInt64`; the computation is exact
`Nat` internally, so no intermediate can wrap. -/
@[export joshi_sell_out]
def sellOutC (tokenRaw solLamports amount : UInt64) : UInt64 :=
  let r : Reserves := { tokenRaw := tokenRaw.toNat, solLamports := solLamports.toNat }
  UInt64.ofNat (r.sellOut amount.toNat)

/-- Whether a pool pays at least `floor` for selling `amount`. Exported as `joshi_accepts`.

Returned as `UInt8` (1/0) rather than `Bool` so the C signature is unambiguous across
toolchains. This is the gate the executor consults before signing. -/
@[export joshi_accepts]
def acceptsC (tokenRaw solLamports amount floor : UInt64) : UInt8 :=
  if floor.toNat ≤ (Reserves.mk tokenRaw.toNat solLamports.toNat).sellOut amount.toNat
  then 1 else 0

/-- **The narrowing back to 64 bits is lossless.**

`UInt64.ofNat` wraps on overflow, which would turn a proved bound into a silently wrong
payout at exactly the sizes that matter most. It cannot happen here: the payout is bounded by
`solLamports`, which is itself a `UInt64`, so the value always fits. This theorem is what
licenses the exported signature. -/
theorem sellOutC_lossless (tokenRaw solLamports amount : UInt64) :
    (sellOutC tokenRaw solLamports amount).toNat
      = (Reserves.mk tokenRaw.toNat solLamports.toNat).sellOut amount.toNat := by
  have hbound := Reserves.sellOut_le_reserve
    (Reserves.mk tokenRaw.toNat solLamports.toNat) amount.toNat
  have hlt : (Reserves.mk tokenRaw.toNat solLamports.toNat).sellOut amount.toNat
      < UInt64.size := Nat.lt_of_le_of_lt hbound solLamports.toNat_lt
  unfold sellOutC
  exact UInt64.toNat_ofNat_of_lt hlt

/-- The exported gate agrees with the `accepts` predicate the proofs are stated about. -/
theorem acceptsC_iff (tokenRaw solLamports amount floor : UInt64) :
    acceptsC tokenRaw solLamports amount floor = 1
      ↔ accepts (Reserves.mk tokenRaw.toNat solLamports.toNat) amount.toNat ⟨floor.toNat⟩ := by
  unfold acceptsC accepts
  by_cases h : floor.toNat ≤ (Reserves.mk tokenRaw.toNat solLamports.toNat).sellOut amount.toNat
  · simp [h]
  · simp [h]

end Joshi
