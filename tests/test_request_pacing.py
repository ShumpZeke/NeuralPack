"""Dispatch-rate regressions use an artificial clock and no network."""
from datetime import datetime, timezone
import pytest
from benchmarks.request_pacing import RequestPacer
from benchmarks.repository_eval import retry_after_seconds


def test_fast_requests_are_spaced_and_slow_requests_are_not_delayed_again():
    now = [0.0]; delays = []
    def sleep(seconds):
        delays.append(seconds); now[0] += seconds
    pacer = RequestPacer(3, 1, clock=lambda: now[0], sleep=sleep)
    starts = []
    for duration in (0.1, 5.0, 0.2):
        pacer.wait(); starts.append(now[0]); now[0] += duration
    assert starts == [0, 3, 8]
    assert delays == [2.9]


@pytest.mark.parametrize('value', [True, -1, 61, float('nan'), float('inf'), '3'])
def test_invalid_spacing_is_rejected(value):
    with pytest.raises(ValueError): RequestPacer(value, 1)


def test_parallel_batches_cannot_misrepresent_the_per_request_limit():
    with pytest.raises(ValueError, match='one worker'): RequestPacer(3, 2)


def test_interrupted_delay_does_not_advance_the_dispatch_clock():
    def interrupted(seconds): raise KeyboardInterrupt
    pacer = RequestPacer(3, 1, clock=lambda: 0, sleep=interrupted)
    pacer.wait()
    with pytest.raises(KeyboardInterrupt): pacer.wait()
    assert pacer.last == 0


def test_a_wait_that_returns_early_cannot_allow_an_early_request():
    now = [0.0]; waits = []
    def early_once(seconds):
        waits.append(seconds); now[0] += 1 if len(waits) == 1 else seconds
    pacer = RequestPacer(3, 1, clock=lambda: now[0], sleep=early_once)
    pacer.wait(); pacer.wait()
    assert waits == [3, 2] and now[0] == 3


@pytest.mark.parametrize('value,expected', [
    ('120', 120), (' 0 ', 0), ('-1', None), ('1.5', None), (None, None),
    ('not-a-date-or-delay', None), ('Wed, 09 Sep 2026 00:01:00 GMT', 60),
    ('Tue, 08 Sep 2026 00:01:00 GMT', 0),
])
def test_retry_hint_accepts_only_a_delay_or_timezone_aware_http_date(value, expected):
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    assert retry_after_seconds(value, now) == expected
