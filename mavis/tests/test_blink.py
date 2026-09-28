"""Blink timing. Pure functions, so no model and no window are needed."""
import random

from avatar.blink import BlinkSchedule


def _run(schedule, seconds, fps=60, start=0.0):
    """Closure per frame over `seconds`, plus the start time of each blink."""
    starts, values, prev = [], [], 0.0
    for i in range(int(seconds * fps)):
        t = start + i / fps
        v = schedule.amount(t)
        if prev == 0.0 and v > 0.0:
            starts.append(schedule.next_start)
        values.append(v)
        prev = v
    return starts, values


def test_open_before_the_first_blink():
    s = BlinkSchedule(random.Random(0))
    assert s.amount(0.0) == 0.0
    assert s.amount(s.next_start - 0.001) == 0.0


def test_one_blink_closes_fully_then_reopens():
    s = BlinkSchedule(random.Random(0), double_chance=0.0)
    s.amount(0.0)
    start = s.next_start
    assert 0.0 < s.amount(start + s.close / 2) < 1.0
    assert s.amount(start + s.close + s.hold / 2) == 1.0
    assert 0.0 < s.amount(start + s.close + s.hold + s.open_ / 2) < 1.0
    assert s.amount(start + s.length + 0.001) == 0.0


def test_gaps_fall_inside_the_interval():
    s = BlinkSchedule(random.Random(1), double_chance=0.0)
    starts, _ = _run(s, 300)
    assert len(starts) > 40
    gaps = [b - (a + s.length) for a, b in zip(starts, starts[1:])]
    assert all(2.0 <= g <= 6.0 for g in gaps)
    # Not a metronome.
    assert max(gaps) - min(gaps) > 1.0


def test_doubles_come_in_pairs_never_triples():
    s = BlinkSchedule(random.Random(2), double_chance=1.0)
    starts, _ = _run(s, 60)
    gaps = [b - (a + s.length) for a, b in zip(starts, starts[1:])]
    assert len(gaps) >= 6
    for i, g in enumerate(gaps):
        if i % 2 == 0:
            assert abs(g - s.double_gap) < 1e-9
        else:
            assert g >= 2.0


def test_a_pause_does_not_replay_missed_blinks():
    s = BlinkSchedule(random.Random(3))
    s.amount(0.0)
    assert 0.0 <= s.amount(1000.0) <= 1.0
    assert 1000.0 + 2.0 <= s.next_start <= 1000.0 + 6.0
    assert s.is_second is False


def test_same_time_twice_gives_the_same_value():
    s = BlinkSchedule(random.Random(4))
    s.amount(0.0)
    t = s.next_start + s.close / 3
    assert s.amount(t) == s.amount(t)


def test_a_minute_at_60fps_has_a_human_blink_rate():
    s = BlinkSchedule(random.Random(5))
    starts, values = _run(s, 60)
    assert 8 <= len(starts) <= 30
    assert all(0.0 <= v <= 1.0 for v in values)
