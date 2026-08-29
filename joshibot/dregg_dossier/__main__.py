"""``python -m dregg_dossier`` — build/show the index, render smoke-test cards."""

import sys

from .store import main

if __name__ == "__main__":
    sys.exit(main())
