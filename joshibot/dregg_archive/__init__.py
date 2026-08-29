"""dregg_archive — the callout archiver whose depth is the product.

Built ON `shitcoims_pumpsocial` (transport, pacing, endpoint verdicts, hygiene) with the
joshi keeper's disciplines: exact-bytes retention, hard budgets with a durable stop,
heartbeat JSON every tick, config re-read with keep-last-good, absence as a record.

Layers:
  store.py     — sqlite, WAL, single writer: raw fetches + derived rows
  client.py    — the recording transport (retention at the wire, budget at the wire)
  crawl.py     — incremental firehose walk; the one derivation all surfaces share
  service.py   — the 10-minute loop, due-work sweeps, heartbeat
  deletion.py  — absent-while-spanned inference; verdicts only, never published here
  outcomes.py  — returns from OUR candles, method-versioned
  manifest.py  — daily sha256 manifests, shaped for public anchoring
"""

from .service import Config, Service
from .store import BudgetExhausted, Store

__all__ = ["BudgetExhausted", "Config", "Service", "Store"]
