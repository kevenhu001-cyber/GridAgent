"""Shared synchronous model request scheduling and bounded, payload-free telemetry."""

from collections import deque
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from random import uniform
from threading import BoundedSemaphore, Lock
from time import monotonic, sleep


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _retry_after(error):
    headers = getattr(getattr(error, "response", None), "headers", {}) or {}
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds) if isfinite(seconds) else None
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            return max(0.0, (date - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


class ModelQueueTimeout(TimeoutError):
    """A request could not be admitted within its queue deadline."""


class ModelScheduler:
    """One scheduler per configured model client, shared by its bound variants.

    Limits are local to the client/process; they are not provider-wide quotas.
    Only explicit HTTP 429 rejections are retried, never arbitrary exceptions.
    """

    def __init__(self, *, concurrency=1, requests_per_minute=0, queue_timeout=60,
                 max_retries=1, max_retry_delay=15, clock=monotonic, pause=sleep):
        if not 1 <= concurrency <= 16 or not 0 <= requests_per_minute <= 100000:
            raise ValueError("Invalid model concurrency or RPM limit")
        if not 0 < queue_timeout <= 600 or not 0 <= max_retries <= 3 or not 0 < max_retry_delay <= 60:
            raise ValueError("Invalid model request timing or retry configuration")
        self._slots = BoundedSemaphore(concurrency)
        self._lock = Lock()
        self._recent = deque()
        self._rpm = requests_per_minute
        self._queue_timeout = queue_timeout
        self._max_retries = max_retries
        self._max_retry_delay = max_retry_delay
        self._clock = clock
        self._pause = pause
        self._stats = {
            "logical_calls": 0, "provider_attempts": 0, "retries": 0,
            "rate_limited": 0, "failed_calls": 0, "queue_timeouts": 0, "parse_failures": 0,
            "queue_seconds": 0.0, "model_seconds": 0.0, "retry_wait_seconds": 0.0,
            "usage_reports": 0, "cache_reports": 0,
            "input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
        }

    def _add(self, **values):
        with self._lock:
            for key, value in values.items():
                self._stats[key] += value

    def snapshot(self):
        with self._lock:
            result = dict(self._stats)
        if not result["usage_reports"]:
            result["input_tokens"] = result["output_tokens"] = None
        if not result["cache_reports"]:
            result["cached_input_tokens"] = None
        return result

    def _admit(self, deadline):
        if self._clock() >= deadline:
            raise ModelQueueTimeout("Model admission deadline exceeded")
        if not self._rpm:
            return
        while True:
            with self._lock:
                now = self._clock()
                while self._recent and now - self._recent[0] >= 60:
                    self._recent.popleft()
                if now >= deadline:
                    raise ModelQueueTimeout("Model RPM admission deadline exceeded")
                if len(self._recent) < self._rpm:
                    self._recent.append(now)
                    return
                delay = max(0.0, 60 - (now - self._recent[0]))
            if self._clock() + delay >= deadline:
                raise ModelQueueTimeout("Model RPM admission deadline exceeded")
            self._pause(delay)

    def _observe(self, message):
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            return
        inputs = _count(usage.get("input_tokens"))
        outputs = _count(usage.get("output_tokens"))
        if inputs is None or outputs is None:
            return
        details = usage.get("input_token_details") or {}
        cached = _count(details.get("cache_read")) if isinstance(details, dict) else None
        values = {"usage_reports": 1, "input_tokens": inputs, "output_tokens": outputs}
        if cached is not None and cached <= inputs:
            values.update(cache_reports=1, cached_input_tokens=cached)
        self._add(**values)

    def invoke(self, operation, *, raw_message=lambda value: value):
        """Execute one logical request, measuring each locally visible attempt."""
        started = self._clock()
        deadline = started + self._queue_timeout
        self._add(logical_calls=1)
        if not self._slots.acquire(timeout=self._queue_timeout):
            self._add(failed_calls=1, queue_timeouts=1, queue_seconds=self._clock() - started)
            raise ModelQueueTimeout("Model concurrency admission deadline exceeded")
        self._add(queue_seconds=self._clock() - started)
        try:
            for attempt in range(self._max_retries + 1):
                queued = self._clock()
                try:
                    self._admit(deadline)
                finally:
                    self._add(queue_seconds=self._clock() - queued)
                if attempt:
                    self._add(retries=1)
                self._add(provider_attempts=1)
                before = self._clock()
                try:
                    result = operation()
                except Exception as error:
                    status = getattr(error, "status_code", None)
                    if status != 429:
                        raise
                    self._add(rate_limited=1)
                    delay = _retry_after(error)
                    if delay is None:
                        delay = min(self._max_retry_delay, uniform(0.5, 1.0) * 2 ** attempt)
                    if (attempt >= self._max_retries or delay > self._max_retry_delay
                            or self._clock() + delay >= deadline):
                        raise
                else:
                    self._observe(raw_message(result))
                    return result
                finally:
                    self._add(model_seconds=self._clock() - before)
                self._pause(delay)
                self._add(retry_wait_seconds=delay)
        except ModelQueueTimeout:
            self._add(failed_calls=1, queue_timeouts=1)
            raise
        except Exception:
            self._add(failed_calls=1)
            raise
        finally:
            self._slots.release()


class ScheduledModel:
    """Minimal runnable adapter used by GridAgent's synchronous model workflows."""

    def __init__(self, runnable, scheduler, *, structured=False, return_raw=False):
        self._runnable = runnable
        self._scheduler = scheduler
        self._structured = structured
        self._return_raw = return_raw

    def bind_tools(self, tools, **kwargs):
        return ScheduledModel(self._runnable.bind_tools(tools, **kwargs), self._scheduler)

    def with_structured_output(self, schema, **kwargs):
        requested_raw = kwargs.pop("include_raw", False)
        bound = self._runnable.with_structured_output(schema, include_raw=True, **kwargs)
        return ScheduledModel(bound, self._scheduler, structured=True, return_raw=requested_raw)

    def invoke(self, messages, config=None, **kwargs):
        def operation():
            if config is not None:
                return self._runnable.invoke(messages, config=config, **kwargs)
            return self._runnable.invoke(messages, **kwargs)

        if not self._structured:
            return self._scheduler.invoke(operation)
        result = self._scheduler.invoke(operation, raw_message=lambda value: value.get("raw"))
        if result.get("parsing_error") is not None:
            self._scheduler._add(parse_failures=1)
            if not self._return_raw:
                raise result["parsing_error"]
        if self._return_raw:
            return result
        return result["parsed"]

    def metrics(self):
        return self._scheduler.snapshot()
