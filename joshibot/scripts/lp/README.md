# Exploration scripts — preserved, not maintained

These are the one-shot scripts that reconstructed the LP position history in
`studies/RESULT_lp_history.md`: pull the wallet's signatures, cache every transaction, find
positions by their rent-creation signature, extract per-position flows, and check token
survival. Run in that order; each writes a JSON the next one reads.

They are kept for **reproducibility of that document**, not as library code, and they are
deliberately excluded from the blocking lint gate in `scripts/check.sh` — they are full of
semicolon one-liners and were written to answer a question once.

**The durable tool is `scripts/lp_report.py`**, which is gated, typed, and re-runnable. Use
that. Reach for these only to re-derive the history analysis or to see exactly how a number in
the RESULT document was produced.
