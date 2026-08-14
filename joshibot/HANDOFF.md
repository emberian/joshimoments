# Handoff — 2026-08-14

Written for whoever resumes this, including a later me. What follows is what a long
forensic detour actually **taught**, and what it **changed** in the project. The
accounting itself stayed in that session; none of it is needed here.

---

## 1. The one lesson worth carrying

**Every error found in a night of measurement was a labelling error. Not one was
arithmetic.**

The chain measures perfectly. It cannot tell you what anything *is*. Enumerating
addresses is trivial; classifying them is the whole problem — and it is the problem
that produced every wrong number we have ever shipped in this repo.

The catalogue, because the shapes repeat:

| what was measured | what it was labelled | what it actually was |
|---|---|---|
| rows with `err != null` | "failed attempts" | mostly arb bots aborting by design — a successful no-op |
| `reference` rows | excluded from denominator | **successes** — routers holding a pool in a lookup table |
| transactions touching the fee program | "creator fee claims" | includes claim *attempts* that paid nothing |
| a program-derived account | "a rando who was sent money" | a fee escrow PDA |
| near-zero-balance forwarding hubs | "exchange deposits" | three of four were the operator's own payees |
| a WSOL wrap targeting an ATA | "a gift" | an LP deposit |
| a swap leg paying a pool vault | "a distribution" | a sell |

**The discriminating tests that actually work**, and which we should reach for by
default:

- **Whose lamports went down?** Presence in `accountKeys` proves nothing. Balance
  deltas prove payment. "Touched" is not "moved".
- **Who owns the account?** System-owned = a wallet, possibly a person.
  Program-owned = plumbing, never a counterparty. This single check would have
  resolved several dead ends instantly.
- **Does it receive from anyone but us?** An exchange deposit address receives
  essentially only from its one owner. A payee receives from many. That test
  separated the two categories in one pass.

And the corollary that matters for every study we run: **absence of a label is not
absence of meaning.** When we cannot classify something, it must be reported as
unclassified, not folded into the nearest bucket. Three separate reports improved the
moment they were forced to name their residual instead of forcing it to zero.

---

## 2. Numbers this corrected, that live in the docs

These are all committed, but they were load-bearing errors and are worth knowing were
*ours*:

- **Priority fee** was hardcoded at 500,000 lamports; measured is **21,000–53,000**.
  `B* = sqrt(priority · Y)` was therefore ~4× oversized for an entire shadow run. The
  operator's instinct for **~$3 clips was right**; the $9 figure I argued for was
  wrong, and the friction gap I cited against it (4.78% vs 3.63%) inverted once the
  constant was fixed.
- **The landing-rate alarm is retracted.** "1–52% landing, friction 2–10× the model"
  was an artifact of two independent defects in our own tool. Real figure for a
  transaction shaped like ours: **95–97%**.
- **Overdispersion does not transfer across estimands.** Hourly *count* Fano ~11–17 is
  real; the *price* variance inflation is **0.59–1.17×**. Applying the count Fano to a
  price-based power calculation double-counts structure the measured σ already holds.
- **The LP edge is router-attention rent, not pricing power.** Both token-token pools
  are dearer *and* thinner than the SOL substitute; a cost-minimising router should
  send them nothing. It fails to **a routing update**, which is a step function, not a
  competitor you can watch for.
- **Concentration is sign-preserving.** `4/W` scales fees and losses identically, so it
  is pure leverage on `(η − VR)`. Tighter bins cannot rescue a −EV pool.
- **The reversion premise is provisional.** Bounce-free variance ratios computed from
  per-swap vault balances read **0.80–1.01 at 15m–1h on four of four pools** — a random
  walk. The 7–9h half-lives came from last-trade closes and carry bid-ask bounce.
- **"Deliberate edge creation" had no route to capture.** Across 593 swaps of full
  history on every token-token pool ever opened, **one** was a genuine direct trade.

---

## 3. Live defects found, and their status

- **The dashboard could re-fabricate a cost basis in one click.** The new-policy form
  pre-filled `cost_basis_sol` from the bag's *current exit quote* and PUT it unmodified
  — the exact mechanism behind the worst loss this desk has taken. The engine's guard
  did not always catch it, because a UI PUT sets origin `operator` and the claim path
  preserves `needs_basis`. **Fixed structurally**: basis is now absent from the draft
  type, so reintroducing it is a compile error. `tests/rendered-html.test.mjs` guards
  it.
- **An address-poisoning campaign is live** against this operator: vanity addresses
  matching both the leading *and* trailing characters of real counterparties, dusted in
  seconds after genuine transfers, targeting the highest-value payees. Nothing has been
  misdirected. The standing rule is simply: **never copy a destination out of
  transaction history.**
- **`studies/deterioration.py` hardcodes SOL at $150.0** — the same constant we
  criticised in another repo, in our own tree, seeding the denominator of forward
  returns. In the hardcode audit's ranked list; not yet fixed.

---

## 4. What changed about the money model

Not the amounts — the *shape*, which affects planning:

- Creator-fee income was **~3× larger than the dashboard figure suggested**, because a
  second coin's fee stream existed that nobody had accounted for anywhere. Lesson: a
  vendor UI shows one product's view; the wallet is the truth.
- The largest single outflow category was **paying people**, not trading and not
  living expenses. Trading losses were a small fraction of it.
- A **vesting escrow holding ~6.3% of DREGG supply** is the largest single asset, on a
  fixed 14-day release schedule. It was invisible to every prior analysis. Any income
  planning should start from it.
- **Do not schedule liquidations against dated obligations.** An earlier brief handed
  cash dates to an LP-strategy agent as a constraint on the LP book, and it dutifully
  recommended dismantling two thirds of the position to cover a few days of fee income.
  Cash constraints attach to the **fee stream**; the book is capital. The right control
  is a coverage trigger, never a calendar.

---

## 5. Process notes that earned their place

- **Agents caught their own errors twice, unprompted**, and both times the catch was
  worth more than the original result: a `bq ls | head -40` truncation that hid the one
  table with the data we needed, and a researcher who noticed it had asserted vendor
  details inherited from an agent whose report never arrived. *A truncating pipe on a
  discovery command is a sample, not a listing.*
- **Separate measured from attested, visibly and always.** Every report improved when
  forced to keep chain-derived and human-supplied figures in different columns that are
  never summed.
- **The operator holds labels no instrument can produce.** Repeatedly, measurement was
  complete and meaningless until a human said "that address is mine" or "that one is a
  scammer." Design for that: make it cheap to attach a label, and record its confidence
  alongside it.

---

## 6. Open, carried forward

- The **probe** (formerly "scalper") lost 15.16% over 73 shadow closes at a 19% hit
  rate — but ran with the 4×-oversized sizing constant. The selection failure stands
  regardless; the *sizing* half was never tested at its own optimum. Re-run before
  concluding anything about size.
- The **rebalance rule** remains the highest-value open question, now qualified: duty
  cycle is necessary but **not sufficient**, because `η < 1` means no rebalance policy
  makes those pools +EV on its own.
- **`studies/flow_signals.py`** exists but its agent died on a 529; the competing-risks
  and changepoint work is unfinished.
- The **hardcode audit's ranked list is unapplied** — it ships a `--check` CI gate that
  is currently green only because nothing has moved.
- **Bulk history is validated and unpurchased**: ~$28 for 22 days, ~$60 for the full 48,
  replay-grade, verified 876/876 reserve-exact against live tape. It needs billing
  enabled on a GCP project and a `--maximum_bytes_billed` cap wired in as a default.
