from types import SimpleNamespace

import pytest

from gridagent.model_runtime import ModelQueueTimeout, ModelScheduler, ScheduledModel


class FakeClock:
    def __init__(self):
        self.time = 0.0

    def now(self):
        return self.time

    def pause(self, seconds):
        self.time += seconds


class RateLimited(Exception):
    status_code = 429

    def __init__(self, retry_after="1"):
        self.response = SimpleNamespace(headers={"retry-after": retry_after})


def scheduler(clock, **kwargs):
    return ModelScheduler(clock=clock.now, pause=clock.pause, **kwargs)


def test_rate_limit_retry_and_usage_accounting():
    clock = FakeClock()
    runtime = scheduler(clock)
    attempts = []

    def call():
        attempts.append(1)
        if len(attempts) == 1:
            raise RateLimited("2")
        return SimpleNamespace(usage_metadata={
            "input_tokens": 100, "output_tokens": 20,
            "input_token_details": {"cache_read": 80},
        })

    runtime.invoke(call)
    stats = runtime.snapshot()
    assert len(attempts) == stats["provider_attempts"] == 2
    assert stats["logical_calls"] == stats["retries"] == stats["rate_limited"] == 1
    assert stats["retry_wait_seconds"] == 2
    assert stats["input_tokens"] == 100
    assert stats["output_tokens"] == 20
    assert stats["cached_input_tokens"] == 80


def test_no_unsafe_retry_and_missing_usage_is_not_zero():
    runtime = ModelScheduler()
    with pytest.raises(TimeoutError):
        runtime.invoke(lambda: (_ for _ in ()).throw(TimeoutError("unknown request outcome")))
    stats = runtime.snapshot()
    assert stats["provider_attempts"] == 1
    assert stats["failed_calls"] == 1
    assert stats["retries"] == 0
    assert stats["input_tokens"] is None
    assert stats["cached_input_tokens"] is None


def test_retry_after_larger_than_cap_is_not_shortened():
    clock = FakeClock()
    runtime = scheduler(clock, max_retry_delay=5)
    with pytest.raises(RateLimited):
        runtime.invoke(lambda: (_ for _ in ()).throw(RateLimited("120")))
    assert clock.time == 0
    assert runtime.snapshot()["provider_attempts"] == 1


def test_rpm_limit_and_admission_timeout():
    clock = FakeClock()
    runtime = scheduler(clock, requests_per_minute=1, queue_timeout=90)
    runtime.invoke(lambda: "one")
    runtime.invoke(lambda: "two")
    assert clock.time == 60
    assert runtime.snapshot()["queue_seconds"] == 60
    limited = scheduler(clock, requests_per_minute=1, queue_timeout=10)
    limited.invoke(lambda: "one")
    with pytest.raises(ModelQueueTimeout):
        limited.invoke(lambda: "two")
    assert limited.snapshot()["provider_attempts"] == 1
    assert limited.snapshot()["queue_timeouts"] == 1


def test_bound_models_share_scheduler_and_structured_results_keep_contract():
    class FakeModel:
        def bind_tools(self, tools, **kwargs):
            return self

        def with_structured_output(self, schema, **kwargs):
            assert kwargs["include_raw"] is True
            return SimpleNamespace(invoke=lambda *a, **k: {
                "parsed": {"answer": 2},
                "raw": SimpleNamespace(usage_metadata={"input_tokens": 10, "output_tokens": 3}),
                "parsing_error": None,
            })

        def invoke(self, messages):
            return SimpleNamespace(usage_metadata={"input_tokens": 5, "output_tokens": 1})

    model = ScheduledModel(FakeModel(), ModelScheduler())
    model.bind_tools([]).invoke([])
    assert model.with_structured_output(dict).invoke([]) == {"answer": 2}
    assert model.with_structured_output(dict, include_raw=True).invoke([])["parsed"] == {"answer": 2}
    stats = model.metrics()
    assert stats["logical_calls"] == stats["usage_reports"] == 3
    assert stats["input_tokens"] == 25
    assert stats["cached_input_tokens"] is None


def test_structured_parse_failure_is_not_retried():
    class FakeModel:
        def with_structured_output(self, schema, **kwargs):
            return SimpleNamespace(invoke=lambda *a, **k: {
                "parsed": None, "raw": None, "parsing_error": ValueError("Invalid model output"),
            })

    model = ScheduledModel(FakeModel(), ModelScheduler())
    with pytest.raises(ValueError, match="Invalid model output"):
        model.with_structured_output(dict).invoke([])
    assert model.metrics()["provider_attempts"] == 1
    assert model.metrics()["parse_failures"] == 1


def test_stream_consumer_uses_scheduler_and_does_not_retry_429():
    model = ScheduledModel(object(), ModelScheduler())
    received = []

    def consume(raw):
        received.append("public delta")
        raise RateLimited()

    with pytest.raises(RateLimited):
        model.consume_stream(consume)
    assert received == ["public delta"]
    assert model.metrics()["provider_attempts"] == 1
    result = model.consume_stream(lambda _: SimpleNamespace(
        usage_metadata={"input_tokens": 4, "output_tokens": 2}))
    assert result.usage_metadata["output_tokens"] == 2
    assert model.metrics()["input_tokens"] == 4
