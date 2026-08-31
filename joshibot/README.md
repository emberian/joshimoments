# shitcoims Sentinel

A local-first, sell-only Solana position monitor for the `shitcoims` wallet. It polls the wallet,
discovers new SPL and Token-2022 holdings, watches explicit stop/trailing/rug policies, and exposes a
read-only dashboard at [http://127.0.0.1:8787](http://127.0.0.1:8787).

This repository contains no MarketFabric imports or copied implementation. MarketFabric was treated
as untrusted reference material.

## Current safety posture

- The only executable swap direction is token -> wrapped SOL.
- There is no buy function or HTTP execution endpoint.
- Browser code receives read-only state and never sees a private key, provider key, unsigned
  transaction, or signed transaction.
- Live execution requires all three local gates: `execution.enabled: true`, process flag `--live`, and
  a mode-0600 arm file whose value binds it to the current `shitcoims` public key.
- Jupiter's returned transaction is untrusted: before submission, the server requires `shitcoims` to
  be the only signer and fee payer, rejects unknown top-level programs and direct token transfers,
  constrains close/ATA destinations, caps the priority fee, and simulates the exact locally signed
  transaction. Simulation must dispose of the complete target, preserve every other owned token,
  return the minimum quoted output to the `shitcoims` SOL account, and stay within the SOL-cost cap.
- Exit retries reconcile the current on-chain balance before each attempt. Jupiter success remains a
  pending intent until Helius confirms the signature and observes the target balance decrease.
  Ambiguous submission does not blindly repeat the original amount.
- Runtime state and pending exits are atomically persisted and reconciled after restart.
- A fatal monitoring error terminates the server so launchd can restart it; the dashboard is not left
  serving stale state as if protection were healthy.

The committed and local configs start with live execution disabled. `--panic` is dry-run unless the
same three live gates are satisfied.

## Local files

The existing secret locations are used directly:

- `~/.helius-key`: Helius API key, mode `0600`
- `~/.shitcoims-wallet`: base58-encoded 64-byte `shitcoims` keypair, mode `0600`
- `~/.jup-shitcoims`: Jupiter API key, mode `0600`
- `~/.shitcoims-tg`: Telegram bot token, mode `0600`
- `~/dev/allgame/.env`: `KAGI_API_KEY` for Search API v1, mode `0600`
- `~/.apify-token`: Apify API token for the pinned X actor, mode `0600`
- `config.yaml`: local position policy, ignored by git
- `state/`: event tape, trailing peaks, pool/supply baselines, pending exits, logs and trade CSV

Secrets are read into memory. They are not copied into the repo, state, dashboard, or structured
logs. Do not enable `httpx` request logging: Helius authenticates in its URL query string.

## Install and run

```bash
uv sync
npm install
npm run build
uv run python sentinel.py
```

The Python process serves both the API and the prebuilt dashboard on loopback port 8787.

The dashboard is a shadcn/ui cockpit with Overview, Positions (edit exit rules), Markets
(DexScreener-proxied history), Intelligence, History, and Performance. Policy writes hit
`PUT /api/policies/{mint}` and only mutate the local `positions:` list — they cannot arm
live execution. For a one-cycle read-only report:

```bash
uv run python sentinel.py --status
```

Install the dry-run/observe-only server as a macOS login service:

```bash
scripts/install-launch-agent.sh
```

It is configured by `ops/com.shitcoims.sentinel.plist`, restarts after failure, and logs to
`state/sentinel.stdout.log` and `state/sentinel.stderr.log`. Remove it recoverably with
`scripts/uninstall-launch-agent.sh`.

## Add explicit position policy

New wallet holdings are discovered automatically but are **observe-only**. Add cost basis and exit
rules to local `config.yaml` before expecting automatic action:

```yaml
positions:
  - mint: "TOKEN_MINT"
    name: "TOKEN"
    cost_basis_sol: 0.5       # total SOL paid for the current balance
    stop_loss_pct: -30
    take_profit_pct: 100
    trailing_stop_pct: 20
    rug_exit: true
    dispose_after_break_even: false
```

Alternatively use `buy_price_sol` for SOL per whole token; set exactly one of `cost_basis_sol` and
`buy_price_sol`. Restart the service after config changes.

**Cost basis is never inferred from a quote.** An earlier build stamped it from the current Jupiter
exit quote, so PnL began at 0% regardless of what had been paid and every stop fired that far below
the coin's already-fallen price — measured over one live window, quote-stamped bases returned −29.1%
mean across 16 round trips while operator-typed bases returned +18.1% across 3. Basis is now
reconstructed from the wallet's own observed on-chain buys, and when it cannot be established the
position is left **rug-only**: with no basis there is no PnL, so no stop, take-profit, trail or
dispose rule can fire at any price. An unknown basis is reported as unknown, never guessed.

Price decisions use a Jupiter quote for the wallet's current token balance — an executable exit
valuation, not a ticker price. Note that exits are **no longer full-balance-only**: scale-out rungs
sell a fraction of a lot, and the simulation check binds the expected remainder rather than
requiring the whole position to disappear.

To make disposal a one-shot local override without editing YAML:

```bash
uv run python sentinel.py --dispose TOKEN_MINT
uv run python sentinel.py --cancel-dispose TOKEN_MINT
```

These commands only validate and update durable local state; they never enter the trading path. A
dispose policy records executable PnL samples, arms only on an observed `PnL <= 0` to `PnL > 0`
transition, persists that trigger's confirmed slot, and authorizes a full sell after a later
confirmed slot is observed. Missing cost basis, full-balance quote, or confirmed slot keeps it
fail-closed. The ordinary three live-execution gates still apply, and emergency rug exits retain
precedence. Marking a held but unconfigured mint is allowed, but it cannot arm until that mint has a
configured cost basis and position policy.

## Rug signals

The 30-second safety sweep pins the primary direct-SOL pool when available and tracks:

- primary-pool SOL reserve (falling back to USD liquidity for non-SOL pairs),
- mint supply growth while mint authority remains active,
- active mint and freeze authorities,
- collapse or disappearance of the full-balance Jupiter exit quote.

A liquidity emergency needs a second pool sample and a measured collapse in a still-available exit
quote. Missing providers are treated as **unknown**, never as zero liquidity. This reduces false
sales caused by one bad DexScreener sample. A material supply increase with active mint authority is
an immediate emergency, except when the authority is the canonical Pump mint-authority PDA used by
modern Pump Token-2022 coins.

The dashboard labels LP-lock/burn status unsupported. A generic “LP tokens burned” boolean is not a
sound invariant across pump.fun AMM, Raydium CLMM/CPMM, Orca Whirlpool, and Meteora DLMM. The runtime
uses actual reserve movement instead of pretending those pool models share one ownership primitive.

## Jupiter V2 and live execution

The old `quote-api.jup.ag/v6` interface in the original spec is obsolete. This implementation targets
current Jupiter Swap V2 `/order` + `/execute`, forces Metis for executable orders, signs locally, and
lets Jupiter handle landing/confirmation.

1. Create a Jupiter API key and save only the key to `~/.jup-shitcoims`:

   ```bash
   chmod 600 ~/.jup-shitcoims
   ```

2. Populate and dry-run real policies. Test `--panic` while dry:

   ```bash
   uv run python sentinel.py --panic
   ```

3. When reviewed, set `execution.enabled: true`, bind the arm file, and run the launch agent with an
   explicit `--live` argument:

   ```bash
   uv run python sentinel.py --arm
   uv run python sentinel.py --live
   ```

The checked-in launch agent intentionally omits `--live`; enabling unattended live exits is a
separate operator review step.

## Notifications

Terminal, stderr, and the durable event journal are always enabled. Telegram is optional:

```yaml
notifications:
  telegram_bot_token_file: "~/.shitcoims-tg"
  telegram_chat_id: "CHAT_ID"
```

The token file must be mode `0600`. Pair only a private chat:

```bash
uv run python sentinel.py --telegram-discover
# scan the one-time QR that opens in Preview, then add the printed telegram_chat_id to config.yaml
uv run python sentinel.py --telegram-test
```

The default pairing window is 10 minutes. Override it when needed, for example with
`--telegram-discover-timeout-seconds 1200` for 20 minutes. The QR is generated locally with
`qrencode`, contains only the one-time private-chat deep link, and is deleted when discovery ends;
if QR generation or opening is unavailable, the CLI prints the same link as a fallback.
After a valid `/start`, the bot replies in that private chat before consuming the pairing update.

Discovery refuses webhooks, existing pending updates, groups, channels, mismatched users, and wrong
nonces. A Telegram delivery failure is itself written as a critical local event and is never silently
swallowed.

## Signal lab

The dashboard now separates source health, normalized evidence, and execution authority. Current
record-only experiments are:

- confirmed Helius wallet activity for `shitcoims`, used to wake the poller immediately;
- official Pump.fun `coins-v2/{mint}` metadata, cached and advisory only;
- the public ClaudeKOL wallet, monitored by canonical transaction receipts only;
- Kagi Search API v1 for discovery snippets (titles/URLs only);
- Apify X search through one pinned pay-per-result actor (`~/.apify-token`).

Pump callouts are visibly disabled. Pump exposes them in its signed-in product, but there is no
supported public API/schema/rate-limit contract. ClaudeKOL is useful as product inspiration, but it is
closed source, brand-new, and has publicly mislabeled the same mint under multiple tickers. No code,
session, or narrative from it is trusted. An external signal can only observe or alert; it cannot call
the executor, synthesize rug evidence, or select an asset by ticker.

## Verification

```bash
uv run ruff check sentinel.py shitcoims_sentinel tests
uv run pytest
npm run lint
npm test
npm audit --audit-level=high
plutil -lint ops/com.shitcoims.sentinel.plist
```

The offline suite covers rule precedence, full-balance pricing, trailing state, supply/liquidity rug
signals, secret permissions, atomic persistence, all live gates, transaction program allowlisting,
priority-fee caps, signing, and browser/server isolation.

## Intelligence daemon

The isolated research process listens on [http://127.0.0.1:8788](http://127.0.0.1:8788). It can
collect advisory X search results through the pinned Apify actor. It cannot sign, buy, or sell.

```bash
uv run python intel.py --ingest-once   # one cheap collection cycle, then exit
scripts/install-inteld.sh              # keep the read API + collectors running
```

Scout (`scout.py`) is the read-only Telegram console. Enable it in `intelligence.yaml`, then:

```bash
uv run python scout.py --check-ready
scripts/install-scout-launch-agent.sh
```

New Scout commands: `/x`, `/xkol`, `/kols`, `/kol <handle>`, `/health`, `/mints`,
`/cashtag TICKER`, `/early <mint>`. Trade, arm, dispose, and config commands are still
rejected locally.

X collection is **KOL-first**. Handles live in `intelligence.yaml` under `adapters.x_apify.kols`.
The seed list was research-checked: `threadguy` is the wrong account — the streamer is
`notthreadguy`. Cashtags are claims. The only self-attested wallet currently configured is
Ansem's X-linked pump.fun profile, stored as a low-confidence claim.

## License

This repository's original source code, studies, and documentation are licensed under the
[GNU Affero General Public License, version 3 or later](LICENSE) (`AGPL-3.0-or-later`).
Copyright (C) 2026 Ember Arlynx.

All of it is first-party work by a single copyright holder. Third-party dependencies (see
`pyproject.toml`, `package.json`, `uv.lock`) remain under their own licenses, and captured or
provider-derived data retains its own provenance; the project license does not replace either.
