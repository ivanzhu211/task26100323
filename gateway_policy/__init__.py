"""Gateway policy weekly-calendar adjudication library."""

from .core import resolve, segments
from .types import ALLOW, BLOCK, Decision, Rule, Segment

__all__ = [
    "ALLOW",
    "BLOCK",
    "Decision",
    "Rule",
    "Segment",
    "resolve",
    "segments",
]
