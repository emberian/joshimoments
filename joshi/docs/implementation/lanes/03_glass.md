# Lane 03 — accessibility-first glass handoff

## Outcome

`apps/glass` is a pinned React 19 + TypeScript 7 + Vite 8 browser shell for observation, decision capture, and replay. It boots with a deterministic offline fixture and has a narrow, runtime-validated seam for the future loopback core. It has no transaction construction, signer, wallet connection, or trade control.

The shell implements:

- a virtualized, board-filterable broad attention feed;
- global search plus a view-only command palette;
- a selected-coin workbench with Lightweight Charts and a text/table equivalent;
- a persistent episode rail for exposed runners and `watching_flat` re-entry watches;
- separately served knowledge-cutoff, witnessed, and retrospective snapshots with atomic mode replacement;
- explicit source gaps and expandable field provenance with observed, ingested, and known clocks;
- comfortable/compact density without shrinking interactive targets;
- large targets, conspicuous focus indicators, a skip link, semantic controls, reduced-motion support, and responsive single-column layouts.

## Safety boundary

The browser is deliberately incapable of capital action. “Re-entry” and “liquidation” appear only as episode/accounting observations. The command surface contains navigation and view commands only. A CSP limits network access to self and HTTP/WebSocket loopback addresses. The loopback client rejects non-local origins, sends `credentials: "omit"`, and rejects response bodies above 4 MiB.

No private key, API credential, provider secret, transaction builder, signer, or wallet adapter belongs in this package.

## Contract and core seam

The pinned boundary is `src/contract/v1.ts`:

- outer transport contract: `joshi.glass.snapshot`, schema version `1`;
- hashed inner view contract: `joshi.glass.view`, schema version `1`;
- exactly one mode per inner view: `knowledge_cutoff`, `witnessed`, or `retrospective`;
- runtime validation: duplicate-key-aware raw JSON parsing followed by recursively strict Zod schemas; duplicate and unknown object keys are rejected rather than collapsed or stripped;
- `snapshotDigest`: SHA-256 over the exact canonical UTF-8 bytes of the inner view;
- complete `AsOfVector`: catalog commit, per-source delivered watermark and sorted scoped cursors, optional chain watermark, exact projection versions/state digests, and render time;
- monetary/quantity values: exact base-10 strings at the boundary;
- integers: canonical decimal strings; timestamps: UTC RFC3339 with exactly six fractional digits and `Z`;
- evidence: class, status, source, and separate observed/ingested/known clocks;
- authority: literal `read_record_replay_only`.

Canonical glass-view encoding v1 is deliberately narrower than a claim of general JCS: strict schema-order object keys, identity arrays strictly sorted by canonical ASCII identity, no insignificant whitespace, then UTF-8. Cursor scopes are `(family, subject, cursorKind)` with nullable subject and independent `advancedThrough`; there is no source-wide “latest cursor.” The transferable TypeScript/Rust golden is `src/contract/golden.ts`, digest `sha256:8cbd045cbf22dd4c908ef84ecc14840d71f846b672c0311f65a2a48cdf8d69ab`.

Default startup uses `OfflineFixtureDataSource`. To exercise the later integration seam, build or run with:

```sh
VITE_JOSHI_CORE_URL=http://127.0.0.1:8787 npm run dev
```

The core must serve `GET /api/v1/glass/snapshot?mode=<mode>` with one contract-v1 envelope. Recomputed requests also carry `basisSceneId=<witnessed-scene-id>`. For witnessed mode, the inner view bytes and digest must be the exact immutable `scene.view_bytes` stored at capture; a current reducer must not regenerate or substitute them. Knowledge-cutoff and retrospective modes are separately generated DTOs whose inner `basisSceneId` must match the requested witnessed scene. The UI retains the prior verified snapshot until the distinct response validates, then replaces it atomically. It never filters a mixed DTO into a purported historical scene.

If the core runs on a different loopback port, it must explicitly allow the glass origin; the client will not send ambient cookies. Streaming is intentionally not invented in this lane. Replace snapshot loading behind `GlassDataSource` only when the core publishes an ordered, digest-bound stream contract.

## Keyboard model

| Key | Meaning |
|---|---|
| `/` | focus market search |
| `J` / `↓` | focus the next candidate in displayed rank order |
| `K` / `↑` | focus the previous candidate |
| `R` | request the next as-known → witnessed → retrospective snapshot |
| `D` | toggle comfortable/compact density |
| `P` | toggle selected-field provenance |
| `⌘K` / `Ctrl+K` / `?` | open the view-only command surface |
| `Esc` | close the command surface |

Shortcuts do not fire while typing. The command dialog traps Tab and restores focus to its launcher on close.

## Verification

Run from `apps/glass`:

```sh
npm install --ignore-scripts
npm run typecheck
npm test
npm run build
```

The tests cover strict contract/digest parsing, raw duplicate-key rejection, exact-decimal and exact-timestamp rejection, canonical ordering and cross-language golden bytes, scoped cursor behavior, loopback-origin/credential/response bounds, keyboard navigation/search, distinct snapshot requests, retrospective visibility, command/provenance behavior, absence of execution buttons, adversarial later-field leakage, and an axe-core scan of the initial rendered view.

At handoff, the exact successful commands were:

```text
npm run typecheck
npm test
npm run build
```

## Integration notes and known limits

- The fixture is intentionally fictional and makes no claim about actual Pump, chain, wallet, or social state.
- Pump information parity is not claimed by this UI. It can only expose the candidates and evidence the upstream collectors provide.
- Charts are canvas-rendered, so the shell supplies a text summary and expandable latest-bars table rather than pretending the canvas is accessible.
- Virtual rows include set size and position metadata, but assistive-technology testing with the operator’s actual screen reader remains an integrated gate.
- The in-app Browser runtime was unavailable during this lane (`agent.browsers.list()` returned no browsers), so automated DOM/axe checks and production compilation passed, but rendered desktop/mobile visual QA still needs to be repeated when that runtime is attached.
- The next integrated test should inject exact stored `scene.view_bytes`, verify the shared golden in Rust and TypeScript, and prove a retrospective request cannot change any already-rendered witnessed field before its distinct digest-valid response commits to the UI.

## Integration repair: single-mode immutable replay

The first Wave 1 draft was rejected during coherence review because one browser DTO bundled witnessed and retrospective ranks while several fields—metrics, tags, episode state, social summaries, and source health—had no field-level availability cutoff. Client-side filtering only some collections could therefore present a scene labeled “witnessed” while leaking later truth.

The repaired contract removes that possibility structurally:

1. An envelope contains exactly one inner view and one replay mode.
2. The inner contract/version, mode, scene/basis identity, full as-of vector, and complete payload are all inside the digest.
3. Witnessed mode has no basis scene and is served from immutable stored view bytes.
4. Knowledge-cutoff and retrospective modes must name the witnessed basis and arrive as distinct responses.
5. Candidate rank is one exact string, not a witnessed/retrospective pair.
6. The UI performs no `knownAt` filtering or value substitution; it renders only the validated mode-local payload.
7. Mode controls are disabled while loading, and the old verified snapshot remains explicitly labeled until atomic replacement.

Adversarial fixtures place unique later-only sentinels in market metrics, tags/social summary, episode re-entry state, source-gap recovery, and social events. Tests prove none occur in witnessed or earlier-cutoff view bytes and all occur only in the retrospective DTO. Separate tests reject raw duplicate JSON object keys before structural parsing, unknown nested fields, tampering under a stale digest, duplicate IDs, non-ASCII canonical identities, variable/offset timestamps, wrong-mode loopback responses, oversized responses, and a lossy source-wide cursor fallback.
