# Lane 04: fancoin, community, and social-transition observatory

Status: pre-engineering research, protocol facts checked 2026-08-16.

## Question and position

The strategy hypothesis is not "coins whose creators claim fees go up." It is:

> Can we recognize an unofficial coin and its surrounding community becoming likely to earn
> the attention, economic acceptance, participation, or audience of the person it depicts
> before that transition is fully reflected in executable price and liquidity?

That is a coherent research direction. It is also unusually easy to study incorrectly. A fee
movement is not necessarily a human action; a platform-authorized social claim is not necessarily
an endorsement; a public mention is not necessarily durable participation; and the person may
arrive only after the coin has already appreciated. The data system must preserve those
distinctions instead of manufacturing one `creator_claimed` Boolean.

This lane recommends an event-sourced **identity, community, and transition observatory** shared
by the fancoin book and the rest of JOSHI. It does not recommend an automated fancoin trading
policy yet. Its first job is to make the actual transition sequence prospectively observable.

## Protocol semantics: what an event does and does not prove

The following are observations from Pump's official public documentation and current IDLs, pinned
to public-docs commit `9c82f61` (2026-07-16). Product-language meanings beyond the IDL are marked
as inference.

| observed event or state | protocol fact | safe interpretation | unsafe interpretation |
| --- | --- | --- | --- |
| coin `creator` field | `create_v2` accepts any non-default public key as `creator` | the address was placed in the coin's creator-routing field at creation | the depicted person deployed, approved, or even knows about the coin |
| ordinary bonding-curve or AMM creator-fee sweep | current collection instructions are permissionless; anyone can trigger payment to the configured creator | accrued fees were transferred to their configured destination | the creator personally claimed, noticed, or endorsed the coin |
| fee-sharing config created | the current coin creator or Pump's `admin_set_creator_authority` may opt a coin into a `sharing_config`; the coin's creator fields then point at that PDA | fee routing/admin state changed | a represented person accepted the coin |
| fee shares finalized | the sharing-config admin sets up to ten shareholders; the current implementation finalizes the list and revokes further admin updates | an authorized routing configuration became final at that point | every shareholder signed, consented, or promoted the coin |
| shared fees transferred or distributed | both AMM-to-Pump transfer and shareholder distribution are permissionless | value was mechanically swept/distributed under the current config | a shareholder took a public action |
| social-fee PDA created | the IDL requires a paying signer but no `social_claim_authority` signer; the event records platform, user ID, PDA, and `created_by` wallet | a fee destination for a platform/user identifier exists | that social identity was verified or aware |
| `SocialFeePdaClaimed` | the claim requires the configured `social_claim_authority` signer; the recipient is writable but not a signer; the event records platform, user ID, recipient, authority, amount, quote mint, and balances | Pump's configured authority authorized a payment for that platform/user identity to that recipient at that time | an on-chain signature directly from the depicted human, an enthusiastic endorsement, or a coin-specific causal catalyst |
| public post, reply, stream, profile link, or repeated participation | attributable content may show awareness or participation if identity evidence is strong | the identified account performed the particular observed act | ownership of every similarly named account, economic commitment, or durable community adoption |

Two consequences are central:

1. **Ordinary fee collection cannot be used as a creator-intent event.** The official docs state
   that both single-recipient collection instructions are permissionless. The same is true of
   shared-fee transfer and distribution.
2. **A social claim is platform-authorized, not self-authenticating.** The Pump Fees IDL shows
   the `social_claim_authority` as signer and the recipient as non-signer. The chain proves what
   the configured authority authorized and paid. It does not reveal the off-chain verification
   ceremony, prove subjective awareness, or establish public endorsement.

The claim event contains no mint. A social identifier or recipient may in principle be referenced
by more than one coin or fee route. Therefore `person P claimed coin C` must never be inferred from
the claim transaction alone. It requires a point-in-time reconstruction of the coin's creator,
sharing config, shareholders, social-fee destination, and quote asset. Whether current Pump launch
modes aggregate multiple coins into one social-fee balance is an empirical protocol-mapping
question that must be resolved from real transactions before any per-coin claim label is shipped.

Pump's terms also describe a community takeover (CTO) as a separate discretionary process in
which creator fees and some admin rights can be handed to a community-selected team or person.
A CTO, ordinary creator routing, shared fee routing, and a social-recipient claim are four distinct
mechanisms even if the UI renders them with similar language.

## Do not force this into a monotone stage number

A useful verbal sketch remains:

```text
unofficial reference
  -> community aggregation
  -> subject awareness
  -> platform-authorized social claim
  -> public acknowledgement or participation
  -> audience arrival
  -> persistence, fragmentation, migration, or decay
```

But this is not the data model. Real sequences can permute or branch:

- a subject can mention a coin before claiming fees;
- an authority can approve a claim without any public mention;
- an audience can arrive because of third-party virality before the subject notices;
- a subject can participate briefly and then withdraw;
- the audience can split across duplicate coins;
- one coin can inherit attention from a predecessor while another receives the fees;
- a CTO can change admin/fee state without changing the represented subject;
- a public account can be compromised, renamed, or impersonated.

The primitive representation should be immutable facts plus temporal relations. A derived state is
a versioned vector, not one enum:

| facet | example values; all retain evidence and uncertainty |
| --- | --- |
| depiction/target | unknown, hypothesized person, strong semantic match, explicit platform/social ID |
| identity evidence | name only, linked numeric account ID, Pump wallet link, platform-authorized claim, signed/public cross-link |
| fee relationship | none seen, direct creator, social destination, sharing config, CTO, cashback, unknown/drifted |
| awareness | no evidence, weak exposure, direct reply/like, explicit acknowledgement |
| participation | none, one-off mention, repeated posts/replies/streaming, operational involvement |
| endorsement | explicitly disclaimed, ambiguous, positive public support, revoked/contradicted |
| community | sparse, aggregating, coherent, coordinated, contested, migrating, decaying |
| audience transfer | none measurable, first arrivals, accelerating, saturated, reversing |
| duplicate competition | unique seen, unresolved family, provisional leader, fragmented, winner migrated |
| market capacity | untradeable, bonding curve, graduated, shallow, executable at Ember's size, stale/unknown |

Derived phrases such as `likely creator-aware` or `community coalescing` are interpretations. They
must carry algorithm/model version, inputs, production time, and confidence; they must never
overwrite the events that produced them.

## Minimal temporal identity graph

### Entities

- coin mint, bonding curve, canonical pool, deployer, current and historical creator-routing
  addresses, sharing configs, and shareholders;
- represented subject, which may be a person, project, trend, fictional character, or institution;
- platform identity `(platform, numeric user_id)`; handle/display name is an attribute with a
  history, not the identifier;
- Pump user UUID, Pump wallet, recipient wallet, author wallet, and follow-graph wallet;
- community, post, reply, callout, media object, stream, mention, and external social post;
- a **coin family**: all contemporaneous coins believed to compete for the same subject or
  narrative, including uncertain members;
- operator episode, attention event, disposition, annotation, and retrospective interview.

### Temporal relations

Examples include `coin_depicts_subject`, `account_represents_subject`, `wallet_controls_profile`,
`coin_routes_fees_to`, `social_destination_authorized_recipient`, `author_participates_in_coin`,
`audience_member_arrives_at_coin`, and `coin_competes_with_coin`. Every relation needs:

- `valid_from` and `valid_to` when the underlying relationship is mutable;
- `t_event`, when the source says it happened;
- `t_observed`, when JOSHI could first have known it;
- source class, source locator, raw payload/hash, and collection status;
- assertion type: protocol fact, first-party statement, third-party attribution, human label, or
  machine inference;
- confidence and, where appropriate, a contradiction relation.

The two-clock minimum from `PROJECT.md` is not enough for enrichment that arrives late. A later
identity resolver may tell us that an old numeric ID belonged to an account, but a replay at the
old decision time may use only evidence whose `t_observed` was already available. Store the later
fact without leaking it backward.

### Identity evidence hierarchy

No universal scalar score is trustworthy, but the UI needs an ordered evidence vocabulary:

1. name, ticker, image, or prose resemblance only;
2. metadata links to a handle or URL, unverified and deployer-controlled;
3. Pump content object links author wallet and stable external numeric ID, as attributed by the
   social backend;
4. Pump profile and social-backend mappings agree on wallet/user identity at the same observed
   time;
5. Pump's social claim authority authorizes a payment for a platform/user ID to a wallet;
6. the subject's established public account cross-links the coin, mint, Pump profile, or recipient
   wallet;
7. repeated first-party participation corroborates the relationship over time.

Evidence can conflict. A platform-authorized payment is stronger economic identity evidence than a
coin image, but it is still not the same predicate as public endorsement. A numeric X ID survives a
handle rename and is therefore preferable to a handle as a join key; account compromise or control
transfer remains possible and must be expressible.

## Candidate census and duplicate competition

The denominator must begin with all Pump coin creations, not claimed coins, successful coins, or
coins Ember happened to inspect. Build the prospective census from on-chain creation events and
snapshot the creation transaction, metadata bytes, URI, media hashes, creator-routing state, and
first observable market/social state.

Candidate discovery should be deliberately high-recall:

- **protocol-explicit:** a social-fee PDA or known social recipient appears in a point-in-time fee
  route;
- **metadata-explicit:** social URL, stable numeric ID, handle, person/project name, or first-party
  link appears in the metadata;
- **semantic:** name, description, posts, image, or media appear to depict a person/project;
- **behavioral:** community members repeatedly mention or address a subject, or several mints
  compete for the same audience;
- **operator-nominated:** Ember marks a coin/family as a fancoin candidate, including a free-form
  reason or `not articulable`.

The semantic and behavioral classifiers are discovery annotations, not truth. Preserve low-score
and rejected candidates so false negatives can be estimated later.

Duplicate resolution is itself a market process, not data cleaning. Group possible duplicates by
stable target identity when available, then by social URL, text/image/media similarity, symbol,
deployer relations, launch-time proximity, community overlap, and explicit audience migration.
Never choose a canonical coin by ticker, current market cap, or eventual success. Store family
membership probabilities and the evidence available at each time. Outcomes belong at both coin
and family level: a correct subject thesis can still lose if capital entered the duplicate that
the audience abandons.

## What the existing Pump social corpus contributes

The `joshibot` `shitcoims_pumpsocial` package is valuable compost, not yet this subsystem.
Its 2026-08-15 mapping establishes:

- per-coin community headers with post count, member count, likes, and latest activity;
- comments, public callouts, and readable callout replies with event/ingest clocks;
- native author wallets on content objects, plus Pump user IDs and often stable X numeric IDs;
- wallet-to-Pump/X identity routes and Pump profiles;
- a live, wallet-keyed callout firehose;
- timestamped **outgoing** follow edges;
- coin metadata including a current `creator` field.

It also establishes limitations that must survive into the new design:

- `api.coin-communities.xyz` is a third-party host; its wallet attribution is a provider claim,
  not chain evidence;
- comment replies are countable but not publicly readable, so the reply tail is censored;
- the cross-coin public feed was observed stale by days and cannot be used as a realtime trigger;
- profile follower counts and post follower counts are read-time snapshots, not historical facts;
- the follower graph exposes outgoing edges only; observed in-degree depends on which roots were
  crawled;
- a full page with no cursor can be truncation rather than completion;
- `userId` means a UUID on one backend and a wallet on another;
- `/coins/{mint}` returns today's mutable creator state and cannot be backfilled into old scenes;
- current callout multiplier/peak fields use future information and are outcomes, never inputs.

The local records already preserve `t_event`, `t_ingest`, author wallet, numeric social ID,
mentions, parent relations, moderation flags, media URL, and deletion time. Those shapes should be
selectively grafted into the new event tape. The reverse-engineered endpoint catalogue and public
browser key are unsupported surfaces: retain dated health probes, raw responses, explicit
partial/failed status, and a replacement path if the provider changes.

External first-party social activity remains a real dependency. Pump-native posts can show
participation inside Pump; they cannot establish what the subject said on X, a livestream, or
another social venue unless that source is independently archived with its own clocks and terms.

## Prospective study design

### Research questions in order

1. **Observability:** Can we reconstruct the fee, identity, community, duplicate, and public-action
   sequence without using information learned later?
2. **Transition dynamics:** Among candidates at risk, what observable configurations precede each
   kind of next event: claim, acknowledgement, participation, audience arrival, fragmentation,
   migration, or decay?
3. **Operator value:** Do Ember's attended, nominated, or armed candidates transition differently
   from the contemporaneous candidates shown but skipped, after preserving the actual choice set?
4. **Tradability:** At the time a transition was foreseeable, was there a size-specific executable
   entry and later exit with useful capacity after fees, impact, latency, and failure risk?
5. **Scaling:** How do transition rate, execution quality, and return distribution change as the
   candidate set expands beyond Ember's top few choices?

Only after questions 1-4 work should this lane propose a predictive policy.

### Risk sets and competing events

At each time `t`, construct a risk set from all prospectively known candidate coins/families that
have not yet experienced the event in question. Estimate cause-specific, time-varying hazards for
distinct events rather than treating every non-claim as a negative label. A coin that is still
unclaimed when collection ends is right-censored; one that loses its audience to a duplicate has
experienced a competing event; a coin discovered after launch is left-truncated.

Useful empirical questions include:

- conditional on evidence available at `t`, what is the distribution of time to first
  platform-authorized social claim?
- what predicts first public acknowledgement separately from fee claim?
- after acknowledgement, what predicts repeated participation rather than a one-off mention?
- when do unique community authors, repeat authors, reply structure, follow relations, and audience
  overlap indicate coherence rather than spam volume?
- which member of a duplicate family receives incremental attention, liquidity, and first-party
  participation, and when does leadership switch?
- how much does Ember's nomination change the base-rate distribution relative to the candidates
  concurrently visible in the product?

### Endogeneity and causal limits

A descriptive event study around claim time is worth running, but it cannot answer whether claims
cause appreciation. The subject or platform is likely to authorize a claim because the coin has
already accumulated attention and fees. Price, volume, community growth, and the claim are jointly
determined. Pre-trend plots should make that visible rather than wash it away with one before/after
mean.

The actionable forecast question is prospective: can pre-claim state predict a claim or stronger
social transition early enough to leave executable upside? Use chronological evaluation, time-local
matched risk sets, and all unsuccessful candidates. Never train or select features on eventual
claimants only. Never use current profiles, current creator fields, eventual peaks, future content
moderation, or later identity enrichment as if they had been known at the entry time.

Claims may be bundled or aggregated across fee routes; public content may be deleted; API snapshots
may arrive late; Pump may change its claim verification process. Missing events are `unknown`, not
`false`. Every analysis must report collection coverage and source health by time interval.

### Outcomes

Market outcomes should include the whole conditional distribution, not a peak multiple:

- executable net return at specified decision rules and horizons;
- maximum realizable size before an impact cap;
- time to liquidity/graduation and duration of usable exit capacity;
- adverse excursion, drawdown, gap risk, and probability of becoming unexitable;
- realized clips plus retained-runner value over the full operator episode;
- persistence of unique community participation and audience overlap;
- fragmentation/migration among duplicate coins;
- operator attention time and opportunity cost.

Peak-at-any-future-time statistics are useful for describing latent upside but are not realizable
returns and cannot score an entry policy.

## Evidence-oriented UI

The product should avoid a celebratory green `CLAIMED` badge. It should render exact predicates:

| UI element | contents |
| --- | --- |
| subject card | stable platform IDs, current and historical handles, evidence level, conflicts, last observation |
| coin-family strip | every competing mint, exact CA, launch time, fee route, attention/liquidity share, provisional leader, unresolved members |
| transition timeline | social-PDA creation, routing changes, ordinary sweeps, social claims, CTO events, posts/replies/streams, audience changes, Ember gestures |
| event badge | e.g. `FEE SWEEP — ANYONE CAN TRIGGER`, `PUMP-AUTHORIZED SOCIAL PAYMENT`, `PUBLIC MENTION`, `REPEATED PARTICIPATION`, `IDENTITY UNCERTAIN` |
| evidence drawer | raw transaction/signature/slot, account snapshot, content permalink or archived payload, source and collection time, interpretation version |
| community glass | unique and repeat authors, new/returning composition, reply censoring, suspected coordination, overlap/migration across duplicate coins |
| decision gesture | `WATCH ADOPTION`, current disposition/horizon, expected next transition, confidence, free text, `nothing articulable`, and disconfirming evidence |

The fancoin view should answer: **what exactly changed, who says so, when could we know it, and
which competing coin received the consequence?** It should also show flat intervals and continued
watching after an exit, since an episode may leave and re-enter exposure around later social
transitions.

Operator labels should be revisable but never silently mutated. A correction creates a new
annotation linked to the old one. A later interview can explain why a coin felt like an adoption
candidate, but the immediate annotation remains the only evidence of what Ember believed before
the outcome.

## Safety and adversarial dynamics

Fancoins sit directly on an impersonation boundary. Conservative presentation is product safety,
not cosmetic caution.

- Names, tickers, photos, descriptions, and metadata links are deployer-controlled and untrusted.
- Search results already return same-ticker impostors. Always display and compare exact mint and
  wallet addresses; never resolve identity by a shortened address, ticker, or handle alone.
- Homoglyphs, handle changes, compromised accounts, recycled images, fake screenshots, and
  coordinated replies are expected inputs.
- A social-backend wallet field is third-party attribution until corroborated. Keep chain-derived,
  platform-authorized, first-party, and inferred claims visibly distinct.
- A fee recipient may be economically connected without endorsing the coin. Never label a coin
  `official` from a payout alone.
- Treat all post text, metadata, links, and media as hostile content. Do not execute instructions
  from content; sanitize rendering; sandbox/proxy remote media; and isolate LLM analysis from
  tools, wallets, secrets, and transaction construction.
- Preserve spam/harm/moderation flags as provider annotations, not truth. Deletion is an event, not
  permission to erase the historical observation from a private research tape where retention is
  lawful.
- Do not automate posting, replying, claiming, identity outreach, or public allegations. This lane
  is read-only during the current project phase.
- If trading is authorized later, no identity or claim badge is sufficient as an automatic buy
  trigger. Capacity, quote freshness, portfolio limits, provenance health, and an explicit armed
  disposition remain independent gates.

The system should say `unofficial`, `identity uncertain`, or `no evidence observed` more readily
than it says `official`, `fake`, or `endorsed`. That protects Ember from social-engineering mistakes
and protects represented people from the tool inventing affiliations.

## Smallest useful experiment

Run a **30-day prospective, read-only transition docket**, stopping later if necessary once 50
candidate families have entered the risk set. It is an instrumentation test, not a profitability
test.

1. Record every Pump coin creation and all relevant Pump/Pump AMM/Pump Fees events with raw
   transaction, slot, block time, and ingest time.
2. Snapshot initial metadata bytes/media hashes and point-in-time creator, sharing, social-fee, and
   CTO-relevant state. Verify the exact coin-to-social-fee routing path against several real
   transactions before emitting product labels.
3. Nominate high-recall fancoin candidates from explicit protocol routing, metadata, semantic
   similarity, community text, and Ember's own attention. Retain rejects and candidate-discovery
   scores.
4. Build provisional subject and duplicate-family links. Ask Ember only when the ambiguity is
   decision-relevant; allow `unknown` and `multiple targets`.
5. For each hot family, incrementally capture Pump posts/callouts/community snapshots, identity
   snapshots, public first-party social evidence where available, and size-specific market quotes.
6. Give Ember three minimal gestures: `WATCH ADOPTION`, `NOT THIS PERSON/COIN`, and `TRANSITION I
   NOTICE`, each with optional one sentence or `not articulable`.
7. At the end of each resolved or abandoned watch, replay the evidence and record a retrospective
   account separately from the immediate labels.
8. Produce event dossiers for claimed, publicly acknowledged, fragmented, migrated, decayed, and
   still-censored cases. Do not require each class to occur; absence with measured coverage is a
   result.

Success criteria for this slice are:

- a reviewer can reconstruct what was known at any decision time without querying today's state;
- ordinary sweeps, shared distributions, social claims, and public actions are never conflated;
- every claim-to-coin attribution has a visible routing proof or is marked unresolved;
- duplicate families and missed/failed collection are visible rather than cleaned away;
- Ember can capture a transition judgment with low enough friction to do it during real use;
- the tape can replay both an attended candidate and its contemporaneous alternatives.

This experiment should not spend capital, declare edge, fit an LLM trading model, or estimate a
claim effect from a handful of successful stories.

## Failure modes and kill conditions

This lane should be narrowed or stopped if prospective evidence shows any of the following:

- the coin-to-social-recipient relation cannot be reconstructed reliably at decision time;
- the public claim process changes faster than source health/versioning can track it;
- first-party participation cannot be captured until after the market move at useful latency;
- candidate discovery misses most operator-recognized fancoins and cannot be improved without
  unavailable/private data;
- duplicate migration makes coin-level exposure indistinguishable from roulette at executable
  horizons;
- social events occur but available liquidity cannot support Ember's intended size and exit;
- the UI cannot express uncertainty without encouraging mistaken `official`/`endorsed` beliefs;
- prospective transition base rates are too low to learn anything on a tolerable time horizon.

These would not invalidate the shared identity/community tape. They would invalidate or defer the
fancoin trading thesis in its current form.

## Dependencies on other lanes

- **Canonical event tape:** multi-clock provenance, immutable raw records, source-health intervals,
  content/media snapshots, derived-annotation versioning, and replay.
- **Whole-market census and attention:** all creates, Pump-like boards/ranks, viewport and candidate
  choice sets, Ember's inspect/dismiss/watch actions.
- **Protocol/account resolver:** Pump, PumpSwap, and Pump Fees IDL decoding; point-in-time account
  snapshots; creator/share/social/CTO routing graph; chain reorg/finality handling.
- **Market/execution glass:** trades, reserves, dynamic fees, size-specific quotes, capacity, and
  realistic shadow entries/exits.
- **Identity and external-social ingestion:** numeric-ID history, Pump profiles, first-party posts,
  streams and links, source terms, deletion/moderation handling.
- **Community analysis:** unique/repeat authors, temporal reply structure with known censoring,
  follow-graph sampling, coordination/spam hypotheses, cross-coin audience overlap.
- **Multimodal retrieval/LLM annotations:** person/project depiction, duplicate discovery, discourse
  summaries, and analogous scenes; all recomputable and prompt-injection isolated.
- **Episode and annotation UI:** changing dispositions, flat watch intervals, re-entry, immediate
  notes, eventual zap interviews, and family-level outcomes.

## Unresolved protocol and product questions

1. What exact off-chain identity proof causes Pump's social claim authority to authorize a
   recipient, and can the procedure or recipient change across claims?
2. What are the complete current platform enum meanings beyond the IDL's examples `0=pump,
   1=twitter, etc.`?
3. How do every current launch mode, CTO path, charity route, cashback mode, and fee-sharing path
   connect a mint to a social-fee PDA? Which path does the Pump UI call a "fancoin"?
4. Are social-fee balances shared across multiple coins for one platform/user identity? If so,
   what attribution, if any, does Pump's UI apply to a claim amount?
5. Does the current frontend expose a point-in-time claimable recipient/target relation that is
   absent from the mapped coin response, or must it be reconstructed wholly from chain state?
6. Can public Pump community membership be incrementally observed, or only current aggregate count
   and per-user community membership?
7. What compliant, sufficiently realtime source should archive first-party X and livestream
   actions? Pump's numeric-ID join does not itself supply external posts.
8. How often are metadata URIs mutable HTTP resources rather than content-addressed objects, and
   what media-retention policy is appropriate?
9. Which Ember-observed examples define the boundary between a fancoin, a trend coin, a parody,
   and a generic reference? The ontology should be learned from prospective cases, not guessed now.

## Sources

Primary/current sources:

- Pump, [Coin Creation Accounts](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/instructions/COIN_CREATION.md#instruction-data), especially the arbitrary non-default `creator` argument.
- Pump, [Collect Creator Fee](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/instructions/COLLECT_CREATOR_FEE.md), documenting permissionless bonding-curve and AMM sweeps.
- Pump, [Creator Fee Sharing](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/instructions/CREATOR_FEE_SHARING.md), documenting config authority, creator-field migration, one-time share finalization, and permissionless distribution.
- Pump, [Pump Fees IDL](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/idl/pump_fees.json), especially `claim_social_fee_pda[_v2]`, `create_social_fee_pda`, `SocialFeePda`, `SocialFeePdaClaimed`, and `SocialFeePdaCreated`.
- Pump, [Fees](https://pump.fun/docs/fees) (last updated 2026-05-20), for current fee categories and the distinction between coin creator and CTO fee owner.
- Pump, [Terms and Conditions, section 4.6](https://pump.fun/docs/terms-and-conditions), for Pump's description of creator fees, shared routing, cashback, and CTOs. This is product/legal language, not protocol proof.

Local measured sources, all in the `joshibot` compost repository:

- `shitcoims_pumpsocial/endpoints.py`, particularly lines 140-205 and 288-403: dated endpoint
  semantics, mutable coin creator warning, community/content/identity routes, and known traps.
- `shitcoims_pumpsocial/models.py`, particularly lines 140-280 and 402-507: numeric social IDs,
  author-wallet records, read-time follower counts, post clocks, and profile joins.
- `shitcoims_pumpsocial/crawl.py`, particularly lines 44-65 and 105-247: explicit missingness,
  truncation, and censored reply accounting.
- `studies/RESULT_pump_social_api.md`: 2026-08-15 measured surface map, provenance caveats, live/dead
  routes, wallet/X joins, reply censoring, follow-graph asymmetry, and callout-score leakage.

The current Pump social product behavior is only partially documented in primary prose. Where this
lane interprets the social-fee IDL as a platform-authorized identity/payment transition, that is a
bounded inference from signer/account/event structure—not a claim about Pump's undisclosed
off-chain verification procedure.
