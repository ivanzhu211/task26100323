"""Weekly calendar policy resolution for gateway rules.

All rules are evaluated in the America/New_York timezone using zoneinfo.
The caller has already matched URLs/categories; the rules passed in are the
candidate set for the request. This library decides, per instant, which rule
wins based on time windows and priority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Hashable, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")

ALLOW = "ALLOW"
BLOCK = "BLOCK"


@dataclass(frozen=True)
class Rule:
    """A single gateway policy rule.

    priority: smaller wins; unique across rules.
    weekdays: set of local weekday numbers, Monday=0 .. Sunday=6.
    start/end: local wall-clock times (second precision), never equal.
    """

    id: Hashable
    priority: int
    action: str
    weekdays: frozenset
    start: time
    end: time


@dataclass(frozen=True)
class Segment:
    """A maximal interval of constant decision within a query range."""

    begin: datetime  # UTC-aware, inclusive
    end: datetime  # UTC-aware, exclusive
    action: str
    policy_id: Optional[Hashable]


def resolve(rules: Sequence[Rule], at_utc: datetime) -> Tuple[str, Optional[Hashable]]:
    """Return (action, policy_id) of the highest-priority active rule."""
    if at_utc.tzinfo is None:
        raise ValueError("at_utc must be timezone-aware")
    local = at_utc.astimezone(TZ)
    wall = local.timetz().replace(tzinfo=None)
    today = local.date()
    yesterday = today - timedelta(days=1)

    best: Optional[Rule] = None
    for rule in rules:
        if _is_active(rule, today, yesterday, wall):
            if best is None or rule.priority < best.priority:
                best = rule
    if best is None:
        return ALLOW, None
    return best.action, best.id


def _is_active(rule: Rule, today, yesterday, wall: time) -> bool:
    """Check whether the rule's window covers the given local date/clock time.

    Local windows are left-closed, right-open. When end < start the window
    continues past midnight; the early-morning part is governed by the
    weekday of the start date, not of the morning's own date.
    """
    if rule.start < rule.end:
        return today.weekday() in rule.weekdays and rule.start <= wall < rule.end
    # Overnight window: [start, 24:00) on start day, [00:00, end) next day.
    if today.weekday() in rule.weekdays and wall >= rule.start:
        return True
    return yesterday.weekday() in rule.weekdays and wall < rule.end


def segments(rules: Sequence[Rule], begin_utc: datetime, end_utc: datetime) -> list:
    """Partition [begin_utc, end_utc) into constant-decision segments."""
    if begin_utc.tzinfo is None or end_utc.tzinfo is None:
        raise ValueError("begin_utc and end_utc must be timezone-aware")
    begin = begin_utc.astimezone(timezone.utc)
    end = end_utc.astimezone(timezone.utc)
    if not begin < end:
        raise ValueError("begin_utc must be earlier than end_utc")

    cuts = _boundary_instants(rules, begin, end) + _transition_instants(begin, end)
    cuts = sorted(set(cuts))
    points = [begin] + cuts + [end]

    out: list = []
    for lo, hi in zip(points, points[1:]):
        mid = lo + (hi - lo) / 2
        action, policy_id = resolve(rules, mid)
        if out and out[-1].action == action and out[-1].policy_id == policy_id:
            out[-1] = Segment(out[-1].begin, hi, action, policy_id)
        else:
            out.append(Segment(lo, hi, action, policy_id))
    return out


def _transition_instants(begin: datetime, end: datetime) -> list:
    """UTC instants in (begin, end) where the local UTC offset changes.

    Wall-clock jumps can start or stop a window even when no window edge
    maps there (e.g. a window beginning inside the spring gap effectively
    starts at the transition instant), so these are decision boundaries.
    """
    found = []
    step = timedelta(hours=1)
    lo = begin
    lo_off = lo.astimezone(TZ).utcoffset()
    while lo < end:
        hi = min(lo + step, end)
        hi_off = hi.astimezone(TZ).utcoffset()
        if hi_off != lo_off:
            # Bisect to the exact second; tzdata transitions are whole seconds.
            a, b = lo, hi
            while (b - a) > timedelta(seconds=1):
                mid = a + (b - a) / 2
                if mid.astimezone(TZ).utcoffset() == lo_off:
                    a = mid
                else:
                    b = mid
            cut = b.replace(microsecond=0)
            if cut.astimezone(TZ).utcoffset() == lo_off:
                cut += timedelta(seconds=1)
            if begin < cut < end:
                found.append(cut)
        lo, lo_off = hi, hi_off
    return found


def _boundary_instants(rules: Sequence[Rule], begin: datetime, end: datetime) -> list:
    """UTC instants strictly inside (begin, end) where some rule may toggle."""
    first_day = begin.astimezone(TZ).date() - timedelta(days=2)
    last_day = end.astimezone(TZ).date() + timedelta(days=2)

    cuts = set()
    for rule in rules:
        overnight = rule.end < rule.start
        day = first_day
        while day <= last_day:
            if day.weekday() in rule.weekdays:
                start_local = datetime.combine(day, rule.start)
                end_day = day + timedelta(days=1) if overnight else day
                end_local = datetime.combine(end_day, rule.end)
                for naive in (start_local, end_local):
                    for utc in _local_to_utc(naive):
                        if begin < utc < end:
                            cuts.add(utc)
            day += timedelta(days=1)
    return sorted(cuts)


def _local_to_utc(naive: datetime) -> list:
    """Real UTC instants whose local wall-clock reading equals `naive`.

    Returns 0 instants for wall times skipped in spring, 1 for normal
    times, and 2 for wall times repeated in the fall (fold=0 and fold=1).
    """
    found = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=TZ, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(TZ).replace(tzinfo=None) == naive:
            found.append(utc)
    return sorted(set(found))
