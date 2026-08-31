"""dregg gate: the token-gate Telegram bot for $DREGG holders.

ONE bot process (@ltshitcoims_bot) serving three lanes on the same long-poll
transport:

1. HOLDER VERIFICATION — any user DMs /verify <wallet>, signs a nonce challenge
   with their wallet's signMessage, pastes the base58 signature back. The bot
   verifies ed25519 (solders) and checks the wallet holds >= 888,888 $DREGG via
   Helius, then mints a single-use, 1-hour invite link to the gated group.
2. RE-VERIFY SWEEP — daily, batched, spread over ~1h. Below threshold: warning
   DM + 48h grace, then eject (ban + immediate unban; rejoin allowed after
   re-verify). A provider error NEVER ejects anyone: the sweep is skipped for
   the day and the operator is alerted instead.
3. OPERATOR LANE — daily heartbeat summary, alerts, and an approvals outbox:
   other services INSERT rows into the approvals table (see
   dregg_gate.approvals); the bot renders inline approve/reject buttons to the
   operator DM and writes the decision back.

State is a single sqlite file guarded by an exclusive flock: a second poller
on the same token refuses to start. Config is TOML with keep-last-good reload.
"""
