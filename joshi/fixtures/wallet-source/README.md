# Wallet-source offline fixtures

Unless a fixture's own entry says otherwise, fixtures are synthetic, credential-free,
finalized-shape examples derived from official Helius and Solana response documentation as
checked on 2026-08-16. They are not claims about real wallet behavior, identity, ownership, or
trading skill.

- `helius_get_transactions_for_address_finalized.json` exercises raw full history, transaction
  index, signer/account roles, native and token balance effects, a direct System transfer, Pump
  program-path observation, pagination cursor candidacy, and mint-relative flow.
- `solana_get_transaction_failed_finalized.json` proves that an instruction observed inside a
  failed transaction is retained but never emitted as an executed transfer.
- `helius_legacy_enhanced_projection_finalized.json` exercises the deprecated Enhanced
  Transactions shape. Its transfer and swap fields remain provider projections requiring raw
  reconciliation.
- `scope_input_future_known_rejected.json` is an adversarial bitemporal input: the candidate became
  available after the enclosing scope input and must never enter an earlier lease or replay.
- `attention_promotion_callout.json` references a separate social observation, coverage, and the
  event-bound selected cluster context that resolved its source hypothesis. It does not copy social
  content into chain evidence or claim identity, endorsement, or skill.
- `pump_decoder_differential.json` is an offline differential corpus encoded by Anchor's official
  IDL coder against pinned Pump public-docs IDLs. It covers every supported Pump/PumpSwap buy/sell
  discriminator and records exact base58/hex bytes plus typed intent bounds. Intent bounds are not
  fill amounts; exact fills require matching executed transfer legs in the raw transaction.
- `portfolio_get_transaction_usdc_finalized.json` is **not synthetic**: it is the exact retained
  provider body of one real, public, finalized mainnet `getTransaction` response captured by the
  collector's live wallet sweep on 2026-08-22 (the operator's own wallet; public chain data). It
  exercises stored-body read-back into wallet-scoped balance events: an owner-filtered token
  boundary with a nonzero pre-balance, a second owner whose accounts must not leak into the
  requested wallet's events, and an unchanged native balance that must produce no row.
- `finalized_pump_pumpswap_exact.json` is a synthetic two-transaction raw Helius page. It carries a
  Pump v2 buy and PumpSwap sell with exact instruction bytes, signer/account layouts, token balance
  effects, and instruction-scoped executed transfer legs. Requested slippage limits intentionally
  differ from fills so a decoder cannot pass by copying instruction arguments.

The exact JSON bytes are retained through the shared source/evidence adapter in tests. No fixture
contains a provider credential, private key, authenticated URL, signed transaction, transaction
builder request, or submission request.
