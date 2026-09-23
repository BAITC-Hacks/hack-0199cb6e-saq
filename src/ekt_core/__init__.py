"""Core data structures and deterministic synthetic fixtures."""

from .config import EngineParams
from .synthetic import CanonicalDataset, make_dataset

__all__ = ["CanonicalDataset", "EngineParams", "make_dataset"]

