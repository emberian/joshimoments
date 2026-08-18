# Joshi Pump Companion

An accessibility-first Manifest V3 WebExtension that stays inside Ember's normal authenticated
`pump.fun` browser session. It observes only JSON responses the page itself already received on an
exact route allowlist, projects them onto an explicit field allowlist, and sends bounded batches to
one fixed loopback sink.

The extension starts paused. It does not request or use `cookies`, `tabs`, `history`, `webRequest`,
`debugger`, `scripting`, `nativeMessaging`, wallet, or all-sites permissions. It does not replay a
Pump request, read request headers, read browser/page storage, post, follow, like, trade, scroll, or
navigate. A public author wallet address delivered inside an allowlisted social object may be
retained as an attributed public field; signing material, challenges, signatures, tokens, and
wallet UI are outside the boundary.

## Pinned toolchain

- Node 26.4.0 and npm 11.17.0
- WXT 0.21.4
- TypeScript 6.0.3
- Zod 4.4.3
- lossless-json 4.3.1
- json-dup-key-validator 1.0.3
- punycode 2.3.1 (browser-compatible transitive alias for duplicate-key validation)
- Vitest 4.1.10
- Biome 2.5.8

Every direct and transitive package is fixed by `package-lock.json`. The only approved dependency
install script is the exact esbuild package pinned in `package.json`.

## Fully offline path

After the one-time dependency installation, this command performs no Pump, provider, or core
network access:

```sh
npm run check:offline
```

It lints, type-checks, runs unit/adversarial tests, replays `fixtures/mock-pump-responses.json`
through the real route policy/normalizers/queue, builds Chrome and Firefox packages, and audits the
generated Chrome manifest for exact permissions and hosts. `npm run mock` runs just the deterministic
fixture replay and prints its digest.

## Local development

```sh
npm install
npm run check:offline
npm run dev
```

WXT writes the unpacked Chrome build under `.output/chrome-mv3`. The loopback adapter is fixed at:

```text
POST http://127.0.0.1:43119/v1/observations/pump-companion
```

Requests use `credentials: omit`, refuse redirects, carry no source authentication material, and
time out after two seconds. A batch remains queued until a bounded adapter receipt exactly echoes
its persisted ingress batch ID/digest, paired catalog, acquisition/gap counts and sorted IDs, and
binds separately named durable-batch/store-admission digests after commit. Empty, malformed, wrong,
or partial 2xx responses retry idempotently. The sink may return
`429 Retry-After`; other failures enter bounded retry/backpressure state.

## Data and pressure policy

- exact Fetch response-body read: 512 KiB maximum, hashed before lossless JSON parsing;
- normalized records: 100 derived assertions maximum per acquisition, with exact numeric lexemes;
- exact private response bytes: off by default; if enabled, unchanged Fetch decoded-body bytes with
  verified digest/length, 512 KiB maximum, and an explicit authenticated-private/local-retention
  class;
- acquisition queue: 512 acquisitions or 2 MiB, with a separate 256-record/256-KiB gap reserve;
- sink batch: 25 acquisitions/gaps or 256 KiB;
- one flush processes at most four batches;
- failures retry from 1–60 seconds or use the sink's `Retry-After`;
- overflow rejects the new acquisition, emits a scope-aware gap, and never silently evicts an older
  acquisition; exhausting the separate gap reserve pauses capture fail-closed.

The badge and popup expose `paused`, `idle`, `healthy`, `backpressure`, or `error`, plus queue,
accepted, delivered, dropped, and last-event clocks.

## Bounded parity handoff

The companion also exposes an offline V2 parity-candidate builder for a later, Ember-present
single-route exercise. It requires raw capture to be explicitly enabled and exports exact decoded
body bytes plus digest-only request/filter/cursor state, a non-secret session-occurrence digest,
source acquisition ID, page ordinal, auth disposition, and millisecond-to-microsecond source
clocks. It refuses raw-off capture, partial request projection, route disagreement, and changed
body closure. It never persists a session credential or turns the extension into a continuous
collector. See `docs/implementation/lanes/21_pump_parity_promotion.md`.

## Live-session limitations

This scaffold observes page `fetch` JSON responses. It does not yet claim coverage for XHR,
WebSocket, service-worker push, canvas state, virtualized DOM order, or responses decoded outside
page fetch. Those are empirical signed-session questions, not reasons to add broad permissions.
The page can spoof main-world messages, so every emitted record is explicitly
`page-delivered-untrusted` and the background rechecks sender page, origin, route, schema, field,
size, and user configuration.

With exact-byte capture off, normalized output is explicitly a lossy companion attestation and is
not admissible as an exact observation of the provider response. With exact-byte capture on, the
bounded exact bytes are candidate private evidence; normalized records remain untrusted derived
assertions. Delivery is fail-closed until a local pairing step has pinned the expected catalog ID
and `joshi.sqlite.v5` schema in extension-local storage.

## License

The original companion source code is licensed under
[`AGPL-3.0-or-later`](../../LICENSE). Page responses, public profile fields, and retained provider
bytes are evidence with separate provenance; observing or storing them does not make them
project-owned or relicense them under the AGPL.
