# RESULT: the crew match is one sparse product, and it agrees to the last decimal

Registered in `studies/REGISTRATION_d4m.md` before any estimand was computed. Code:
`dregg_d4m/` (`assoc.py`, `graphs.py`, `nulls.py`, `parity.py`, `analyses.py`). Artifacts:
`state/dregg_d4m/`. Tests: `tests/test_d4m_assoc.py` (28), `tests/test_d4m_nulls.py` (9),
`tests/test_d4m_graphs.py` (14), `tests/test_d4m_parity.py` (5). 56 in total.

Reproduce:

```
uv run --group research python -m dregg_d4m d0     # the parity gate
uv run --group research python -m dregg_d4m d1     # the crew graph
```

Read-only, no network, no Helius credits, deterministic given the seeds. This lane never
writes to the ledger.

---

## 0. The one-paragraph answer

**D0 PASSES, exactly.** On 3,000 coins the shipped ledger has never stored -- the coins of
single-launch deployers, exact stand-ins for a live launch -- the algebra reproduces
`dregg_screen.ledger.Ledger.crew_match`'s overlap and Jaccard on **3,000 of 3,000**, with
**zero** numeric disagreements. **D1 PASSES**: recomputed as one product plus a
normalisation, `operator_crime`'s cmd_graph statistic comes back as
**0.2607947149034321** against a target of **0.2607947149034321** -- not "within tolerance",
*bit-identical* -- and the day-matched control reproduces to the same precision.

The algebra is therefore licensed, and the licence bought three things the pairwise form
could not see. All three are properties of the SHIPPED matcher, found by holding it against
its own algebra:

1. **`min_jaccard = 0.10` is inert.** Of 1,844 simulated launches that reached at least one
   candidate at `overlap >= 2`, **zero** were then rejected by the Jaccard floor. The median
   matched Jaccard is **0.50** and the 90th percentile is **1.00**. `min_overlap = 2` is the
   entire filter; the second threshold has never rejected anything.
2. **The crew NAME is ambiguous in 44.7% of matches** (824 of 1,844, 95% CI 42.4-47.0%): the
   best Jaccard is tied across stored coins belonging to two or more different crews, and
   which crew gets printed is sqlite's row order, not the data. 197 matches are tied across
   **ten or more** crews. The Jaccard is solid. The crew id next to it frequently is not.
3. **`LIMIT 200` silently loses better matches.** 332 of 3,000 launches produced more than
   200 candidates (max **3,840**), and in **3** of those the truncation returned a strictly
   worse match than the untruncated answer.

---

## 1. What the algebra is

Every asset here is `A(row_key, col_key) -> value` with base58 string keys, which is a scipy
CSR matrix plus two key dictionaries. `B` is birth-slot buyer x coin: **636,136 ex-deployer
incidences over 59,524 wallets and 163,444 coins**, window 2026-08-05..28.

`crew_match` scans stored per-coin sniper sets one at a time and computes
`overlap / (len(launch) + set_size - overlap)`. That is `B' B` over the plus-times semiring
with a Jaccard normalisation applied to the product. cmd_graph builds the same-deployer coin
pair list explicitly and loops it; that is the same product read at a different set of
indices. **Neither is a new statistic in matrix form. They are the same statistic, and the
matrix form computes all of it at once.**

Three semirings are implemented and no more, because only these are tested:
`plus_times` (co-occurrence counts -- the workhorse), `or_and` (reachability support, used
by D4's hop frontiers), and `max_min` / `max_plus` / `min_plus` (best-chain values;
`max_min` is the widest-path semiring and is the correct one for chaining similarities,
since a two-hop crew link is only as strong as its weaker leg).

---

## 2. D0 -- the parity gate

### 2.1 The design, and why the query coins are unseen

Scoring the algebra against coins the ledger *stores* would be flattered by a self-match at
Jaccard 1.0. So the query set is the coins of **single-launch deployers**, which the ledger
never stored (`CREW_MIN_COINS = 2`): the artifact has never seen them, exactly as it has
never seen a live launch. n = 3,000, drawn with `numpy.random.default_rng(20260829)`.

Two details decide whether parity is real or cosmetic, and both are in the code:

* **The union denominator uses the FULL launch-set size**, including launch wallets that
  appear in no stored crew set. The product must restrict the query matrix to the ledger's
  wallet universe to share a contraction axis; using that restricted size would shrink
  `len(wallets)` and inflate every Jaccard. The full size is carried separately.
* **The comparison is run in two arms**, because the shipped instrument is not deterministic
  at its shipped settings (section 2.3).

### 2.2 The result

| arm | agreement on (overlap, Jaccard) | agreement including matched_mint |
|---|---|---|
| **untruncated (`LIMIT` lifted on both sides)** | **3,000 / 3,000 = 1.000** | 0.696 |
| shipped config (`LIMIT 200`) | 2,998 / 3,000 = 0.9993 | 0.696 |

* Coins where both returned no match: **1,156**. Coins matched by the ledger: **1,844**.
* Cases where one side matched and the other did not: **0**, in both arms.
* 909 matched coins have a **unique** untruncated argmax. Of those, the 765 that also stayed
  inside the `LIMIT 200` agree on `matched_mint` **765 / 765**. The single exception among the
  909 is a truncation case (292 candidates; the ledger and the untruncated algebra both return
  0.2857, the truncated algebra returns 0.2222) and is section 2.3, not a parity failure.

The registered gate was "100% agreement on `(overlap, round(jaccard, 4))` and on
`matched_mint` wherever the argmax is unique". **Both hold. D0 passes.**

The two numeric disagreements in the shipped-config arm are not the algebra. Both had more
than 200 candidates (230 and 292), and in both the **untruncated algebra returns exactly the
ledger's untruncated answer** (0.4 and 0.2857). They are section 2.3.

### 2.3 The instrument finding: the truncation is not a function of the data

`crew_match`'s SQL is `ORDER BY overlap DESC LIMIT 200` **with no tiebreaker**, and the
candidate list is dominated by a large block tied at `overlap = 2`. Which 200 of that block
sqlite returns is engine row order.

| quantity | value |
|---|---|
| launches with more than 200 candidates | **332 / 3,000 (11.1%)** |
| largest candidate list observed | **3,840** |
| truncation changed the answer | **3 / 332**, Wilson 95% CI [0.003, 0.026] |
| ... and lost a strictly better match | **3 of 3** |

Small, but it is a *silent* wrong answer in a product that prints a crew id, and it is one
`ORDER BY` clause from being deterministic. Overlap order is not Jaccard order: a smaller
stored set with less overlap scores higher, so a rank-by-overlap cut can drop the winner.

### 2.4 The instrument finding: the Jaccard floor never fires

| quantity | value |
|---|---|
| launches reaching >= 1 candidate at `overlap >= 2` | 1,844 |
| ... then rejected by `min_jaccard = 0.10` | **0 (0.0%)** |
| median matched Jaccard | **0.50** |
| 90th percentile matched Jaccard | **1.00** (exact set equality) |
| median launch set size | 4 wallets |

Launch sets are small. An overlap of 2 against a stored set of 4 is a union of 6 and a
Jaccard of 0.33 -- three times the floor. **`min_overlap = 2` is the whole gate**, and the
`min_jaccard` parameter is documentation of an intent that the data never exercises. Raising
it to a value that actually discriminates is a decision the product can now make with a
measured distribution instead of a guess.

### 2.5 The instrument finding that matters most: the crew name

`CrewMatch` names a `crew_id`, and the wire prints it. But the best Jaccard is frequently a
tie:

| tied crews at the best Jaccard | matched launches |
|---|---|
| 1 (unambiguous) | 1,020 (55.3%) |
| 2 | 256 |
| 3 | 148 |
| 4-9 | 223 |
| **10 or more** | **197** |
| **>= 2 (ambiguous)** | **824 (44.7%)**, Wilson 95% CI [42.4%, 47.0%] |

**In 44.7% of matches the instrument prints one crew id out of several equally-supported
ones, chosen by sqlite's row order.** Nothing about the Jaccard is wrong; the *attribution*
is arbitrary. This is invisible to a pairwise scan, which sees one candidate at a time and
has no way to know how many others tied. It falls straight out of the product, which has the
whole row.

The honest live wording is therefore "matches a known crew pattern at Jaccard J" rather than
"matches crew #4213", unless the tie is checked. The tie count is one extra column on the
row the matcher already computes.

---

## 3. D1 -- the crew graph at scale

### 3.1 The replication that licenses it

`operator_crime.cmd_graph`'s arm, recomputed as `_algebra_mean_jaccard` -- one
`co_occurrence` product, one `jaccard` normalisation, one gather at the registered pair list:

| quantity | `graph.json` | algebra | band | verdict |
|---|---|---|---|---|
| same-deployer mean Jaccard | 0.2607947149034321 | **0.2607947149034321** | +/- 0.010 | pass |
| day-matched control | 0.0026193362663966004 | **0.0026193362663966004** | +/- 0.001 | pass |
| curveball null mean (n = 200) | 0.007533357468896544 | 0.007542703698255762 | +/- 0.002 | pass |

The first two are **bit-identical**, which is the strongest form this check can take: the
day-matched control is a random draw and it reproduces exactly because the arm construction
and the rng consumption were replicated, not approximated. The null mean differs in the
fifth decimal because the 200 draws are generated from a fresh `default_rng(20260815)` per
this lane's `against_null` (each draw restarts from the observed incidence) rather than
continuing cmd_graph's single chain; that is a deliberate difference, documented in
`dregg_d4m/nulls.py`, and it moves the answer by 0.9%.

Arm: 9,997 coins x 947 wallets, 20,649 ex-deployer edges, 119,928 same-deployer pairs,
119,928 day-matched control pairs. Effect: **34.6x over the degree-preserving null**,
`p_curveball = 0.000` (floor 1/201 = 0.005), z = 1650.

**The null is `studies.operator_crime._curveball`, imported and reused verbatim** -- the
same Strona et al. trade that validated the shipped instrument. Writing a second one here
would have been the mirror this project keeps paying for.

### 3.2 The graphs

| graph | product | nodes | pairs at `overlap >= 2` | pairs at Jaccard >= 0.10 |
|---|---|---|---|---|
| wallet x wallet | `B B'` | 59,524 | 113,153 | **22,458** |
| coin x coin | `B' B` | 163,444 | 1,463,546 | 1,461,772 |

The coin-coin product needs a wallet-degree cap to exist at all: `sum_w deg(w)^2` is
**9.763e8** untruncated, and the busiest wallet is on 13,847 coins. The cap was registered at
200 before computing, in the same direction as `cluster_map`'s `k > 50` exclusion. Its cost
is measured rather than assumed:

| wallet cap | wallets kept | incidences kept | coin pairs | at J >= 0.10 |
|---|---|---|---|---|
| 50 | 57,999 | 149,774 | 177,365 | 177,010 |
| 100 | 58,616 | 194,612 | 537,236 | 536,413 |
| **200** | **58,998** | **248,986** | **1,463,546** | **1,461,772** |
| 500 | 59,305 | 340,960 | 4,577,873 | 4,553,633 |

Two things are visible here that the pairwise form hides. First, the cap is cheap in
*wallets* and expensive in *pairs*: dropping 526 wallets of 59,524 (0.9%) removes 61% of the
incidence mass, which is a direct measurement of how much of the co-occurrence graph is
manufactured by a few thousand universal snipers. Second, on the coin side **99.9% of pairs
that clear `overlap >= 2` also clear Jaccard 0.10** -- section 2.4's finding again, from the
other direction.

---

## 4. Limits

* **Parity is at the crew-match unit only.** It says the algebra computes what `crew_match`
  computes. It says nothing about whether `crew_match`'s Jaccard is the right statistic --
  that was established by cmd_graph and re-validated in `graph.json`, not here.
* **The wallet-degree cap is a modelling choice**, reported at four values rather than
  defended at one. Every coin-coin number above is conditional on it.
* **The corpus has an 11-day hole** (2026-08-15..25). Nothing here interpolates across it;
  D2 is where that gap is measured rather than assumed away.
* **The three instrument findings are about the SHIPPED matcher and are not fixed by this
  lane.** No file under `dregg_screen/` was modified. They are reported so the decision is
  the product owner's.
