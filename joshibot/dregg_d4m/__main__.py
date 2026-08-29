"""CLI: ``uv run --group research python -m dregg_d4m <d0|d1|d2|d3|d4|d5|all>``."""

import sys

from dregg_d4m.analyses import main

if __name__ == "__main__":
    sys.exit(main())
