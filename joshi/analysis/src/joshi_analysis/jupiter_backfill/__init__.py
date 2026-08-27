"""Historical backfill of SOL up/down prediction rounds from Polymarket public data.

The live collector (jupiter_collect) only accrues from turn-on; this module backfills
weeks of already-settled rounds so the registered opportunity census (jupiter_conditional
REGISTRATION.md, amendment v1.3) can run on real history now. Read-only throughout: GET
requests against Polymarket's public Gamma / data-api / CLOB endpoints, bounded and
receipted. No order is ever constructed, signed, or submitted.

Honesty spine: trades are FILLS, not the book — a realistic transacted price, never a
guaranteed fillable size. Every provider price and timestamp is a provider claim in its
declared units, retained verbatim in the raw files. A failed pull is a durable gap.
"""
