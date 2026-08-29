# dregg gate

Token-gate Telegram bot for the $DREGG holders group. One process
(@ltshitcoims_bot — NOT @dreggnet_bot) serving holder verification, gated-group
invites, the daily re-verify sweep, and the operator approvals/alerts DM lane.

Run: `python -m dregg_gate --config dregg_gate.toml`
(`--check-config` validates offline; `--probe` does one live getMe.)

The state db takes an exclusive flock; a second poller on the same bot token
refuses to start. The disabled scout used the same discipline on its own state
file — nothing else may consume this token's getUpdates.

## The 2-minute group setup (for Ember)

The Bot API cannot create groups, so this part is manual, once:

1. In Telegram, create a new group (a plain group is fine; if Telegram later
   upgrades it to a supergroup the bot follows the migration automatically).
   Don't create an invite link yourself — the bot mints per-member ones.
2. Add @ltshitcoims_bot to the group.
3. Promote it to admin with at least: **Invite Users via Link** and
   **Ban Users**. Nothing else is needed.
4. In the group, send: `/bind`
   The bot only honors this from your account (operator chat id). It records
   the group id in its state and confirms by DM.

Done. From then on: verified holders get single-use, 1-hour invite links; the
sweep ejects lapsed holders (ban + immediate unban, so they can rejoin after
re-verifying).

## Holder flow

1. DM the bot `/verify <wallet>`.
2. It replies with a challenge (nonce, 10-minute expiry). Sign that exact text
   with the wallet's signMessage (Phantom, Solflare, Backpack — anything), paste
   the base58 signature back.
3. The bot verifies ed25519, checks the wallet holds >= 888,888 $DREGG via
   Helius (decimals read on-chain, balances summed across all token accounts),
   binds tg-account<->wallet 1:1 both ways, and DMs a single-use invite link.
4. `/status` shows standing; `/invite` re-mints a link for verified members.

Daily sweep: below threshold -> warning DM + 48h grace -> still below after
grace -> eject. A Helius error NEVER ejects anyone: the day's sweep is skipped
whole and the operator is alerted instead.

## Approvals API (for the wire/verdict lanes)

Other services ask the operator for a yes/no by inserting a row into the
`approvals` table in the gate's sqlite (`paths.db` in the config). Full schema,
lifecycle, and helpers (`enqueue_approval`, `read_decision`) are documented in
`dregg_gate/approvals.py` — use those helpers, not raw SQL. Short version:

    id = enqueue_approval(db_path, source="wire", kind="draft",
                          summary="text shown to Ember", payload={...})
    # ... poll:
    decision = read_decision(db_path, id)   # None until decided
    # decision.decision is 'approve' or 'reject'; decision.payload is yours, unchanged

The db is WAL with a busy timeout — concurrent writers are expected and safe.
The gate's flock guards the Telegram poller identity, not the database.
