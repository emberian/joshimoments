"""dregg_d4m -- D4M-style associative arrays over the crew substrate.

An associative array ``A(row_key, col_key) -> value`` with string keys IS a sparse matrix
plus two key dictionaries (Kepner, *Mathematics of Big Data*). Every asset this project
holds has that shape -- birth-slot sniper x coin, wallet x coin, deployer x coin, caller x
coin -- and several of our hand-rolled pairwise set loops are one sparse product over the
right semiring.

``assoc`` is the layer. ``graphs`` builds the real matrices with provenance. ``analyses``
holds the pre-registered analyses (``studies/REGISTRATION_d4m.md``), each with a
degree-preserving null.

This package NEVER writes to the live ledger and never spends a network credit. It reads
study corpora and the shipped read-only sqlite artifacts, and writes only under
``state/dregg_d4m/``.
"""

from dregg_d4m.assoc import Assoc, co_occurrence, jaccard, matmul, overlap_coeff

__all__ = ["Assoc", "co_occurrence", "jaccard", "matmul", "overlap_coeff"]
