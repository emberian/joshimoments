/-
The position book, and the exact arithmetic of releasing capacity.

Split out of `Envelope.lean` because it is a different kind of object: this file knows nothing
about limits, gates or learners. It is the desk's book of open positions and the three
operations the envelope performs on it — total it, look a position up, release lamports back
out of one — together with the arithmetic facts that make the release safe.

**Why the book exists at all.** The envelope previously carried exposure as a single `Nat`
field that only ever grew. That models a desk which can buy and never sell, so it ratchets to
its cap and stops trading forever; it cannot express the desk's primary action. Exposure here
is instead *derived* from the book (`bookTotal`), which is how the live shadow book computes
it too (`shitcoims_scalper/book.py`: `sum(p.size_lamports for p in open.values())`). Deriving
it rather than storing it is the cheap way to make an illegal state unrepresentable: there is
no way to construct a desk whose recorded exposure disagrees with the positions it holds,
because there is only one place the number comes from.

**On `Nat` subtraction, which is truncated and therefore dangerous.** Releasing capacity is
the kernel's only subtraction, and `5 - 7 = 0` in `Nat` would silently turn an over-large exit
into a free reset of the book to zero. Two ways out: carry exposure as `Int` with a
non-negativity invariant, or stay in `Nat` and prove the release never exceeds what is open.

**This kernel takes the second.** Lamports and raw base units are natural numbers on chain, so
`Int` would introduce a representation the domain does not have and an invariant to drag
through every theorem, purely to make an underflow *representable* so it can be excluded. The
`Nat` route excludes it earlier: the gate refuses a release larger than the open position
(`Envelope.releasable`), and `bookTotal_bookRelease_exact` below discharges the truncation
outright. Note its shape — it is stated as `total (release …) + amount = total` and never as
`total (release …) = total - amount`, because the second form is *also true when it truncates*
and so proves nothing. The additive form is false under truncation, which is exactly why it is
worth proving. This is the same idiom `Fill.lean` uses for the pool's SOL side in
`afterSell_sol`, for the same reason.
-/

namespace Joshi

/-- One open position. `mint` is an opaque identifier; `costLamports` is what is at risk in it.

`costLamports` is what the desk *put in*, not a mark to market. The envelope bounds capital
committed, and marking exposure to a live price would make the cap move under the desk — the
sentinel's fabricated-cost-basis defect is what a price-derived basis costs in practice.

Distinct from `Basis.Position`, deliberately and not just to dodge the name clash: that one is
a *holding* whose cost basis may be unknown (`basis : Option CostBasis`), which is the right
shape for reconstructing what an already-open bag cost. This one is what the desk committed at
entry, which is known by construction because the envelope is what admitted it. The two would
be wrong to merge; an envelope whose exposure could be `none` could not bound anything. -/
structure OpenPosition where
  mint : Nat
  costLamports : Nat
deriving Repr, DecidableEq

/-- Total lamports at risk across the book. This *is* the desk's exposure; see the header. -/
def bookTotal : List OpenPosition → Nat
  | [] => 0
  | p :: rest => p.costLamports + bookTotal rest

@[simp] theorem bookTotal_nil : bookTotal [] = 0 := rfl

@[simp] theorem bookTotal_cons (p : OpenPosition) (rest : List OpenPosition) :
    bookTotal (p :: rest) = p.costLamports + bookTotal rest := rfl

/-- The open position in `mint`, if the desk has one. -/
def bookFind? (mint : Nat) : List OpenPosition → Option OpenPosition
  | [] => none
  | p :: rest => if p.mint = mint then some p else bookFind? mint rest

@[simp] theorem bookFind?_nil (mint : Nat) : bookFind? mint [] = none := rfl

theorem bookFind?_cons_self (p : OpenPosition) (rest : List OpenPosition) :
    bookFind? p.mint (p :: rest) = some p := by
  simp [bookFind?]

/-- Take `amount` lamports of risk back out of the position in `mint`.

A release that meets or exceeds the position closes it; a smaller one leaves the remainder
open. On a mint the desk does not hold, the book is returned unchanged — the *gate* is what
refuses such an action (`Envelope.release_of_unopened_rejected`), so this function is never
asked to invent a position, and if it were it would still not corrupt the total. -/
def bookRelease (mint amount : Nat) : List OpenPosition → List OpenPosition
  | [] => []
  | p :: rest =>
      if p.mint = mint then
        (if p.costLamports ≤ amount then rest
         else { p with costLamports := p.costLamports - amount } :: rest)
      else p :: bookRelease mint amount rest

/-- **A release never increases exposure, whatever it is aimed at.**

Unconditional: no hypothesis that the position is open or the size is legal. This is what
keeps the exposure bound trivial on the release branch — a release cannot be the step that
breaches a cap, so the gate does not have to defend against one. -/
theorem bookTotal_bookRelease_le (mint amount : Nat) :
    ∀ b : List OpenPosition, bookTotal (bookRelease mint amount b) ≤ bookTotal b := by
  intro b
  induction b with
  | nil => simp [bookRelease]
  | cons p rest ih =>
    by_cases hm : p.mint = mint
    · by_cases hc : p.costLamports ≤ amount
      · simp only [bookRelease, if_pos hm, if_pos hc, bookTotal_cons]
        omega
      · simp only [bookRelease, if_pos hm, if_neg hc, bookTotal_cons]
        omega
    · simp only [bookRelease, if_neg hm, bookTotal_cons]
      omega

/-- **The truncation discharge: a legal release moves exactly the lamports it says.**

Stated additively on purpose (see the header): `total after + amount = total before` is *false*
if the subtraction ever truncates, so proving it rules truncation out rather than hiding it.
The hypotheses are exactly what the gate checks — the position is open, and the release does
not exceed it. -/
theorem bookTotal_bookRelease_exact {mint amount : Nat} {p : OpenPosition} :
    ∀ b : List OpenPosition, bookFind? mint b = some p → amount ≤ p.costLamports →
      bookTotal (bookRelease mint amount b) + amount = bookTotal b := by
  intro b
  induction b with
  | nil => intro h; simp at h
  | cons q rest ih =>
    intro hfind hamt
    by_cases hm : q.mint = mint
    · rw [bookFind?, if_pos hm] at hfind
      have hq : q = p := by simpa using hfind
      subst hq
      by_cases hc : q.costLamports ≤ amount
      · simp only [bookRelease, if_pos hm, if_pos hc, bookTotal_cons]
        omega
      · simp only [bookRelease, if_pos hm, if_neg hc, bookTotal_cons]
        omega
    · rw [bookFind?, if_neg hm] at hfind
      have := ih hfind hamt
      simp only [bookRelease, if_neg hm, bookTotal_cons]
      omega

/-- Releasing exactly what a head position holds leaves the tail untouched.

The step the wind-down plan in `Envelope.run_exitPlan` takes, one position at a time. -/
@[simp] theorem bookRelease_head (p : OpenPosition) (rest : List OpenPosition) :
    bookRelease p.mint p.costLamports (p :: rest) = rest := by
  simp [bookRelease]

/-! ### The book is a map, not a list

`bookFind?` returns the *first* position in a mint, so "the position in this mint" is only a
well-defined thing to release against if there is at most one. The entry gate refuses a second
position in an open mint (`Envelope.entry_duplicate_mint_rejected`), and what follows is what
makes that clause an invariant rather than a spot check: the property survives every operation
the desk can perform, so `Envelope.run_preserves_book_map` can carry it across any learner.

Nothing above depends on this — the arithmetic theorems are all proved over arbitrary books,
duplicates included, so a book that came in from outside the gate cannot make them wrong. -/

/-- No mint appears twice. -/
def bookNoDup : List OpenPosition → Bool
  | [] => true
  | p :: rest => (bookFind? p.mint rest).isNone && bookNoDup rest

/-- A release introduces no mint the book did not already have. -/
theorem bookFind?_bookRelease_none {mint rmint amount : Nat} :
    ∀ b : List OpenPosition, bookFind? mint b = none →
      bookFind? mint (bookRelease rmint amount b) = none := by
  intro b
  induction b with
  | nil => intro _; rfl
  | cons q rest ih =>
    intro hnone
    rw [bookFind?] at hnone
    by_cases hqm : q.mint = mint
    · rw [if_pos hqm] at hnone; exact absurd hnone (by simp)
    · rw [if_neg hqm] at hnone
      by_cases hr : q.mint = rmint
      · by_cases hc : q.costLamports ≤ amount
        · simp only [bookRelease, if_pos hr, if_pos hc]
          exact hnone
        · simp only [bookRelease, if_pos hr, if_neg hc, bookFind?, if_neg hqm]
          exact hnone
      · simp only [bookRelease, if_neg hr, bookFind?, if_neg hqm]
        exact ih hnone

/-- **Releasing preserves the map property.** Closing or shrinking a position cannot create a
duplicate, so the desk cannot exit its way into an ambiguous book. -/
theorem bookNoDup_bookRelease (rmint amount : Nat) :
    ∀ b : List OpenPosition, bookNoDup b = true →
      bookNoDup (bookRelease rmint amount b) = true := by
  intro b
  induction b with
  | nil => intro _; rfl
  | cons q rest ih =>
    intro hnd
    rw [bookNoDup, Bool.and_eq_true] at hnd
    have hq : bookFind? q.mint rest = none := by simpa using hnd.1
    by_cases hr : q.mint = rmint
    · by_cases hc : q.costLamports ≤ amount
      · simp only [bookRelease, if_pos hr, if_pos hc]
        exact hnd.2
      · simp only [bookRelease, if_pos hr, if_neg hc, bookNoDup, Bool.and_eq_true]
        exact ⟨by simpa using hq, hnd.2⟩
    · simp only [bookRelease, if_neg hr, bookNoDup, Bool.and_eq_true]
      exact ⟨by simpa using bookFind?_bookRelease_none rest hq, ih hnd.2⟩

/-- Opening a position in a mint the book does not hold preserves the map property. -/
theorem bookNoDup_cons {p : OpenPosition} {b : List OpenPosition}
    (hfresh : bookFind? p.mint b = none) (hnd : bookNoDup b = true) :
    bookNoDup (p :: b) = true := by
  simp only [bookNoDup, Bool.and_eq_true]
  exact ⟨by simpa using hfresh, hnd⟩

end Joshi
