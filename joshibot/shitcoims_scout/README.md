# shitcoims Scout

Scout is the Telegram gateway for local `shitcoims` intelligence and YAML exit rules. It can query
the intelligence API on `127.0.0.1:8788` and the Sentinel snapshot on `127.0.0.1:8787`, and it can
PUT loopback policy YAML. It contains no wallet, Helius, Jupiter, signer, executor, or transaction
dependency. It cannot sell, arm, or panic.

Scout is disabled by default. Add this section to `intelligence.yaml` only after reviewing the
gateway:

```yaml
scout:
  enabled: false
  telegram_bot_token_file: "~/.shitcoims-tg"
  telegram_chat_id: "YOUR_PRIVATE_CHAT_ID"
  telegram_user_id: "YOUR_TELEGRAM_USER_ID"
  state_file: "./intelligence_state/scout.sqlite3"
  api_base: "http://127.0.0.1:8788"
  sentinel_api_base: "http://127.0.0.1:8787"
  poll_timeout_seconds: 25
  message_max_age_seconds: 120
```

The existing private-chat pairing normally has the same numeric chat and user ID, but both values
must be configured explicitly. The bot must not have a webhook. Scout must be the only process that
calls `getUpdates` for this bot; an exclusive state lock also prevents two local Scout processes.

Validate without contacting Telegram:

```sh
uv run python scout.py --check-config
uv run python scout.py --check-ready
```

After changing `enabled` to `true`, run in the foreground with `uv run python scout.py`. The separate
launch-agent scripts are `scripts/install-scout-launch-agent.sh` and
`scripts/uninstall-scout-launch-agent.sh`; they are provided but are not run automatically.

Commands are `/start`, `/help`, `/desk`, `/now`, `/x`, `/xkol`, `/health`, `/mints`, `/kols`,
`/portfolio`, `/positions`, `/inventory`, `/panic-preview`, `/risks`, `/performance`,
`/events`, `/trades`, `/sources`, `/wallet <address|label>`, `/token <mint>`,
`/cashtag <TICKER>`, `/kol <handle>`, `/why <signal-id>`, and `/digest`.
`/desk` opens inline buttons that write `config.yaml` positions only.
`/inventory` and `/panic-preview` are GET-only reads of the local Sentinel snapshot.
`/performance`, `/events`, and `/trades` are GET-only reads of the local Sentinel
history APIs. `/panic` stays rejected; `/panic-preview` only describes what a panic
would attempt and never sells. Trade, arm, sign, and live-execution commands are rejected
locally without querying an API.

The cursor, outgoing-message queue, and opaque expiring callback handles are stored in Scout's own
private SQLite database. Telegram messages must come from the exact configured non-bot user in the
exact configured private chat and must be fresh. Buttons are one-use capabilities; callback queries
are acknowledged before slower local data requests.
