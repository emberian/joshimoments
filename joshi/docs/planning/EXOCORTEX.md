# The exocortex journal

Status: planning + first honest slice, 2026-08-22. This plan grants no trading, signing, wallet,
or autonomous economic authority; every act described here is `evidence_only` / `observe_only`
through the frozen operator command contract.

The ask, in Ember's words: *"'on this day we discussed this about these charts' should be
something that gets stored inside joshi as a sorta evolving journally exocortex."* This morning a
DREGG/SOLVE LP band was analyzed against ten days of corpus data, with her scenario views said out
loud — "SOLVE likely rips 0-60%, DREGG probably stays 300-500K with an unlikely spike to 700K+
because Dragon's Clutch is in release prep" — and all of that reasoning lives only in a chat
transcript. When the position resolves in three weeks, nothing in JOSHI will remember why it was
entered. `docs/reference/SESSION_HISTORY.md` is the standing proof of what that costs: a steering
trail that had to be excavated from 13,244 stored messages after the fact. The exocortex exists so
that reconstruction never has to happen again.

## 1. What a journal entry IS

**A journal entry is an ordinary durable operator command whose words are carried verbatim in its
frozen capture context.** It is not a new table, not a new wire kind, not a parallel store, and not
a form. The command ledger in `crates/joshi-store` (the `command` table plus content-addressed
payload blobs, written only through `SqliteStore::commit_operator_v1`) already has every property
the journal needs and has already paid for them:

- **Words, verbatim.** `context.note` (up to 4,000 UTF-16 units) and `context.whyNow` (800) hold
  her language exactly as uttered. A blank note is refused at intent construction
  (`apps/glass/src/operator/holds.ts` precedent) — an empty entry is never stored where words
  belong, because a later reader would take the blank as "she had nothing to say."
- **Scene binding.** Every command names `{sceneId, viewDigest}` and admission refuses the act
  unless those bytes hash to what the store retains (`commit_operator_v1` re-reads and re-hashes).
  "These charts" is therefore not a description — it is the exact served bytes.
- **Mint binding.** The command subject is typed: `{kind: "candidate", key: <mint>}` for a
  coin-directed utterance (admission proves the candidate was in the exact scene), or
  `{kind: "scene", key: <sceneId>}` for an utterance about the whole discussion.
- **Dates and clocks.** `issuedAt` (client wall clock), the client monotonic pair, and the store's
  `receivedAt`/commit sequence. "What happened on Aug 22" is a query over clocks the ledger
  already keeps.
- **Restart-proven durability.** `apps/core/src/live_gesture.rs` already proves acts survive
  process death bound to the same scene bytes.
- **Append-only correction.** A wrong entry is answered by `compensate_command`, never by edit or
  delete. The journal keeps what was believed *and* the later retraction, which is precisely what
  makes it evidence about her reasoning rather than a wiki.

The discriminator that makes a `record_focus` a *journal entry* rather than a hold is the frozen
UI label, exactly as `HOLD_UI_LABEL` already works:

- `"Journal entry"` (`JOURNAL_UI_LABEL`, version 1) — words about a subject, in
  `context.note`.

Other frozen kinds are journal entries too, and render in the same timeline without any label
convention: `record_disposition` and `record_crackle_family` (provisional stances),
`record_annotation` (words anchored to a chart point/range), `record_gesture`,
`record_post_action_report`, `link_interview`, and the hold/hold-note pair. The journal is a
**reading** of the operator ledger, not a sibling of it.

Iron law honored: operator acts and raw utterances precede any fixed taxonomy. No category field,
no tag vocabulary, no "entry type" dropdown exists in v1 or is planned. Structure, if it ever
comes, will be derived later from the words — never demanded at capture time.

## 2. How entries are captured

1. **By Ember, in Glass, today.** The hold (`;`) plus the hold-note form already capture "this
   coin, and later, why." This slice adds one composer to the journal surface: a textarea that
   commits `record_focus` with subject `{kind: "scene", key: sceneId}` and label
   `"Journal entry"`. Same route (`POST /api/v1/operator/commands`), same pending-queue retention,
   same refusal of blank words. Nothing is required at the moment of noticing.
2. **By the primary agent, in conversation.** The agent holds a paired capability (the launcher
   prints a one-time code; `joshi-core live-surface-inspect` / `serve` issue scopes) and POSTs the
   same canonical command bytes the browser sends — the route does not care who typed. "On this
   day we discussed X about these charts" becomes one or several scene-bound `record_focus`
   commands whose `context.note` is the agreed sentence, written while the scene that was
   discussed is the one being served. No agent-specific wire shape exists; an agent entry is
   distinguishable by its `clientSessionId`/`clientClockId`, not by privilege.
3. **Eventually, by an embedded agent.** A sibling deputy is designing that lane. The contract
   this plan fixes for it: the embedded agent writes through the identical command route with its
   own session identity, and everything it writes reads back through the identical read route.
   Nothing here needs to change for that lane to land.

## 3. How entries are read back

**One route serves both the journal and the held rail's known gap** (a hold was invisible after
reload, and the rail said so on screen):

```
GET /api/v1/operator/commands?sceneId=<sceneId>
```

- Authorization mirrors the snapshot route: ordinary pairing `cockpit_read` scope when ordinary
  pairing is mounted; the same fail-closed posture checks; loopback only.
- Backed by the store query that already exists and is already restart-proven:
  `SqliteStore::operator_commands_for_scene_v1` (`crates/joshi-store/src/live_observation.rs`),
  which returns every durable command bound to one immutable scene in commit order, with **exact
  retained payload bytes**. The route splices those bytes into the response unre-encoded, the same
  way the Cockpit V2 open route serves exact stored bytes.
- Two absences are kept apart, matching the venue-readout precedent: an unknown scene is
  `404 scene_not_found`; a scene this process is serving but no act has yet made durable answers
  `200` with `sceneRetention: "served_not_yet_durable"` and an empty list. An empty list is never
  rendered as "nothing was said" — the surface states which of the two it was told.

The two remembered questions and what they wait for:

- **"What did we say about SOLVE?"** — a subject-keyed listing across scenes.
- **"What happened on Aug 22?"** — a received-time-window listing across scenes.

Both need one store query that does not exist, and `crates/joshi-store` is read-only for this
slice, so it is specified here for the primary to sequence (§5). The v1 surface says this scope
limit out loud instead of pretending the per-scene answer is the whole journal.

## 4. The v1 surface in Glass

`apps/glass/src/components/JournalRail.tsx`, mounted in the right rail of the ordinary cockpit:

- **Entries in time order**: durable commands for the served scene (commit order, from the read
  route) merged with this browser session's acts (insertion order), deduplicated by `commandId`
  with the durable record winning.
- **Each entry shows**: its own words verbatim (`note`, `whyNow`, and the kind-specific stated
  fields — disposition, crackle family, nomination, gesture label — exactly as stored), its frozen
  label, its subject (`candidate`/mint or `scene`), its scene binding, its client clock, and — for
  durable records — `receivedAt` and the commit sequence. Local-only acts show their retention
  state in the same vocabulary the held rail uses; "committed" is claimed only with a commit seq.
- **Explicit absences, never blanks**: offline-fixture cockpits state that no durable catalog
  backs them; a failed read states the failure and keeps the session view; an empty durable list
  states whether the scene is durable or served-not-yet-durable; the per-scene scope limit is
  stated on the surface.
- **Keyboard and screen reader**: reachable in normal tab order, focusable (`tabIndex={-1}` +
  `id="journal"`), a Command Palette entry ("Open the journal") and **zero new single-letter
  shortcuts** — six of the eight existing ones already collide with NVDA/JAWS quick-nav and this
  surface must not add a seventh. The composer refuses blank words with a `role="alert"` reason.
- A **"Read the catalog again"** button re-queries the route, which is how entries written by the
  primary agent mid-session become visible without a reload.
- The held rail's on-screen honesty text is updated: it no longer claims "the core serves no route
  for that," and instead points at the journal, where a catalog-accepted act for this scene is now
  actually visible after reload.

## 5. Deliberately NOT in v1

- **No cross-scene or cross-catalog listing.** Needs a store query `joshi-store` does not have.
  Precise specification for the primary to sequence, mirroring
  `operator_commands_for_scene_v1`'s shape and refusal style:

  ```rust
  /// Reads durable operator commands in commit order, optionally filtered by exact
  /// subject key and/or an inclusive received-at window, with an explicit
  /// truncation marker (never a silent cut).
  pub fn operator_commands_v1(
      &self,
      subject_key: Option<&str>,          // "what did we say about SOLVE" (exact mint key)
      received_from: Option<UtcTimestamp>, // "what happened on Aug 22" (day start)
      received_until: Option<UtcTimestamp>,
      limit: usize,                        // page bound; truncated flag like
                                           // DurableSourceObservations::truncated
  ) -> Result<(Vec<StoredOperatorCommandV1>, bool /* truncated */)>;
  ```

  With it, the same core route grows `?subjectKey=` / `?receivedFrom=` / `?receivedUntil=`
  parameters and the same wire shape; nothing in the Glass reader changes except the query.
- **No restoration of the held rail's cards from durable read-back.** `StoredOperatorCommandV1`
  does not carry `issued_mono_ns`, so a byte-faithful `OperatorCommand` cannot be reconstructed in
  the browser, and the rail's retention vocabulary (`holdRetention`) is defined over session
  entries. Either the store read-back grows that column's value (a one-line store change, also for
  the primary) or the rail learns a durable-record shape. The journal makes the reloaded hold
  visible meanwhile; the rail says exactly what it still does and does not cover.
- **No taxonomy, tags, categories, or entry templates.** Iron law.
- **No editing or deletion.** `compensate_command` is the only correction, rendered as its own
  entry.
- **No search, no summarization, no LLM digest.** Reading words is v1; deriving anything from them
  is not.
- **No embedded-agent capture.** Sibling deputy's lane; the route contract above is what it plugs
  into.
- **No "current scene" pointer and no live stream.** The journal reads immutable scenes by name,
  exactly like every other Glass read.

## 6. Restart proof

`apps/core/src/live_journal.rs::run_live_journal_walk` mirrors the live gesture walk: mount a real
catalog copy, pair, serve the scene, commit a hold **and** a journal entry with real words through
the ordinary route, then drop the router, launcher, and writer; reopen the catalog read-only in a
fresh service; GET the read route; and refuse unless the exact words, subject, scene digest, and
commit sequences come back. The walk is a test in the `joshi-core` gate and a CLI subcommand
(`live-journal-walk`), so the proof is runnable against a real catalog, not only the fixture.
