"""Adjudication logic: resolve() and segments()."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Iterable, List, Tuple
from zoneinfo import ZoneInfo

from .types import ACTIONS, ALLOW, Decision, Rule, Segment

TZ = ZoneInfo("America/New_York")


def _validated(rules: Iterable[Rule]) -> List[Rule]:
    rules = list(rules)
    ids = set()
    priorities = set()
    for rule in rules:
        if rule.id in ids:
            raise ValueError(f"duplicate rule id: {rule.id!r}")
        if rule.priority in priorities:
            raise ValueError(f"duplicate priority: {rule.priority!r}")
        if rule.action not in ACTIONS:
            raise ValueError(f"invalid action: {rule.action!r}")
        if rule.start == rule.end:
            raise ValueError("start and end must differ")
        if not all(isinstance(d, int) and 0 <= d <= 6 for d in rule.weekdays):
            raise ValueError(f"invalid weekdays: {rule.weekdays!r}")
        ids.add(rule.id)
        priorities.add(rule.priority)
    return rules


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC-aware datetime")


def _is_effective(rule: Rule, local_date, local_time: time) -> bool:
    """Check the local window for one local date / wall-clock time."""
    start, end = rule.start, rule.end
    if start < end:
        return local_date.weekday() in rule.weekdays and start <= local_time < end
    # Overnight window: [start, midnight) belongs to the start day;
    # [midnight, end) belongs to the start day's next calendar day.
    if local_date.weekday() in rule.weekdays and local_time >= start:
        return True
    previous = local_date - timedelta(days=1)
    return previous.weekday() in rule.weekdays and local_time < end


def resolve(rules: Iterable[Rule], at_utc: datetime) -> Decision:
    """Return the decision of the highest-priority effective rule."""
    _require_utc("at_utc", at_utc)
    local = at_utc.astimezone(TZ)
    local_date = local.date()
    local_time = local.time()
    best: Tuple[int, Rule] | None = None
    for rule in _validated(rules):
        if not _is_effective(rule, local_date, local_time):
            continue
        if best is None or rule.priority < best[0]:
            best = (rule.priority, rule)
    if best is None:
        return Decision(ALLOW, None)
    return Decision(best[1].action, best[1].id)


def _local_to_utc_instants(naive: datetime) -> List[datetime]:
    """Map a naive local datetime to its 0, 1 or 2 real UTC instants."""
    instants = set()
    for fold in (0, 1):
        aware = naive.replace(tzinfo=TZ, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(TZ).replace(tzinfo=None) == naive:
            instants.add(utc)
    return sorted(instants)


def _offset_transitions(begin_utc: datetime, end_utc: datetime) -> List[datetime]:
    """Find UTC instants in [begin_utc, end_utc] where the UTC offset changes."""
    transitions = []
    step = timedelta(hours=6)
    previous = begin_utc
    previous_offset = previous.astimezone(TZ).utcoffset()
    current = begin_utc + step
    while current <= end_utc + step:
        current_offset = current.astimezone(TZ).utcoffset()
        if current_offset != previous_offset:
            lo, hi = previous, current
            while (hi - lo) > timedelta(seconds=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(TZ).utcoffset() == previous_offset:
                    lo = mid
                else:
                    hi = mid
            transitions.append(hi.replace(microsecond=0))
        previous, previous_offset = current, current_offset
        current += step
    return [t for t in transitions if begin_utc <= t <= end_utc]


def _rule_boundaries(rule: Rule, first_date, last_date) -> List[datetime]:
    """UTC instants where this rule's effectiveness may switch."""
    instants = []
    day = first_date
    one_day = timedelta(days=1)
    while day <= last_date:
        if day.weekday() in rule.weekdays:
            start_local = datetime.combine(day, rule.start)
            end_day = day if rule.start < rule.end else day + one_day
            end_local = datetime.combine(end_day, rule.end)
            instants.extend(_local_to_utc_instants(start_local))
            instants.extend(_local_to_utc_instants(end_local))
        day += one_day
    return instants


def segments(
    rules: Iterable[Rule], begin_utc: datetime, end_utc: datetime
) -> List[Segment]:
    """Return the effective decision segments covering [begin_utc, end_utc)."""
    _require_utc("begin_utc", begin_utc)
    _require_utc("end_utc", end_utc)
    if end_utc <= begin_utc:
        return []
    rules = _validated(rules)

    first_date = (begin_utc.astimezone(TZ) - timedelta(days=1)).date()
    last_date = (end_utc.astimezone(TZ) + timedelta(days=1)).date()

    boundaries = {begin_utc, end_utc}
    boundaries.update(_offset_transitions(begin_utc, end_utc))
    for rule in rules:
        for instant in _rule_boundaries(rule, first_date, last_date):
            if begin_utc < instant < end_utc:
                boundaries.add(instant)
    ordered = sorted(boundaries)

    result: List[Segment] = []
    for left, right in zip(ordered, ordered[1:]):
        decision = resolve(rules, left)
        if (
            result
            and result[-1].action == decision.action
            and result[-1].policy_id == decision.policy_id
        ):
            result[-1] = Segment(
                result[-1].start, right, decision.action, decision.policy_id
            )
        else:
            result.append(Segment(left, right, decision.action, decision.policy_id))
    return result
