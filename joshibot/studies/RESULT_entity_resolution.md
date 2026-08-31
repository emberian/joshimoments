# Signal #2 — funding-tree entity resolution

**Verdict on the live data: `NO-LINKS-AT-THIS-N`.** Not one of the three linkage sources has a
single surviving edge in this environment, because the only wallet-level corpus we hold indexes
**two** wallets. That is a statement about the corpus, not about whether coordinated wallets exist,
and it is reported first because the instrument built to find them is the deliverable.

The instrument is real and calibrated: `studies/entity_resolution.py`, 48 tests, **15/15 mutations
kill their guarding test**, and pair precision **1.000** with recall **0.762** against a planted
world whose truth we wrote down. The one thing the live store *could* tell us it did tell us, and
it is a negative result worth more than the study: **the only linkage-shaped relation the store can
express would merge our own sentinel wallet with a third-party KOL wallet**, on the strength of one
dust sender.

Run:

```
python -m studies.entity_resolution --store <copy>/intelligence.sqlite3 --out links.jsonl
python -m studies.entity_resolution --simulate 20260813        # calibration
studies/falsify_entity_resolution.sh                            # the mutation matrix
```

---

## 1. The question

PROGRAM.md §4 ranks this second and calls it a prerequisite for signals #1, #4, #5, #6 and #7. The
reason is §3 rule 2: a study that splits train/test before collapsing wallets to entities lets one
actor straddle both sides. The motivating number is MELT's — **36.5% of token supply is held by
coordinated accounts disguised as independent** — and the payoff is the **bundle-adjusted minus
naive top-10 delta** (+24pp high-risk vs +6pp low-risk), which does not exist until wallets are
resolved to entities. Raw top-10 share is a listed anti-signal; 98.7% of launches have a dev buy.

The output is interface #7, `EntityLink`, emitted exactly as `shitcoims_tape/schema.py` freezes it.

---

## 2. Which linkage sources could actually be built

| # | Source | Built? | Rows in this environment | Why |
|---|---|---|---|---|
| 1 | **Co-signing** (joint signers of one tx) | yes, strict | **0** | needs a signer set; the tape has none, and the store carries only `fee_payer` |
| 2 | **First-funder / fund-flow** | yes | **0** | needs native SOL transfers; nothing local carries them. Fetch plan and its cost are in §11 |
| 3 | **Jito bundle id** | yes | **0** | bundle ids are *not on chain*. Reads `shitcoims_tape.backfill`'s existing sidecar shape verbatim, so MELT's crawled traces import with no translation step |
| — | *fee-payer sponsorship* | built, **refused by default** | 1,164 | the only relation present, and it is spam — see §5 |
| — | *unsigned co-occurrence* | built, **refused by default** | 0 | on an account-model chain a transfer puts sender and recipient in one transaction while only one holds a key |

All three MELT sources are implemented and union-merged. Two of them return zero because the input
does not exist yet; the third returns zero because the corpus is two wallets wide. Nothing was
stubbed, and nothing was silently downgraded to a weaker relation to manufacture output.

**What does not transfer, and was not used.** Bitcoin's multi-input co-spend heuristic has no
analogue here: Solana is account-model, and "two wallets moved in one transaction" is satisfied by
every airdrop. The Ethereum replacements (Victor 2020 — deposit-address reuse, airdrop
multi-participation) are the right family, and first-funder is deposit-address reuse in Solana
clothing. None of it has published precision or recall against ground truth.

---

## 3. n at every stage — the live intelligence store

Read through `shitcoims_tape.backfill.load_intelligence_wallet_transactions`, which is what
un-inverts the store's two clocks (`emitted_at` is block time for chain rows, the reverse of its
social rows) and what refuses multi-leg rows rather than splitting one SOL delta across legs.

| stage | n |
|---|---|
| `wallet_transaction` rows read | 1,577 |
| imported as trades | **1,250** |
| skipped | 327 |
| — of which multi-leg (refused, not split) | 110 |
| — of which address failed the 32-byte decode | 172 |
| rows with no block time (kept, counted) | 179 |
| **distinct wallets** | **2** |
| distinct mints after import | 611 |
| distinct signatures | 1,166 |
| signatures touching more than one observed wallet | **0** |
| funding edges available | **0** |
| co-signature rows available | **0** |
| Jito bundle rows available | **0** |
| surviving links | **0** |
| largest cluster | 1 |

**Holders per mint: 611 mints, every one with exactly one holder.** That is the wallet-indexed-tape
pathology SWARM.md Track B already measured from the other direction: a wallet-indexed corpus
records nothing about a mint the watched wallets ignored. The top-10 concentration delta is
therefore identically zero here by construction, not by measurement — see §8.

---

## 4. The verdict, and why it is a null rather than a failure

`NO-LINKS-AT-THIS-N`. The resolver ran, every stage reported its denominator, and the answer is
zero links. Two wallets cannot form a funding tree. This is the honest form of the result and it is
reported prominently because the alternative — reaching for the one relation that *is* present and
calling it entity resolution — is precisely the error §5 documents.

---

## 5. The one real finding: the store's only linkage-shaped relation is a false positive

The store carries `fee_payer` on every `wallet_transaction` payload. That is the sole counterparty
identity it holds, and it is **not on the tape** — SWARM.md Track B lists the absence of
`fee_payer`/`trader_paid_fee` on `Trade` as gap (2). Measured:

- **1,164** rows where the fee payer is not the subject (after dropping failed transactions)
- **820** distinct such payers
- **1,062** of those rows are *inbound token, zero SOL movement* — i.e. dust spray, matching the
  earlier 88.5%-inbound-dust finding on this wallet
- **one** payer, `Hx51Pd4ajqhVDD8CwrhecRNWvfouFr1vo6WL1CZvChY`, touched **both** watched wallets

Run with `--trust-sponsor-edges`, the resolver therefore emits:

```
{"wallet":"Sh1WNJ8g68rXJGyDjVPcfxWN1WbMrLsgdXmSb6cccuE", ... "entity_id":"ef3f0cf4da08da9b1","method":"sponsor_unverified"}
{"wallet":"GV6UUmNxz2RpKxmNAPadYKb7uQpszwqQAu3qLJxVdC52", ... "entity_id":"ef3f0cf4da08da9b1","method":"sponsor_unverified"}
```

`Sh1WNJ…` is **our own sentinel wallet** (`studies/callout_flow.py::POLICY_WALLETS`). `GV6UU…` is
the third-party KOL wallet. One dust sender that happened to pay for a transaction touching each of
them merges them into one actor. Every downstream study — deployer ancestry, co-trading, skill
fraction — would then be reading a closed loop.

Note what the degree rule does **not** do here: `Hx51Pd…` has fan-out 2, so no threshold catches it.
The rule that catches it is *typed*: a funding edge must be a **native SOL transfer that is the
account's first inbound SOL**, not "somebody paid my fee". That is why sponsorship is a separate
type in the code (`SponsorEdge`, never `FundingEdge`) and refused by default, with the flag
stamping `INFERENCE_INVALID` into the output when it is enabled.

---

## 6. Method — every choice and why

### 6.1 First funder

Per funded wallet, the **earliest** inbound transfer by `(slot, signature)`. Only the first can be
the rent deposit that brought the account into existence; later transfers are payments and carry no
custody implication. Self-funding is dropped. Ordering is by slot, not by row order, so the answer
is identical under any input permutation (`test_first_funder_is_the_earliest_by_slot…`, and
mutation 5 flips `<` to `>` and kills it).

**A structural fact worth stating, because it bounds the damage:** a wallet has exactly one first
funder, so the shared-funder relation *partitions* wallets by funder and cannot chain. Funding-only
components are therefore bounded above by `hub_degree − 1`. Every blob larger than that came from
combining sources. Pinned in `test_funding_only_components_cannot_exceed_the_hub_degree`.

### 6.2 The CEX-exclusion rule, stated precisely

MELT says to exclude CEX funding addresses because their outflows are user withdrawals, not
control. Realised as two rules, in this order:

1. **Curated** — an operator-supplied address file (`--exchanges`), comments allowed so provenance
   travels with each entry. **Empty by default, on purpose.** A hard-coded "this address is
   Binance" that nobody in this environment can verify is an unfalsifiable assertion sitting in the
   middle of a merge rule — the same disease as a cost basis stamped from a quote. It is a
   supplement, never the mechanism.
2. **Structural** — a funder whose **fan-out** (distinct wallets whose *first* funding it paid)
   reaches `hub_degree` is dropped as a linkage source. Default **25**. This is the rule that has
   to work, because it is measurable from the data with no external labelling.

The same fan-out logic is applied to co-signing (a fee-paying relayer co-signs with every customer;
without it one relayer merges its entire customer base — `test_relay_cosigner_hub…`).

**How the rule was validated.** Three ways, none of which is ground truth:

- **Synthetic, adversarial.** One address funding **2,000** unrelated wallets produces largest
  cluster **1** and zero merges. Disabling the rule collapses all 2,000 into one entity
  (`test_cex_hub_test_has_teeth_when_the_exclusion_is_disabled`), so the passing test measures the
  rule and not the fixture.
- **Exclusion removes the edge, not the wallets.** A hub's children stay resolvable by other
  evidence: two of the 2,000 that also co-sign still merge, and nothing else does
  (`test_hub_exclusion_removes_the_edge_not_the_wallets`). Dropping the wallets instead would throw
  away every sniper that once withdrew from an exchange.
- **Threshold sweep, reported with the number** (§3 rule 7 — the NFT wash literature produced 0.12%
  to 94.5% on one market purely by moving knobs):

| `hub_degree` | funders excluded | wallets merged | largest cluster | pair precision | pair recall |
|---|---|---|---|---|---|
| 2 | 41 | 138 | 6 | 1.000 | 0.425 |
| 3 | 40 | 139 | 6 | 1.000 | 0.428 |
| 5 | 16 | 168 | 6 | 1.000 | 0.555 |
| **10** | 1 | 209 | 6 | 1.000 | **0.762** |
| **25 (default)** | 1 | 209 | 6 | 1.000 | **0.762** |
| **50** | 1 | 209 | 6 | 1.000 | **0.762** |
| **100** | 1 | 209 | 6 | 1.000 | **0.762** |
| 200 | 0 | 61 | 302 → suppressed | 1.000 | 0.198 |
| 500 | 0 | 61 | 302 → suppressed | 1.000 | 0.198 |

The answer is **flat across a full decade of the knob**, 10 to 100, which is the only kind of
threshold justification worth having. It moves only at the extremes: too tight and genuine
two-wallet actors are discarded, too loose and the exchange survives the test — at which point the
tripwire fires and the resolver *refuses* rather than merging wrongly. **Precision is 1.000 at every
threshold.** The knob buys recall; it cannot buy errors.

### 6.3 The super-cluster tripwire

Degree capping alone is not enough, and the tests prove it. Consecutive wallet pairs sharing a
first funder with fan-out exactly 2, stitched by two-signer transactions, pass **every** local rule
— zero funders excluded, zero relays excluded — and union-find still walks 240 wallets into one
component. So a global tripwire sits after the merge: a component at or above
`supercluster_min_size` (50) that also holds `supercluster_share` (5%) of the known wallets is
**suppressed**. Both conditions must hold — an absolute floor so a 2-of-4 fixture never trips, a
share so corpus growth cannot silently disarm it.

Suppressed wallets are **absent from the output**, not emitted as singletons: emitting them as
singletons would assert an independence we do not have, and a downstream splitter that needs
complete coverage must be able to see the gap. The verdict changes to
`SUPER-CLUSTER-SUPPRESSED` and the count is reported.

The §4.1 objection is worth answering directly. PROGRAM.md rejects connected components for the SVN
co-occurrence network, where they swallow 99.6% of the graph. That is a statement about a
*statistical* co-occurrence graph whose edges are noisy by construction. Funding and co-signing
edges are near-deterministic facts about key custody, and §1.5 endorses union-find over funding
relations by name. The blob risk is real all the same — hence the tripwire, and hence measuring it.

### 6.4 Co-signing requires signers, not co-occurrence

The tape's `Trade` carries one wallet and no `fee_payer`, so "both wallets moved in one signature"
cannot distinguish a co-signer from a passive airdrop recipient. In a synthetic sprayer scenario —
one duster, 60 victims, one signature each — accepting co-occurrence produces a **61-wallet**
entity. Refused by default; the count of what was refused is reported so the reader can see the
size of the decision (`links_unsigned_cooccurrence_available`).

### 6.5 Bundles

Bundle ids are not on chain, so the sidecar names signatures and the tape maps them to wallets.
`max_bundle_wallets` defaults to **5** because a Jito bundle holds at most five transactions — a
protocol fact, not a tuned threshold. More distinct wallets than that means the signature map is
wrong or the bundle is a shared relay; either way it is not one actor, and the bundle is refused
and counted.

### 6.6 Confidence is a stated prior, never a measurement

| method | confidence | what it encodes |
|---|---|---|
| `co_signing` | 0.95 | a joint signature requires both private keys — near-definitional. Residual risk: multisig, custodial relayers |
| `jito_bundle` | 0.80 | atomic co-execution by one submitter. Residual risk: third-party bundler services |
| `shared_first_funder` | 0.60 | MELT's most productive source and the weakest per link: exchange withdrawals reproduce it for free |
| `sponsor_unverified` | 0.20 | refused by default |
| `co_occurrence_unsigned` | 0.20 | refused by default |
| `singleton` | 1.00 | no merge is asserted |

**These are not measured precision.** There is no ground-truth ownership labelling for Solana
wallets and none of these heuristics has published precision or recall against one. The number
travels in `params.confidence_is` in every run's output so it cannot be read as an estimate.

### 6.7 Output shape

One `EntityLink` per **(wallet, method)**. The frozen dataclass carries a single `method` string,
and PROGRAM.md requires downstream studies to report which heuristic did the work — co-signing and
shared-funder have different false-positive profiles. A wallet merged by two sources emits two
records with the **same** `entity_id`, so a study that wants "only the co-signing clusters" filters
on `method` without losing the merge. `entity_id` is a content hash of the sorted member list, so
it is identical across runs and orderings and *changes* when membership changes — which is correct,
because that is a different claim about the world and must not inherit the old one's identity.

JSONL, never CSV. Raw amounts stay integers end to end; only shares are floats, computed once.

---

## 7. Calibration against a planted world

There is no ground truth, so the only falsifiable number available is recovery against a generator
whose truth we wrote down. **This is strictly weaker than validation** — it measures the resolver
against our own model of how coordinated actors fund wallets, not against the world. It is worth
having because a resolver that cannot recover a world it was handed has no business being pointed
at the real one, and because it turns "the CEX rule costs recall" into an exchange rate.

The generator (`simulate`): 40 actors × 6 wallets funded from that actor's treasury, **except** that
each wallet is instead funded straight from the exchange hub with probability 0.30 — those are
unlinkable by the funding source **on purpose**. Half the actors also co-sign one transaction, half
submit one Jito bundle. Plus 400 unrelated wallets, funded individually or from the same hub. Total
640 wallets; the hub ends up funding 194 of them.

Metric: **pairwise** precision/recall. Entity resolution is a clustering problem and per-wallet
accuracy is meaningless at this base rate — every wallet is trivially "correct" as a singleton,
which is the same disease as reporting accuracy at a 98% base rate (§3 rule 5). A wallet the
resolver declined to place is scored as a singleton, so refusing to answer **costs recall** rather
than being silently excused (mutation 14 kills the test that pins this).

| seed | multi-wallet entities | largest | pair precision | pair recall |
|---|---|---|---|---|
| 1 | 42 | 6 | **1.000** | 0.687 |
| 7 | 42 | 6 | **1.000** | 0.685 |
| 99 | 42 | 6 | **1.000** | 0.738 |
| 20260813 | 40 | 6 | **1.000** | 0.762 |
| 424242 | 41 | 6 | **1.000** | 0.772 |

Cluster-size distribution at seed 20260813: `{3: 3, 4: 3, 5: 16, 6: 18}` — 40 entities over 209
wallets, largest 6, which is the planted ceiling. No entity exceeds its true size, which is the
same statement as precision 1.000 read from the other side.

**Source ablation** (seed 20260813, MELT's own framing — which source does the work):

| sources | wallets merged | pair recall |
|---|---|---|
| all three | 209 | **0.762** |
| first-funder only | 169 | 0.482 |
| bundles only | 115 | 0.383 |
| co-signing only | 36 | 0.030 |
| everything except first-funder | 138 | 0.425 |

First-funder is the largest single contributor, as MELT reports (~22.6% of holders / 28.2% of
supply against co-signing's 6.5% / 9.2%). The ordering here is an artefact of the generator's rates
as much as of the method, and should not be quoted as an empirical finding — it is reported to show
that no single source dominates and that the union is doing real work (0.762 against a best-single
0.482).

---

## 8. The bundle-adjusted minus naive top-10 delta

Implemented (`top10_delta`), tested, and **not computable on any data we hold**.

- Real store: 611 mints, **every one with exactly one holder**. Top-10 naive share = 1.0, adjusted
  share = 1.0, delta = 0.0pp for all 611. The number is a structural artefact of a wallet-indexed
  corpus, not a measurement, and quoting it would be exactly the error the tape contract's
  `WatchWindow` exists to prevent.
- Synthetic: 20 equal holders of which 11 are one entity gives naive 50%, adjusted 100%, delta
  **+50.0pp** — the arithmetic is pinned, including the guarantee that the adjusted share can never
  fall below the naive one over 50 random assignments (grouping only moves mass *into* the top k; a
  negative delta would be an arithmetic bug and it is the one direction the number can never
  legitimately go).

MELT's +24pp / +6pp separation needs per-token holder sets. Those come from Track B's recorder or
from MELT's archive, and the cost of building them from chain is §11.

---

## 9. Falsification matrix — 15 mutations, 15 dead tests

`studies/falsify_entity_resolution.sh` breaks the resolver on purpose and asserts the guarding test
goes red. A mutation that fails to apply is itself reported, so the matrix cannot go stale silently.

| # | mutation | guarding test | result |
|---|---|---|---|
| 1 | hub exclusion removed | `test_cex_hub_funding_thousands_…_does_not_collapse_them` | **FAILED (good)** |
| 2 | operator exchange list ignored | `test_operator_exchange_list_excludes_a_funder…` | **FAILED (good)** |
| 3 | super-cluster tripwire removed | `test_chained_sources_build_a_supercluster_that_is_suppressed` | **FAILED (good)** |
| 4 | suppressed component emitted anyway | `test_suppressed_wallets_are_absent_not_emitted_as_singletons` | **FAILED (good)** |
| 5 | first funder = latest, not earliest | `test_first_funder_is_the_earliest_by_slot…` | **FAILED (good)** |
| 6 | self-funding accepted as a link | `test_self_funding_is_not_a_link` | **FAILED (good)** |
| 7 | co-signing relay-hub rule removed | `test_relay_cosigner_hub_does_not_merge_its_customers` | **FAILED (good)** |
| 8 | Jito bundle-size cap removed | `test_bundle_over_the_protocol_cap_is_refused` | **FAILED (good)** |
| 9 | unsigned co-occurrence accepted by default | `test_unsigned_cooccurrence_is_refused_by_default` | **FAILED (good)** |
| 10 | sponsor edges trusted by default | `test_sponsor_edges_are_refused_by_default…` | **FAILED (good)** |
| 11 | `method` field collapsed to one value | `test_a_wallet_merged_by_two_sources_emits_one_record_per_method` | **FAILED (good)** |
| 12 | unassigned wallets pooled in the top-10 delta | `test_unassigned_wallets_are_their_own_entity_in_the_delta` | **FAILED (good)** |
| 13 | output made order-dependent | `test_resolution_is_deterministic_under_input_shuffling` | **FAILED (good)** |
| 14 | withheld wallets excused in scoring | `test_pairwise_scores_treat_a_withheld_wallet_as_a_singleton` | **FAILED (good)** |
| 15 | generator plants no unlinkable wallets | `test_planted_world_is_recovered_with_perfect_pair_precision` | **FAILED (good)** |

Mutation 15 is the one that guards the calibration itself: with `cex_withdrawal_rate` set to zero
the planted world contains nothing the CEX rule can lose, recall goes to 1.0, and the test that
asserts recall is *strictly below* 1.0 dies. A generator tuned to flatter the resolver is the
easiest way to fake §7, and this is the tripwire against doing it.

The suite additionally carries three in-suite teeth tests that do not need the harness: disabling
hub exclusion collapses planted-world precision below 0.2 with >1,000 false pairs; raising the
floor past the blob emits it whole; raising `hub_degree` past a hub trades merges for refusal while
precision stays at 1.000.

---

## 10. What is NOT validated

Stated plainly, because there is no ground truth in this field and §3 rule 7 says the threshold
travels with every number.

1. **No ground truth exists, and none of these numbers is precision against the world.** Pair
   precision 1.000 is precision against *our generator*. If real actors fund wallets through
   patterns the generator does not contain, the resolver's real precision is unknown — not high,
   not low, **unknown**. Every cluster is a CANDIDATE with a stated prior.
2. **`METHOD_CONFIDENCE` is a prior, not an estimate.** 0.95 / 0.80 / 0.60 encode how much key
   custody each observation implies. They have never been checked against a labelled set because no
   labelled set exists.
3. **The hub threshold is defended by a flat plateau, not by a measurement of exchanges.** 25 sits
   in the middle of a decade over which the answer does not move on the *planted* world. Whether
   real exchange fan-out and real bundler fan-out separate at 25 is untested.
4. **Adversarial evasion is untested.** An operator who funds each wallet from a distinct throwaway
   intermediary defeats first-funder entirely, and one who keeps every intermediary's fan-out below
   the threshold defeats the degree rule by construction. The tripwire converts that into a refusal
   rather than a false merge, which bounds the damage but does not detect the adversary.
5. **The bundle path has never seen a real bundle.** It is exercised only against synthetic rows in
   `shitcoims_tape.backfill`'s documented sidecar shape, and that shape is itself marked UNVERIFIED
   in `backfill.py`'s own docstring.
6. **`fee_payer` is read raw, outside the tape contract.** It has to be, because `Trade` has no such
   field. That read is confined to one clearly-labelled function returning a type that is not a
   `FundingEdge`, but it is still an out-of-contract dependency on the store's payload shape.
7. **Zero rows for two of three sources means those two code paths have no field exposure at all.**

**What would establish it.** Ordered by strength:

- **Labelled seeds.** A handful of *known* multi-wallet operators — our own wallets are the free
  one, since we know their true ownership, and a bundler whose wallets are identifiable from a
  public post-mortem is the next. Ten labelled actors give a real recall floor; they cannot give
  precision.
- **Precision by construction: a held-out custody fact.** Merge on funding alone, then check what
  fraction of the merged pairs *also* co-sign at some later date. Co-signing is near-definitional
  evidence of shared custody, so agreement between two independent sources is the closest thing to
  precision available without labels. It is a lower bound (co-owners need not ever co-sign) and it
  is computable the moment the tape carries signer sets.
- **A negative control on the same corpus.** Time-shuffle the funding edges — keep every wallet's
  in-degree, randomise who funded whom — and re-run. Any cluster structure that survives is an
  artefact of the estimator. This is the §3 rule 10 null and it costs nothing but CPU.
- **MELT's own archive.** It carries the bundle traces and its published holder/supply shares
  (6.5%/9.2% co-signing, 22.6%/28.2% funding) are a direct external check on whether our rates are
  in the right decade.

---

## 11. Credit arithmetic

Helius Developer: $49/mo, 10M credits. `getTransactionsForAddress` = **10 credits per 100 txs**.
The Enhanced API is 100 credits *per call* and is never used — parse raw.

Populating the funding sidecar needs each wallet's **oldest** inbound SOL transfer. Pagination runs
newest→oldest, so the cost is `ceil(tx_count/100) × 10` credits per wallet, and the final page
already carries the oldest transaction bodies — identifying the funder itself is free.

| scope | txs/wallet assumed | credits | share of the monthly plan |
|---|---|---|---|
| 6,000 wallets (30 tokens × ~200 holders) — **the right first spend** | 100 | 60,000 | **0.6%** |
| 6,000 wallets | 500 | 300,000 | 3.0% |
| 50,000 wallets (PROGRAM.md's figure) | 100 | 500,000 | 5.0% |
| 50,000 wallets | 200 | 1,000,000 | 10.0% — matches PROGRAM.md's estimate |
| 50,000 wallets, 5-page cap | 500 | 2,500,000 | 25.0% |
| re-deriving MELT's 218M txs | — | 21,800,000 | **218%** — 2.2 months of the entire plan |

Two operational points that are correctness, not cost:

- **Cap the walk, and record the cap.** A wallet that exhausts the page cap must be written as
  `first_funder_unknown`, never as "the oldest transaction we happened to see". Taking the oldest
  *observed* funder is displacement censoring wearing a different hat: it fabricates a first funder
  for exactly the long-lived wallets most likely to be exchange-adjacent.
- **MELT is free and already plumbed.** `shitcoims_tape.backfill.load_melt` writes bundle rows in
  the shape `load_links` reads. Importing the archive costs zero credits and is the only route to
  bundle ids at all, since they are not recoverable from chain.

---

## 12. What the next experiment should be

**Not** a bigger clustering run. In order:

1. **Put signer sets and `fee_payer` on the tape** (SWARM.md Track B gap 2). This is small, it is
   the difference between a refused relation and a 0.95-confidence one, and without it source #1 is
   permanently zero. It also unlocks the held-out-custody precision check in §10.
2. **Import MELT through `backfill.py` and run this resolver against it.** Zero credits, real
   bundles, and MELT publishes the holder/supply shares each source should recover — the first
   opportunity this method has to be *wrong* about something external.
3. **Then the 6,000-wallet funding fetch (0.6% of the plan)** over the tokens Track B is already
   recording, and compute the real bundle-adjusted-minus-naive top-10 delta. The pre-registered
   prediction is MELT's: roughly +24pp on high-risk tokens against +6pp on low-risk ones. If the
   delta comes back near zero on both, either the resolver is not finding the coordination or this
   market's coordination does not look like MELT's — and distinguishing those two is exactly what
   step 2 is for.
4. **Run the funding-edge shuffle null on the same corpus** before quoting any cluster statistic.

One line for whoever picks this up: the resolver's failure mode has been engineered to be
*refusal*, not error. Every threshold in the sweep holds pair precision at 1.000; what the knobs
move is how much the instrument declines to say. If a future run reports a large entity, the thing
to check first is not the threshold — it is whether the tripwire was disarmed.
