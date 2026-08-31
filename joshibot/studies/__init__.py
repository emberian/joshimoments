"""Research studies. Read-only, deterministic, no network at run time.

Nothing in here may import the sentinel's execution path. A study that can sign is not a
study. Studies read a *copy* of a store; the live daemon holds a lock on the original.
"""
