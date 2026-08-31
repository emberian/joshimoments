"""dregg_feed — the realtime movers feed into the gated group, with chart previews.

WHAT THIS IS AND IS NOT (the honesty boundary, non-negotiable)
--------------------------------------------------------------
Our own studies REFUTED momentum as an entry edge: board_entry continuation reverses
under censoring, and the bandit/buy-ahead studies were nulls. This feed is therefore
AWARENESS — "what is moving right now" — never a buy signal. No rockets, no urgency,
and every alert ends with the standing line in `compose.STANDING_LINE`. What we add
that the pump frontend does not: the screen's BIRTH verdict on the same coin, so
"trending" arrives welded to "and here is what its launch looked like".

  charts.py   — dark chart PNGs from swap-api 5m candles: singles and the up-to-6
                MONTAGE grid (deterministic bytes)
  movers.py   — the movers-board poller + the high-bar detector (sqlite state)
  verdicts.py — mint -> birth verdict from the screen's scores JSONL (incremental)
  compose.py  — the montage caption (PLAIN TEXT, bare auto-linked URLs, no HTML)
  service.py  — the loop: poll, detect, batch into ONE montage per window, enqueue
                into the GATE outbox

Delivery goes through dregg_gate's outbox ONLY (one bot, one group, one queue);
the gate poller uploads the PNG via multipart sendPhoto.
"""
