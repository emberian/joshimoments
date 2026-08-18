from __future__ import annotations

import argparse
from pathlib import Path

from joshi_analysis.fixture import write_fixture_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the deterministic offline snapshot fixture")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    write_fixture_snapshot(args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
