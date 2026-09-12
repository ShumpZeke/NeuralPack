"""Per-run dispatch spacing for explicit LIVE evaluation, without automatic retries."""
import math
import time


class RequestPacer:
    def __init__(self, interval, workers, *, clock=None, sleep=None):
        if type(interval) not in (int, float) or not math.isfinite(interval) or not 0 <= interval <= 60:
            raise ValueError('Request interval must be finite and within 0..60 seconds')
        if interval and workers != 1:
            raise ValueError('Request spacing requires one worker')
        self.interval = interval
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.last = None

    def wait(self):
        """Call BEFORE recording STARTED, so interrupted spacing is not an attempt."""
        now = self.clock()
        if self.last is not None and self.interval:
            delay = self.last + self.interval - now
            while delay > 0:
                self.sleep(delay)
                now = self.clock()
                delay = self.last + self.interval - now
        self.last = now
