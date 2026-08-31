"""Swap-level flow recording for the four-token community cluster.

Hourly OHLCV is a time average. This package records the flow field itself: every
transaction that touched one of the cluster's six pools, at slot resolution, with the
pool's reserves before and after.

See :mod:`shitcoims_cluster.parse` for what is and is not recoverable from a transaction,
and where the recorded shapes do and do not fit ``shitcoims_tape.schema``.
"""

from __future__ import annotations

__all__ = ["CLUSTER_POOLS", "PoolSpec"]

from shitcoims_cluster.pools import CLUSTER_POOLS, PoolSpec
