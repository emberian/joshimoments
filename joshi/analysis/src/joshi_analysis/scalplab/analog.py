"""Analog forecasting: the empirical distribution of what followed the nearest neighbours.

No functional form: the model is the memory. Feature vectors from train coins are
standardized and stored; a query event's forecast is the Laplace-smoothed label frequency
among its ``ANALOG_NEIGHBOURS`` nearest train vectors (Euclidean in standardized space). When
the memory exceeds ``ANALOG_MEMORY_CAP`` it is thinned by a deterministic uniform stride —
declared in the registration as part of the model, not a tuning knob.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from .linalg import standardize_apply, standardize_fit
from .vocabulary import ANALOG_MEMORY_CAP, ANALOG_NEIGHBOURS


@dataclass(frozen=True)
class AnalogForecast:
    probability: float  # (positives + 1) / (k + 2)
    neighbours: int
    neighbour_positives: int


@dataclass(frozen=True)
class AnalogModel:
    means: tuple[float, ...]
    stds: tuple[float, ...]
    memory: tuple[tuple[float, ...], ...]
    memory_labels: tuple[int, ...]
    k: int

    def forecast(self, vectors: list[list[float]]) -> list[AnalogForecast]:
        standardized = standardize_apply(vectors, list(self.means), list(self.stds))
        out = []
        for row in standardized:
            distances = (
                (sum((a - b) ** 2 for a, b in zip(row, mem, strict=False)), label)
                for mem, label in zip(self.memory, self.memory_labels, strict=True)
            )
            nearest = heapq.nsmallest(self.k, distances, key=lambda pair: pair[0])
            positives = sum(label for _, label in nearest)
            k = len(nearest)
            out.append(
                AnalogForecast(
                    probability=(positives + 1) / (k + 2),
                    neighbours=k,
                    neighbour_positives=positives,
                )
            )
        return out

    def predict_proba(self, vectors: list[list[float]]) -> list[float]:
        return [f.probability for f in self.forecast(vectors)]

    def params(self) -> dict:
        return {
            "family": "analog",
            "k": self.k,
            "memorySize": len(self.memory),
            "memoryCap": ANALOG_MEMORY_CAP,
            "smoothing": "laplace (pos+1)/(k+2)",
        }


def fit_analog(
    vectors: list[list[float]],
    labels: list[int],
    k: int = ANALOG_NEIGHBOURS,
    cap: int = ANALOG_MEMORY_CAP,
) -> AnalogModel:
    if len(vectors) != len(labels) or not vectors:
        raise ValueError("vectors and labels must be non-empty and aligned")
    means, stds = standardize_fit(vectors)
    standardized = standardize_apply(vectors, means, stds)
    if len(standardized) > cap:
        stride = len(standardized) / cap
        picks = [int(i * stride) for i in range(cap)]
        standardized = [standardized[i] for i in picks]
        labels = [labels[i] for i in picks]
    return AnalogModel(
        means=tuple(means),
        stds=tuple(stds),
        memory=tuple(tuple(row) for row in standardized),
        memory_labels=tuple(labels),
        k=k,
    )
