"""dregg_screen — the live birth-time rug screen ($DREGG utility v1, workstream B2).

Every new pump.fun launch, scored within seconds of its create event, against the
birth-time CLEAN screen validated in ``studies/operator_crime.py`` and re-validated by
B1 on fresh post-upgrade data (2026-08-26..28, ``studies/data/operator_crime_fresh/``,
the SEEDED-history variant: CLEAN precision 100% on is_rip / 99.97% on collapse at an
8.5% admit rate).

Three moving parts, deliberately separated by dependency weight:

``ledger``    builds the KNOWN-CREW fingerprint ledger + deployer-history table from the
              study corpora into one versioned sqlite artifact (needs the research group:
              pandas/pyarrow). The live scorer only ever READS this file, with stdlib
              sqlite3, so the runtime never imports pandas.
``features``  the feature definitions, replicated EXACTLY from operator_crime's SQL —
              a drifted feature silently invalidates B1's numbers, so every definition
              cites the SQL it mirrors and the parity test in
              ``tests/test_dregg_screen.py`` holds them equal on real corpus rows.
``live``      the service: PumpPortal ``subscribeNewToken`` via the already-hardened
              :mod:`shitcoims_scalper.firehose` client (watch ledger, gap rows,
              heartbeats, reconnect — that discipline is inherited, not reimplemented),
              Helius birth-slot hydration under a hard daily budget, and the JSONL /
              rolling-JSON / TG-line outputs.

This package POSTS NOTHING. It emits artifacts; the gate/bot lane consumes them.
Scores RANK risk. They never convict — the emitted language says "matched crew
fingerprint #N (Jaccard 0.31)", never "scammer".
"""

__all__ = ["features", "ledger", "score"]
