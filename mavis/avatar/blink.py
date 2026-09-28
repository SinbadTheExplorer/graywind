"""When he blinks. Pure timing, no Panda3D: the scene turns the number into lids.

A face that never blinks reads as dead, but a metronome reads as a machine, so
the gap is drawn fresh every time and now and then he blinks twice in a row.
First drafted by the `delegate` model, then reviewed and reworked.
"""


def _smoothstep(x: float) -> float:
    """3x^2 - 2x^3, clamped: eases in and out so the lid never snaps."""
    x = 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
    return x * x * (3.0 - 2.0 * x)


class BlinkSchedule:
    """Eyelid closure over time: 0 open, 1 shut."""

    def __init__(self, rng, interval=(2.0, 6.0), double_chance=0.12,
                 close=0.07, hold=0.04, open_=0.13, double_gap=0.12):
        self.rng = rng
        self.interval = interval
        self.double_chance = double_chance
        self.close = close
        self.hold = hold
        self.open_ = open_
        self.double_gap = double_gap
        self.length = close + hold + open_
        self.next_start = None
        self.is_second = False

    def amount(self, t: float) -> float:
        """Closure at absolute time `t`; call once per frame, t non-decreasing."""
        if self.next_start is None:
            self.next_start = t + self.rng.uniform(*self.interval)
        while True:
            if t < self.next_start:
                return 0.0
            end = self.next_start + self.length
            if t < end:
                break
            if t - end > self.length:
                # A pause skipped whole blinks. Replaying them would just be a
                # flutter on resume, so start the clock again from now.
                self.next_start = t + self.rng.uniform(*self.interval)
                self.is_second = False
            elif not self.is_second and self.rng.random() < self.double_chance:
                self.next_start = end + self.double_gap
                self.is_second = True
            else:
                self.next_start = end + self.rng.uniform(*self.interval)
                self.is_second = False

        phase = t - self.next_start
        if phase < self.close:
            return _smoothstep(phase / self.close)
        if phase < self.close + self.hold:
            return 1.0
        return 1.0 - _smoothstep((phase - self.close - self.hold) / self.open_)
