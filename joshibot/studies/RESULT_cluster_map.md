# RESULT: the cluster map — 13,462 fleets, and an 8-second accumulation ladder

Operator tasking, verbatim: *"let's generalize somewhat and make sure we can map as much of
clusters as possible, including correlational flows among/between etc (not just within but
without) … stuff that is **structure** even if it isn't **edge** yet. finding structure is so
important."*

Code: `studies/cluster_map.py`. Artifacts in `.cache/clustermap/` (gitignored).

---

## 0. The one-paragraph answer

**The market is densely, measurably coordinated, and the coordination has geometry.** Over ten
days and 1,534,512 wallets, an event-first method recovers **13,462 clusters covering 78,340
wallets**. The relations *between* those clusters are not noise: of 300 cluster pairs tested
against a degree-preserving null, **223 systematically avoid each other** and 67 pile on — two
fleets active on all eleven days share **8 coins out of 20,874 and 33,688** (z = −112.6). Twelve
of fifty ordered pairs show **directional predation**, one fleet's selling landing inside
another's buying at 27.9% against a 14.7% matched null (z = 19.7), with the reverse direction
significantly *negative*, which is what makes it directional rather than mutual.

And the thing nobody was looking for: **six clusters — 34 wallets — enter the same coins at fixed
8-second intervals**, rungs at −4, 0, +8, +16, +24, +32 s. They have made **63,052 entries and 62
exits (0.098%)**. They are not trading. They are accumulating on a timer. **They bought nosis in
launch order at +5, +9, +17, +26, +34 and +41 seconds, and every one of them is still holding.**

---

## 1. The primitive, and why it scales

All-pairs similarity over 1.53M wallets is 1.18 **trillion** pairs. The method never computes it.

**Event-first.** A wallet going flat is the least-deniable coordination signature (`§7`), and it
is cheap to index. Ten days yield **46,236,544 zero-crossing / opening legs** in **28,613,507
events** over **440,467 pump mints**.

| exclusion | share |
|---|---|
| k < 2 wallets in the event (nothing to link) | 47.4% of legs |
| k > 50 (rug / migration cascades, not coordination) | 5.6% |
| **kept** | **47.0%** |

A **lossless** prefilter — an edge needs 3 mints, which implies 3 events, which implies s ≥ 3 —
cuts 1,534,512 wallets to 594,681 with **byte-identical output**. Final: **2,601,660 candidate
pairs against 1.18 trillion — a 452,543× reduction**, with nothing approximated away.

Weighting is stated rather than assumed: `w = 1/(k−1)` per event (Newman — a 200-wallet rug exit
gives each pair 1/199, so mass exits cannot manufacture links), then degree-normalised to
`cos = W/√(s_u·s_v)`.

---

## 2. The gate, passed unassisted

The method was required to rediscover the four-wallet fleet from `RESULT_bundle_hypothesizer.md`
without being told it existed.

**It returns exactly one module of size 4, containing exactly those four wallets, out of
1,534,512** — at **both** cos ≥ 0.05 and cos ≥ 0.10, a range rather than a tuned point. It never
absorbs the `FBvxneTq…` universal-sniper control at any threshold.

---

## 3. Two methodological failures, both caught and both worth keeping

**Union-find's pathology, measured live rather than cited.** `PROGRAM.md` §4 signal 1 says
"weighted Infomap — **not** union-find". At cos ≥ 0.02, connected components produce a
**14,238-wallet giant blob (8.3% of all clustered wallets)**; Infomap's largest module is **186
(0.1%)**. One promiscuous wallet chains half the market together. The warning was right and now
has a number attached.

**Infomap was not reproducible, and that nearly went unnoticed.** Three runs of a single command
returned **24,180 / 24,196 / 24,199 modules**. The cause was not the algorithm: duckdb's unordered
reads assigned different node ids each run, which changed tie-breaking. Fixed with `ORDER BY u, v`;
the partition now hashes identically across runs. **Every number in this file comes from the
deterministic partition.** A clustering that silently varies run to run would have made every
downstream count unfalsifiable.

---

## 4. Structure BETWEEN clusters — the half that is usually skipped

### 4.1 Territory: fleets avoid each other

300 cluster pairs, 200 curveball (degree-preserving) draws each:

| verdict | pairs |
|---|---|
| **systematic avoidance** | **223** |
| pile-on | 67 |
| null | 10 |

The extreme case: clusters **5985 and 8792 share 8 coins** out of universes of **20,874 and
33,688** — Jaccard **0.0001 against a null of 0.1995, z = −112.6**.

**The boring explanation was checked and ruled out.** They are not avoiding each other by being
active in different weeks: both trade on **all 11 calendar days**, with first trades within
**90 seconds** of corpus start. These are simultaneously-active fleets with **disjoint coin
universes** — a partition of the market, not a schedule artifact.

### 4.2 Predation: directional, and the direction is the evidence

50 ordered cluster pairs against a matched-moment null, 200 draws: **12 above null.**

Strongest — cluster **7434's selling**: **27.9% of its closed volume goes flat inside an 8792
opening**, against a **14.7%** null, **z = 19.7**. One fleet's exits are systematically filled by
another fleet's entries.

**Asymmetry is what makes this predation rather than mere co-activity:** 14351 → 5985 scores
**z = +4.6** while 5985 → 14351 scores **z = −17.8**. If the two merely traded the same coins at
the same times, both directions would be positive.

### 4.3 Co-firing

183,083 coins touched; **66.2% by ≥2 clusters**; **42.5% have ≥2 clusters entering within 60 s**;
maximum observed **1,356 clusters on a single coin**.

---

## 5. The headline: a six-cluster, 34-wallet accumulation ladder on an 8-second timer

Six clusters enter the same coins at **fixed 8-second offsets** — rungs at **−4, 0, +8, +16, +24,
+32 s**. Three independent validations, because a periodic pattern is exactly the kind of thing an
over-eager clustering invents:

1. **The offsets are internally consistent.** 11 pairwise cluster offsets fit a single 1-D ladder
   with **6 independent consistency checks and zero mismatches**. Inter-quartile ranges are **1
   second wide** over 3,000+ coins per cluster.
2. **It survives dropping the partition entirely.** Ignoring cluster labels, all 33 non-reference
   wallets sit at **exactly their cluster's rung, IQR ≤ 1 s**. Clusters whose wallets do *not* all
   share one median offset: **0 of 6.** So Infomap **found** the rungs; it did not quantize a
   continuum into them.
3. **It fired on nosis, live** (§6).

**They do not sell.** 63,052 entries against **62 exits — 0.098%**. This is not a trading fleet;
it is an accumulation machine on a timer.

**The obvious alternative was tested and is decisively negative.** A balance corpus cannot see
instruction type, so "these are dust-airdrop recipients, not buyers" had to be excluded on
evidence: **distinct-amounts / entries = 0.996–0.9998** and **top-1 amount share ≤ 0.11%**. Every
position is a different size. Fixed-value dust would collide constantly; buying into a moving
bonding curve would not. These are purchases.

**What it is remains open.** Sybil accumulation ahead of some future distribution, a
buy-every-launch indexing strategy, and paid holder-count manufacturing all fit a machine that
buys on a metronome and never sells. This instrument cannot separate them, and no story is offered
here beyond the geometry.

---

## 6. The operator's coins

**nosis** — 44,128 crossing events, **329 clusters** touched. The ladder bought it **in launch
order at +5, +9, +17, +26, +34 and +41 seconds**, matching its global rung spacing to within 1
second, and **all six clusters show zero exits. They are still holding.**

That is a distinct finding from `RESULT_bundle_hypothesizer.md` §8's "+0.0 pp, no supply parking",
and the two do not conflict. That measured **supply fragmented by transfer**. This is coordinated
**buying**: 34 wallets that each genuinely purchased, so no transfer graph links them and
bundle-adjusted concentration cannot see them. The consequence is narrow and worth stating
plainly: **nosis's holder count includes at least 34 wallets that are one coordinated actor, and
its first 41 seconds of demand were partly a metronome rather than a market.**

**weave / SOLVE / DREGG** were touched by **106 / 52 / 50** clusters. Their launches predate the
corpus, so their measured "latency" is from corpus start — **censored, not a launch latency** — and
no launch claim is made for them.

---

## 7. The channel ranking, now quantitative

This sharpens `RESULT_bundle_hypothesizer.md` §1's finding that same-slot co-occurrence is a
launch-sniping artifact. Measured against the universal-sniper control across the full corpus:

| channel | separation |
|---|---|
| **synchronized exit only** | **∞** — the control shares **zero** exit events with the fleet |
| entry + exit | 90.5× |
| entry only | 50.3× |

**Synchronized *entry* carries the launch-sniping confound; synchronized *exit* does not.**
Everyone races the same launch; only coordinated wallets go flat together. Exit is the channel to
build on.

---

## 8. Limits

* **Funding ancestry is not computable locally** — no fee payer, no native-SOL legs. Every label
  is `inferred`.
* **The method separates "moves with" from "does not move with", and nothing finer.** It cannot
  distinguish one entity's wallets from a copy bot following that entity, nor either from a
  two-sided market maker. §5's ladder is a *geometry*, not an identification.
* **Clip sizes are token-supply fractions, not SOL.**
* **Ten days truncates longer lifecycles**, and three of the four operator coins launched before
  the window.
* **§4.2's predation rests on 12 of 50 ordered pairs.** The direction asymmetry is the strongest
  part of that claim; the prevalence is not an estimate.
* The **first** predation null was an artifact and is disclosed rather than buried: drawing entry
  slots uniformly from a coin's active-slot support gave large *negative* z on every pair, because
  entries are front-loaded while exits are spread, so uniform draws push entries into exits by
  construction. Replaced with matched-moment substitution.
