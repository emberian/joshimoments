"""CLI: ``run`` the desk, ``report`` on it, ``glass`` to serve the capture surface.

    uv run python -m shitcoims_paperdesk run --minutes 10
    uv run python -m shitcoims_paperdesk run --minutes 0        # daemon, until killed
    uv run --group research python -m shitcoims_paperdesk report
    uv run python -m shitcoims_paperdesk hunch                  # the intuition premium
    uv run python -m shitcoims_paperdesk glass --warm           # the API the glass talks to

The research group is only needed for ``report`` -- specifically for the survival section,
which is fitted with ``lifelines`` rather than hand-rolled. The desk itself runs on the
base dependency set and imports nothing from ``shitcoims_sentinel``: it holds no keys,
signs nothing and sends nothing.
"""

from __future__ import annotations

import sys

from shitcoims_paperdesk import desk, report

USAGE = """usage: python -m shitcoims_paperdesk <command> [options]

  run     [--minutes N] [--poll-seconds S] [--bankroll-sol X] [--seed N]
          [--explore-eps E] [--max-positions N] [--drain] [--tape-days-back N]
          --minutes <= 0 runs as a daemon until killed. Positions persist across
          restarts unless --drain is passed.

  report  [--days N] [--dir PATH] [--json]
          Per-book daily P&L net of friction, open positions, censoring rates,
          the toll gate table, and the cross-book comparison.

  hunch   [--days N] [--json]
          The operator book against the wiggle book under identical execution:
          the intuition premium, the expectation scorecard, and which entry
          gates would have vetoed which hunches.

  glass   [--port N] [--warm]
          The loopback API the coin explorer talks to (default 127.0.0.1:8788).
          Reads the tapes, appends hunches. Holds no key and sends nothing.
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(USAGE)
        return 0
    command, rest = args[0], args[1:]
    if command == "run":
        return desk.main(rest)
    if command == "report":
        return report.main(rest)
    if command == "hunch":
        from shitcoims_paperdesk import hunch_report

        return hunch_report.main(rest)
    if command == "glass":
        from shitcoims_paperdesk import glass

        return glass.main(rest)
    print(USAGE)
    print(f"unknown command: {command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
