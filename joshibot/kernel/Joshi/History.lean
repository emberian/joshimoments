/-
Interface #3 of the Phase 0 manifest: the causal index.

Lookahead is the most consequential bug in this literature and it is almost never visible in
the code that commits it. Measured instances from the audit: the same model family scored
recall 0.778 under a random split and 0.234 under a temporal one — 54 points, purely from
evaluation protocol. A GNN benchmark moved 39.5 F1 points between transductive and inductive
evaluation. One published "purged" cross-validation had a purge parameter that was a literal
no-op. In every case the code ran, produced a number, and the number was wrong.

The defence here is that a strategy is not given a history. It is given a `View t`, which
carries a proof that it contains nothing after `t`. Reading the future is therefore not a
mistake to be caught in review; it is a term that cannot be constructed.
-/

namespace Joshi

/-- One observation, stamped with the chain slot it became true at.

Chain slot, not observer wall-clock. Observer lag on a published pump.fun collector ran to a
p99 of 151 seconds, and indexing on arrival time silently shifts every event. -/
structure Obs where
  slot : Nat
  value : Nat
deriving Repr, DecidableEq

/-- A recorded history. Order is not assumed; `visible` filters rather than truncates, so a
tape that arrives out of order cannot smuggle a future event into a past view. -/
structure History where
  events : List Obs
deriving Repr

/-- Everything observable at or before `t`. -/
def History.visible (h : History) (t : Nat) : List Obs :=
  h.events.filter (fun o => decide (o.slot ≤ t))

theorem History.visible_no_future (h : History) (t : Nat) :
    ∀ o ∈ h.visible t, o.slot ≤ t := by
  intro o ho
  exact of_decide_eq_true (List.mem_filter.mp ho).2

/-- **The only thing a strategy may read.**

The `no_future` field is what makes this a guarantee rather than a convention: you cannot
build a `View t` containing a later event without producing a proof that it is not later. -/
structure View (t : Nat) where
  events : List Obs
  no_future : ∀ o ∈ events, o.slot ≤ t

/-- The canonical view of a history at a slot. -/
def View.at (h : History) (t : Nat) : View t :=
  { events := h.visible t
    no_future := h.visible_no_future t }

/-- Views are determined by their events: the proof field is irrelevant. -/
theorem View.ext {t : Nat} {v w : View t} (h : v.events = w.events) : v = w := by
  cases v; cases w; congr

/-- A strategy: for every slot, a decision from the causally-restricted view.

The type is the specification. There is no `History` argument anywhere in it. -/
structure Strategy (Action : Type) where
  decide : (t : Nat) → View t → Action

/-- **No-lookahead, as a theorem.**

Two histories that agree up to `t` — however wildly they differ afterwards — produce the
same decision at `t`. This is the property that backtest protocols try to enforce socially
with purging and embargoes, and that a leaked feature silently violates. Here it is a
consequence of the strategy's type, so it holds for every strategy anyone can write. -/
theorem decision_ignores_the_future {Action : Type} (s : Strategy Action)
    (h₁ h₂ : History) (t : Nat) (agree : h₁.visible t = h₂.visible t) :
    s.decide t (View.at h₁ t) = s.decide t (View.at h₂ t) := by
  have : View.at h₁ t = View.at h₂ t := View.ext agree
  rw [this]

/-- Appending events strictly after `t` cannot change the view at `t`, hence cannot change
the decision. The concrete form of the same guarantee: tomorrow's tape does not disturb
today's backtested action. -/
theorem later_events_do_not_disturb_the_view
    (h : History) (t : Nat) (extra : List Obs)
    (hlate : ∀ o ∈ extra, t < o.slot) :
    (History.mk (h.events ++ extra)).visible t = h.visible t := by
  simp only [History.visible, List.filter_append]
  have : extra.filter (fun o => decide (o.slot ≤ t)) = [] := by
    apply List.filter_eq_nil_iff.mpr
    intro o ho
    have := hlate o ho
    simp
    omega
  rw [this, List.append_nil]

end Joshi
