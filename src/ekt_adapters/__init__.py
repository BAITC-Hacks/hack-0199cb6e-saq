"""Local, read-only adapters for partner spreadsheets."""

from .iek import load_iek
from .se import load_se

__all__ = ["load_iek", "load_se"]
