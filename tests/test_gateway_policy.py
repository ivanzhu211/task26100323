import unittest
from datetime import datetime, time, timedelta, timezone

from gateway_policy import ALLOW, BLOCK, Rule, resolve, segments

UTC = timezone.utc
SUNDAY = 6


def utc(day, hour, minute=0, second=0, month=11, year=2025):
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def blocked_ranges(segs):
    return [(s.start, s.end) for s in segs if s.action == BLOCK]


def assert_tiling(testcase, rules, begin, end):
    """Segments tile [begin, end) once and agree with resolve everywhere."""
    segs = segments(rules, begin, end)
    testcase.assertTrue(segs)
    testcase.assertEqual(segs[0].start, begin)
    testcase.assertEqual(segs[-1].end, end)
    for left, right in zip(segs, segs[1:]):
        testcase.assertEqual(left.end, right.start)
        testcase.assertNotEqual(
            (left.action, left.policy_id), (right.action, right.policy_id)
        )
    for seg in segs:
        testcase.assertLess(seg.start, seg.end)
        probe = seg.start
        while probe < seg.end:
            decision = resolve(rules, probe)
            testcase.assertEqual(decision.action, seg.action)
            testcase.assertEqual(decision.policy_id, seg.policy_id)
            probe += timedelta(seconds=30)
    return segs


class FallBackTest(unittest.TestCase):
    """2025-11-02: local 01:00-02:00 happens twice (EDT then EST)."""

    def test_repeated_window_blocks_twice(self):
        rule = Rule(1, 1, BLOCK, frozenset({SUNDAY}), time(1, 15), time(1, 45))
        segs = assert_tiling(self, [rule], utc(2, 4), utc(2, 9))
        self.assertEqual(
            blocked_ranges(segs),
            [(utc(2, 5, 15), utc(2, 5, 45)), (utc(2, 6, 15), utc(2, 6, 45))],
        )

    def test_window_spanning_the_fallback(self):
        rule = Rule(1, 1, BLOCK, frozenset({SUNDAY}), time(0, 30), time(1, 30))
        segs = assert_tiling(self, [rule], utc(2, 3), utc(2, 9))
        self.assertEqual(
            blocked_ranges(segs),
            [(utc(2, 4, 30), utc(2, 5, 30)), (utc(2, 6, 0), utc(2, 6, 30))],
        )


class SpringForwardTest(unittest.TestCase):
    """2025-03-09: local 02:00-03:00 never happens."""

    def test_partially_skipped_window(self):
        rule = Rule(1, 1, BLOCK, frozenset({SUNDAY}), time(2, 10), time(3, 10))
        segs = assert_tiling(self, [rule], utc(9, 5, month=3), utc(9, 12, month=3))
        self.assertEqual(
            blocked_ranges(segs),
            [(utc(9, 7, 0, month=3), utc(9, 7, 10, month=3))],
        )

    def test_fully_skipped_window_never_applies(self):
        rule = Rule(1, 1, BLOCK, frozenset({SUNDAY}), time(2, 10), time(2, 50))
        segs = assert_tiling(self, [rule], utc(9, 5, month=3), utc(9, 12, month=3))
        self.assertEqual(blocked_ranges(segs), [])
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].action, ALLOW)
        self.assertIsNone(segs[0].policy_id)


class PriorityTest(unittest.TestCase):
    def test_smaller_priority_wins(self):
        low = Rule(1, 10, BLOCK, frozenset({SUNDAY}), time(0, 0), time(12, 0))
        high = Rule(2, 5, ALLOW, frozenset({SUNDAY}), time(1, 0), time(2, 0))
        at = utc(2, 5, 30)  # local 01:30 EDT, inside both windows
        decision = resolve([low, high], at)
        self.assertEqual(decision.action, ALLOW)
        self.assertEqual(decision.policy_id, 2)

    def test_shadowed_rule_creates_no_extra_segments(self):
        # Rule 2 is fully shadowed by rule 1 while both are active.
        # Local Sunday 00:00-03:00 == UTC 04:00-08:00 (spans the 06:00 fallback).
        boss = Rule(1, 1, ALLOW, frozenset({SUNDAY}), time(0, 0), time(3, 0))
        hidden = Rule(2, 2, BLOCK, frozenset({SUNDAY}), time(1, 0), time(3, 0))
        segs = assert_tiling(self, [boss, hidden], utc(2, 3), utc(2, 9))
        self.assertEqual(len(segs), 3)
        self.assertEqual(
            [(s.action, s.policy_id) for s in segs],
            [(ALLOW, None), (ALLOW, 1), (ALLOW, None)],
        )
        self.assertEqual((segs[1].start, segs[1].end), (utc(2, 4), utc(2, 8)))

    def test_same_action_different_policy_still_splits(self):
        first = Rule(1, 1, BLOCK, frozenset({SUNDAY}), time(0, 0), time(1, 0))
        second = Rule(2, 2, BLOCK, frozenset({SUNDAY}), time(1, 0), time(2, 0))
        segs = assert_tiling(self, [first, second], utc(2, 3), utc(2, 9))
        blocks = [s for s in segs if s.action == BLOCK]
        self.assertEqual([s.policy_id for s in blocks], [1, 2])
        self.assertEqual(blocks[0].end, blocks[1].start)


class OvernightTest(unittest.TestCase):
    def test_early_morning_uses_previous_weekday(self):
        # Window Sunday 22:00 -> Monday 02:00 local (EST, UTC-5).
        rule = Rule(1, 1, BLOCK, frozenset({SUNDAY}), time(22, 0), time(2, 0))
        segs = assert_tiling(self, [rule], utc(2, 20), utc(3, 12))
        self.assertEqual(
            blocked_ranges(segs),
            [(utc(3, 3), utc(3, 7))],
        )

    def test_overnight_not_effective_on_wrong_weekday(self):
        rule = Rule(1, 1, BLOCK, frozenset({SUNDAY}), time(22, 0), time(2, 0))
        # Tuesday 01:00 local: previous day is Monday, not Sunday.
        decision = resolve([rule], utc(4, 6))
        self.assertEqual(decision.action, ALLOW)
        self.assertIsNone(decision.policy_id)


class ResolveTest(unittest.TestCase):
    def test_default_allow_without_rules(self):
        decision = resolve([], utc(2, 5))
        self.assertEqual(decision.action, ALLOW)
        self.assertIsNone(decision.policy_id)

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            resolve([], datetime(2025, 11, 2, 5, 0))

    def test_non_utc_datetime_rejected(self):
        from zoneinfo import ZoneInfo

        local = utc(2, 5).astimezone(ZoneInfo("Asia/Shanghai"))
        with self.assertRaises(ValueError):
            resolve([], local)

    def test_validation(self):
        with self.assertRaises(ValueError):
            resolve([Rule(1, 1, "MAYBE", frozenset({0}), time(0), time(1))], utc(2, 5))
        with self.assertRaises(ValueError):
            resolve([Rule(1, 1, BLOCK, frozenset({0}), time(1), time(1))], utc(2, 5))
        dup_id = [Rule(1, 1, BLOCK, frozenset(), time(0), time(1)),
                  Rule(1, 2, ALLOW, frozenset(), time(0), time(1))]
        with self.assertRaises(ValueError):
            resolve(dup_id, utc(2, 5))
        dup_prio = [Rule(1, 1, BLOCK, frozenset(), time(0), time(1)),
                    Rule(2, 1, ALLOW, frozenset(), time(0), time(1))]
        with self.assertRaises(ValueError):
            resolve(dup_prio, utc(2, 5))


class SegmentsTest(unittest.TestCase):
    def test_empty_range(self):
        self.assertEqual(segments([], utc(2, 5), utc(2, 5)), [])
        self.assertEqual(segments([], utc(2, 6), utc(2, 5)), [])

    def test_no_rules_single_allow_segment(self):
        segs = segments([], utc(2, 5), utc(2, 9))
        self.assertEqual(len(segs), 1)
        self.assertEqual((segs[0].action, segs[0].policy_id), (ALLOW, None))
        self.assertEqual((segs[0].start, segs[0].end), (utc(2, 5), utc(2, 9)))

    def test_second_precision(self):
        rule = Rule(1, 1, BLOCK, frozenset({SUNDAY}),
                    time(0, 0, 30), time(0, 1, 30))
        segs = segments([rule], utc(2, 3), utc(2, 9))
        self.assertEqual(
            blocked_ranges(segs),
            [(utc(2, 4, 0, 30), utc(2, 4, 1, 30))],
        )


if __name__ == "__main__":
    unittest.main()
