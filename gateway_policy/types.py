"""Public data types for the gateway policy calendar library."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import FrozenSet, Optional

ALLOW = "ALLOW"
BLOCK = "BLOCK"
ACTIONS = (ALLOW, BLOCK)


@dataclass(frozen=True)
class Rule:
    """A single gateway policy rule.

    Attributes:
        id: Unique policy identifier.
        priority: Unique integer; smaller means higher priority.
        action: "ALLOW" or "BLOCK".
        weekdays: Set of weekday numbers (Monday=0 .. Sunday=6) on which
            the window starts, in local time.
        start: Local wall-clock window start (inclusive), second precision.
        end: Local wall-clock window end (exclusive), second precision.
            Must differ from ``start``. If ``end < start`` the window
            continues past midnight into the next local day.
    """

    id: int
    priority: int
    action: str
    weekdays: FrozenSet[int] = field(default_factory=frozenset)
    start: time = time(0, 0)
    end: time = time(0, 0)


@dataclass(frozen=True)
class Decision:
    """Result of resolving a single instant."""

    action: str
    policy_id: Optional[int]


@dataclass(frozen=True)
class Segment:
    """A maximal half-open UTC interval [start, end) with one decision."""

    start: datetime
    end: datetime
    action: str
    policy_id: Optional[int]
