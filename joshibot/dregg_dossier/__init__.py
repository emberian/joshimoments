"""dregg_dossier — the 728k-wallet behavioral layer as a live holder feature.

``/wallet <address>`` renders a wallet's behavioral dossier (guild, realization policy,
executable realized PnL, hold times, bot tells) and ``/coin <mint>`` the holder
composition of a corpus coin (guild mix, preset-bot count, crews, active iceberg
distributors) — both over ``state/wallets/`` (built by ``studies/wallet_estimator.py``),
served from a compact sqlite index so a lookup never touches the 660MB parquets.

========  =======================================================================
module    role
========  =======================================================================
store     the index: ``build`` (research deps, run per corpus refresh) and the
          stdlib ``Dossier`` reader the bot holds; CLI ``python -m dregg_dossier``
cards     plain-text card rendering (no HTML anywhere), misses as null-with-reason
lookup    the gated, rate-limited /wallet + /coin handlers; gateway wiring notes
          live in its module docstring
========  =======================================================================

The JOIN_CONTRACT (state/wallets/JOIN_CONTRACT.md) is honored throughout: misses are
null-with-reason and never zero, every card carries the corpus-window freshness stamp,
and timing_q is presented as a ranking exit tell, never a conviction.
"""

__all__ = ["cards", "lookup", "store"]
