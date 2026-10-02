import unittest
from datetime import datetime, time, timedelta, timezone

from policy import ALLOW, BLOCK, Rule, resolve, segments


def utc(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)


def block_segments(segs):
    return [(s.begin, s.end) for s in segs if s.action == BLOCK]


class FallBackTest(unittest.TestCase):
    """2025-11-02: clocks fall back; 01:00-02:00 wall time happens twice."""

    def test_window_inside_repeated_hour(self):
        rule = Rule("r1", 1, BLOCK, frozenset({6}), time(1, 15), time(1, 45))
        segs = segments([rule], utc(2025, 11, 2, 4, 0), utc(2025, 11, 2, 8, 0))
        self.assertEqual(
            block_segments(segs),
            [(utc(2025, 11, 2, 5, 15), utc(2025, 11, 2, 5, 45)),
             (utc(2025, 11, 2, 6, 15), utc(2025, 11, 2, 6, 45))],
        )

    def test_window_crossing_repeated_hour(self):
        rule = Rule("r1", 1, BLOCK, frozenset({6}), time(0, 30), time(1, 30))
        segs = segments([rule], utc(2025, 11, 2, 4, 0), utc(2025, 11, 2, 8, 0))
        self.assertEqual(
            block_segments(segs),
            [(utc(2025, 11, 2, 4, 30), utc(2025, 11, 2, 5, 30)),
             (utc(2025, 11, 2, 6, 0), utc(2025, 11, 2, 6, 30))],
        )

    def test_resolve_both_folds(self):
        rule = Rule("r1", 1, BLOCK, frozenset({6}), time(1, 15), time(1, 45))
        for h, m, expected in [(5, 14, ALLOW), (5, 15, BLOCK), (5, 45, ALLOW),
                               (6, 14, ALLOW), (6, 15, BLOCK), (6, 45, ALLOW)]:
            action, pid = resolve([rule], utc(2025, 11, 2, h, m))
            self.assertEqual(action, expected)
            self.assertEqual(pid, "r1" if expected == BLOCK else None)


class SpringForwardTest(unittest.TestCase):
    """2025-03-09: clocks spring forward; 02:00-03:00 wall time never occurs."""

    def test_window_partially_skipped(self):
        rule = Rule("r1", 1, BLOCK, frozenset({6}), time(2, 10), time(3, 10))
        segs = segments([rule], utc(2025, 3, 9, 5, 0), utc(2025, 3, 9, 9, 0))
        self.assertEqual(
            block_segments(segs),
            [(utc(2025, 3, 9, 7, 0), utc(2025, 3, 9, 7, 10))],
        )

    def test_window_fully_skipped(self):
        rule = Rule("r1", 1, BLOCK, frozenset({6}), time(2, 10), time(2, 50))
        segs = segments([rule], utc(2025, 3, 9, 5, 0), utc(2025, 3, 9, 9, 0))
        self.assertEqual(block_segments(segs), [])
        self.assertEqual(resolve([rule], utc(2025, 3, 9, 7, 30)), (ALLOW, None))


class PriorityTest(unittest.TestCase):
    def test_lower_priority_shadowed(self):
        high = Rule("high", 1, BLOCK, frozenset({0}), time(9, 0), time(17, 0))
        low = Rule("low", 2, ALLOW, frozenset({0}), time(0, 0), time(23, 59))
        # 2025-03-10 is a Monday. 13:00 UTC = 09:00 EDT, 20:00 UTC = 16:00 EDT.
        self.assertEqual(resolve([high, low], utc(2025, 3, 10, 13, 0)), (BLOCK, "high"))
        self.assertEqual(resolve([high, low], utc(2025, 3, 10, 20, 0)), (BLOCK, "high"))
        self.assertEqual(resolve([high, low], utc(2025, 3, 10, 22, 30)), (ALLOW, "low"))

    def test_shadowed_rule_toggles_make_no_extra_segments(self):
        high = Rule("high", 1, BLOCK, frozenset({0}), time(9, 0), time(17, 0))
        low = Rule("low", 2, ALLOW, frozenset({0}), time(10, 0), time(11, 0))
        segs = segments([high, low], utc(2025, 3, 10, 0, 0), utc(2025, 3, 11, 0, 0))
        self.assertEqual(
            [(s.action, s.policy_id) for s in segs],
            [(ALLOW, None), (BLOCK, "high"), (ALLOW, None)],
        )

    def test_same_action_different_policy_not_merged(self):
        r1 = Rule("r1", 1, BLOCK, frozenset({2}), time(9, 0), time(12, 0))
        r2 = Rule("r2", 2, BLOCK, frozenset({2}), time(12, 0), time(15, 0))
        # 2025-03-12 is a Wednesday (EDT, UTC-4).
        segs = segments([r1, r2], utc(2025, 3, 12, 0, 0), utc(2025, 3, 13, 0, 0))
        self.assertEqual(
            [(s.action, s.policy_id) for s in segs],
            [(ALLOW, None), (BLOCK, "r1"), (BLOCK, "r2"), (ALLOW, None)],
        )
        self.assertEqual(segs[1].end, utc(2025, 3, 12, 16, 0))
        self.assertEqual(segs[2].begin, utc(2025, 3, 12, 16, 0))


class OvernightTest(unittest.TestCase):
    def test_overnight_window_uses_start_day_weekday(self):
        # Sunday 22:00 -> Monday 02:00 local. Monday 01:00 is covered because
        # the start day (Sunday) is in weekdays, even though Monday is not.
        rule = Rule("r1", 1, BLOCK, frozenset({6}), time(22, 0), time(2, 0))
        # 2025-03-09 is Sunday (EST until 07:00 UTC, then EDT).
        self.assertEqual(resolve([rule], utc(2025, 3, 10, 2, 30)), (BLOCK, "r1"))  # Sun 22:30 EDT
        self.assertEqual(resolve([rule], utc(2025, 3, 10, 5, 30)), (BLOCK, "r1"))  # Mon 01:30 EDT
        self.assertEqual(resolve([rule], utc(2025, 3, 10, 6, 30)), (ALLOW, None))  # Mon 02:30 EDT

    def test_overnight_segments(self):
        rule = Rule("r1", 1, BLOCK, frozenset({2}), time(22, 0), time(2, 0))
        # Wednesday 2025-03-12 (EDT, UTC-4): window Wed 22:00 -> Thu 02:00
        # local is Thu 02:00-06:00 UTC. Tuesday is not in weekdays, so no
        # block on Wednesday morning.
        segs = segments([rule], utc(2025, 3, 12, 0, 0), utc(2025, 3, 14, 0, 0))
        self.assertEqual(
            block_segments(segs),
            [(utc(2025, 3, 13, 2, 0), utc(2025, 3, 13, 6, 0))],
        )


class SegmentInvariantTest(unittest.TestCase):
    def _assert_invariants(self, rules, begin, end):
        segs = segments(rules, begin, end)
        self.assertTrue(segs)
        self.assertEqual(segs[0].begin, begin)
        self.assertEqual(segs[-1].end, end)
        for prev, cur in zip(segs, segs[1:]):
            self.assertEqual(prev.end, cur.begin)  # no gaps, no overlaps
            self.assertNotEqual(  # adjacent results always differ
                (prev.action, prev.policy_id), (cur.action, cur.policy_id))
        for s in segs:
            self.assertLess(s.begin, s.end)  # no zero-length segments
        # Segments agree with resolve on sampled instants.
        t = begin
        while t < end:
            action, pid = resolve(rules, t)
            seg = next(s for s in segs if s.begin <= t < s.end)
            self.assertEqual((seg.action, seg.policy_id), (action, pid))
            t += timedelta(seconds=137)

    def test_invariants_across_fall_back(self):
        rules = [
            Rule("a", 1, BLOCK, frozenset({6}), time(0, 30), time(1, 30)),
            Rule("b", 2, ALLOW, frozenset({6, 0}), time(1, 0), time(3, 0)),
            Rule("c", 3, BLOCK, frozenset({0}), time(23, 0), time(2, 0)),
        ]
        self._assert_invariants(rules, utc(2025, 11, 1, 12, 0), utc(2025, 11, 3, 12, 0))

    def test_invariants_across_spring_forward(self):
        rules = [
            Rule("a", 1, BLOCK, frozenset({6}), time(2, 10), time(3, 10)),
            Rule("b", 2, BLOCK, frozenset({6}), time(1, 30), time(4, 30)),
            Rule("c", 3, ALLOW, frozenset({6, 1}), time(20, 0), time(5, 0)),
        ]
        self._assert_invariants(rules, utc(2025, 3, 8, 12, 0), utc(2025, 3, 10, 12, 0))

    def test_empty_rules_single_allow_segment(self):
        segs = segments([], utc(2025, 6, 1, 0, 0), utc(2025, 6, 2, 0, 0))
        self.assertEqual(len(segs), 1)
        self.assertEqual((segs[0].action, segs[0].policy_id), (ALLOW, None))


if __name__ == "__main__":
    unittest.main()
