# RESULT: the busiest fleets hold disjoint territory -- 204 of 300 pairs share ZERO coins

Registered as D3 in `studies/REGISTRATION_d4m.md`. Code
`dregg_d4m/analyses.py:d3_territory`; artifact
`state/dregg_d4m/d3_territory_community_pairs-v1-*.parquet`. Reproduce:
`uv run --group research python -m dregg_d4m d3`.

---

## 0. The one-paragraph answer

`RESULT_cluster_map.md` section 4.1 found that of 300 cluster pairs tested against a
degree-preserving null, **223 systematically avoid each other**, 67 pile on, 10 are null. That
was measured on Infomap clusters over **zero-crossing exit events** across ten days of the
bulk tape. Recomputed here as one sparse product -- `U U'` where `U = binarize(P B)` -- over
**label-propagation crews on birth-slot entries** across a different 24-day window, the same
300-pair test returns:

| verdict | this lane | `cluster_map` |
|---|---|---|
| **systematic avoidance** | **224** | **223** |
| pile-on | 41 | 67 |
| null | 35 | 10 |
| avoidance share | **74.7%** | 74.3% |

**The registered claim was a SHAPE replication -- avoidance dominates pile-on -- and it holds
at 74.7% against a 50% bar.** That the avoid COUNT lands on 224 against 223 is not something
the registration claimed and is not a result; two independent instruments on two different
substrates agreeing to within one pair out of 300 is a coincidence worth stating and not worth
believing. The share is the finding.

**And the effect size is larger than the z scores suggest. 204 of the 300 pairs share ZERO
coins**, and 206 of the 224 avoid verdicts have an observed Jaccard below a tenth of their
null mean. Section 4.1 explains why the z values are nonetheless modest, and why a
multiplicity correction on z is the wrong instrument for a zero-count outcome -- a point that
applies to `cluster_map`'s published 223/67/10 exactly as much as to this file's numbers.

The market's partition into non-overlapping coin territories is therefore **not an artifact of
the exit-event substrate, the Infomap partition, or the ten-day window.** It survives changing
all three at once.

---

## 1. The method, and where the algebra earns its keep

`P` is community x wallet (indicator). `B` is the ex-deployer birth-slot incidence, wallet x
coin. Then

```
U = binarize(P B)        # community x coin -- each crew's coin universe, one product
shared = U U'            # every pair's shared-coin count, one more product
```

`cluster_map` computed the equivalent by looping cluster pairs and intersecting coin sets.
The algebra returns the entire 25 x 25 matrix in two products. That is the whole D4M claim in
this lane, and it is worth exactly what it says: the *same numbers*, faster. Nothing here is a
statistic `cluster_map` could not have computed.

Top 25 communities by coin-universe size; all 300 unordered pairs; observed coin-universe
Jaccard against **200 `studies.operator_crime._curveball` draws** on the community x coin
incidence, which holds every crew's coin count and every coin's crew count exactly fixed.
Verdict at `|z| > 2`, cluster_map's sign convention.

## 2. The extremes

**Avoidance.** Crew `c1556` (**9,652 coins**) and crew `c2742` (**7,747 coins**) share
**3 coins**:

| pair | coins A | coins B | shared | Jaccard | null mean | z |
|---|---|---|---|---|---|---|
| c1556 / c2742 | 9,652 | 7,747 | **3** | 0.00017 | 0.01704 | **-19.1** |
| c1556 / c3161 | 9,652 | 3,773 | 36 | 0.00269 | 0.01064 | -9.7 |
| c1556 / c3309 | 9,652 | 2,119 | **0** | 0.00000 | 0.00685 | -9.1 |

Two of the three busiest fleets in the corpus, both active across the entire window
(`community_profile` gives both `t_first` 2026-08-05 and `t_last` 2026-08-28), overlapping on
**three coins out of a combined 17,399**. This is the same object cluster_map found in its
5985 / 8792 pair (8 shared coins out of 20,874 and 33,688, z = -112.6) and it is not a
schedule artifact for the same reason: they are simultaneously active for the whole window.
The z magnitudes are smaller here because 200 draws over 25 communities give a coarser null
than cluster_map's, not because the effect is weaker -- the Jaccards are two orders of
magnitude below their nulls.

**Pile-on.** The complement is just as sharp:

| pair | coins A | coins B | shared | Jaccard | null mean | z |
|---|---|---|---|---|---|---|
| c2742 / c2564 | 7,747 | 1,397 | 721 | 0.0856 | 0.00459 | **+117.7** |
| c3161 / c2890 | 3,773 | 921 | 366 | 0.0846 | 0.00291 | +103.6 |
| c3161 / c337 | 3,773 | 912 | 199 | 0.0444 | 0.00292 | +53.3 |

Note that `c2742` appears on both lists -- avoiding `c1556` at z = -19.1 while piling onto
`c2564` at z = +117.7. Territory is a property of the PAIR, not a disposition of a fleet, and
that is only visible when the whole matrix is computed at once.

## 3. What is NOT reported, and why

**Directional predation is not computable on this substrate, and no number is offered.**
`cluster_map` section 4.2's finding -- one fleet's selling landing inside another's buying, at
27.9% against a 14.7% matched null with the reverse direction significantly negative -- needs
an **exit leg**. `B` is a birth-slot incidence: entries only, one slot, no sells. There is no
version of "7434's selling lands in 8792's opening" that this matrix can express, and
constructing a proxy from entry timing would reproduce exactly the artifact cluster_map
disclosed in its own section 8 (uniform entry draws gave large negative z on every pair
because entries are front-loaded and exits are not).

Section 7 of that study is the reason this matters rather than being a footnote:
**synchronised ENTRY carries the launch-sniping confound and synchronised EXIT does not**
(separation infinity vs 50.3x). This lane is built entirely on the entry channel. Its
territory result is real because territory is about *which coins*, not *when*; its inability
to speak about predation is structural.

## 4. Limits

* **The top-25 cut is by coin-universe size**, so these are the busiest crews and the result
  does not generalise to the 3,341 smaller ones without re-running.
* **`c1556` has 2 wallets and 9,652 coins.** A "community" here can be a small number of very
  busy addresses; size in wallets and size in coins are different things and both are in the
  artifact.
* **200 draws over a 25-row incidence** is a coarse null -- the empirical p floor is 1/201 --
  so the z values rank pairs, they do not carry a calibrated tail probability past that floor.
  This is the same limit `RESULT_svn_cotrading.md` section 4.2 states for every empirical
  randomisation p in this repo.
## 4.1 The threshold sensitivity, measured -- and it is not small

`|z| > 2` is `cluster_map`'s convention and this file reproduces it. It is **uncorrected for
300 comparisons**, and correcting it does not leave the counts alone:

| bar | avoid | pile-on | null |
|---|---|---|---|
| **\|z\| > 2** (cluster_map's convention) | **224** | 41 | 35 |
| **Bonferroni 0.01 / 300** (\|z\| > 4.149) | **43** | 34 | 223 |

**81% of the avoid verdicts do not survive multiplicity correction**, while 83% of the pile-on
verdicts do (avoid z median -2.90; pile-on z median +11.49). The direction still holds at the
corrected bar -- 43 avoid against 34 pile-on -- but 43 vs 34 is not a dominance claim, and
anyone quoting "223 of 300 fleets avoid each other" from either study is quoting an
uncorrected count.

**The correction is, however, the wrong lens here, and the reason is arithmetic rather than
special pleading.** The avoiding pairs mostly share *zero* coins. A statistic that is already
at its floor cannot produce an extreme z: its z is capped at `-null_mean / null_sd`, the null
distribution's own inverse coefficient of variation, which for these small null means over 200
draws sits between about -3 and -19. **The z is measuring the null's variance, not the size of
the avoidance.** The effect-size statement is the robust one and it does not move with the
threshold:

| statement | count |
|---|---|
| pairs sharing **zero** coins | **204 / 300** |
| avoid verdicts with observed Jaccard < one tenth of the null mean | **206 / 224** |

Both studies should be read as "the busiest fleets hold disjoint coin territories", which the
zero-overlap count establishes directly, rather than as "N of 300 pairs are significant",
which is threshold- and draw-count-dependent in both.

## 5. Limits (continued)

* **The trichotomy counts above are uncorrected**, by design, to match cluster_map's stated
  method. The corrected version is section 4.1 and is the one to quote if a count is quoted.
