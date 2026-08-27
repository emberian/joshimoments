"""CLI: the flow-model census (registration v1.4).

    cd analysis
    uv run --offline python -m joshi_analysis.jupiter_flow \
        --rounds ~/dev/joshi/state/prediction/backfill/backfill-*-rounds.jsonl
"""

from .census import main

if __name__ == "__main__":
    main()
