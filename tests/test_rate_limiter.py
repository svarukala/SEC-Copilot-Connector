"""Concurrent monotonic pacing without wall-clock sleeps."""

import asyncio

import pytest

from sec_connector.utils import RateLimiter


async def test_concurrent_acquisitions_are_paced_without_initial_burst(monkeypatch):
    clock = [100.0]
    actual_sleep = asyncio.sleep

    async def sleep(delay):
        clock[0] += delay
        await actual_sleep(0)

    monkeypatch.setattr("sec_connector.utils.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("sec_connector.utils.asyncio.sleep", sleep)
    limiter = RateLimiter(10)
    admissions = []

    async def acquire():
        await limiter.acquire()
        admissions.append(clock[0])

    await asyncio.gather(*(acquire() for _ in range(6)))
    assert admissions == pytest.approx([100 + i * 0.1 for i in range(6)])
    clock[0] += 10
    await asyncio.gather(acquire(), acquire())
    assert admissions[-1] - admissions[-2] == pytest.approx(0.1)


@pytest.mark.parametrize("rate", [0, -1, float("inf"), float("nan")])
def test_invalid_rate_rejected(rate):
    with pytest.raises(ValueError):
        RateLimiter(rate)
