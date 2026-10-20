import pytest

from paa.llm import BrainRouter, Completion, ModelError


class FakeClient:
    def __init__(self, *, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = 0

    def complete(self, messages, *, temperature=1.0):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def _completion(text="ok"):
    return Completion(text=text, model="m", input_tokens=1, output_tokens=1)


def test_uses_primary_when_healthy():
    primary = FakeClient(responses=[_completion("来自本地")])
    fallback = FakeClient(responses=[_completion("来自云")])
    router = BrainRouter(primary=primary, fallback=fallback)

    result = router.complete([], now=0.0)

    assert result.provider == "primary"
    assert result.completion.text == "来自本地"
    assert fallback.calls == 0


def test_falls_back_on_primary_failure():
    primary = FakeClient(error=ModelError("boom", status_code=503))
    fallback = FakeClient(responses=[_completion("来自云")])
    router = BrainRouter(primary=primary, fallback=fallback)

    result = router.complete([], now=0.0)

    assert result.provider == "fallback"
    assert result.fell_back is True
    assert result.completion.text == "来自云"


def test_demotes_after_consecutive_failures():
    primary = FakeClient(error=ModelError("boom", status_code=503))
    fallback = FakeClient(responses=[_completion()] * 3)
    router = BrainRouter(primary=primary, fallback=fallback, failure_threshold=2)

    router.complete([], now=0.0)
    router.complete([], now=1.0)
    assert not router.primary_healthy

    calls_before = primary.calls
    router.complete([], now=2.0)

    assert primary.calls == calls_before
    assert fallback.calls == 3


def test_recovers_after_cooldown_when_primary_works_again():
    primary = FakeClient(error=ModelError("boom", status_code=503))
    fallback = FakeClient(responses=[_completion()] * 5)
    router = BrainRouter(
        primary=primary, fallback=fallback, failure_threshold=1, recovery_seconds=30
    )

    router.complete([], now=0.0)
    assert not router.primary_healthy

    primary.error = None
    primary.responses = [_completion("恢复了")]
    result = router.complete([], now=31.0)

    assert result.provider == "primary"
    assert result.completion.text == "恢复了"
    assert router.primary_healthy


def test_client_error_does_not_fall_back():
    primary = FakeClient(error=ModelError("bad payload", status_code=400))
    fallback = FakeClient(responses=[_completion()])
    router = BrainRouter(primary=primary, fallback=fallback)

    with pytest.raises(ModelError, match="bad payload"):
        router.complete([], now=0.0)

    assert fallback.calls == 0


def test_both_channels_failing_marks_demoted():
    primary = FakeClient(error=ModelError("down", status_code=503))
    fallback = FakeClient(error=ModelError("also down", status_code=503))
    router = BrainRouter(primary=primary, fallback=fallback)

    with pytest.raises(ModelError, match="also down"):
        router.complete([], now=0.0)

    assert not router.primary_healthy


def test_demote_skips_primary_immediately():
    primary = FakeClient(responses=[_completion("本地")])
    fallback = FakeClient(responses=[_completion("云")])
    router = BrainRouter(primary=primary, fallback=fallback, recovery_seconds=60)

    router.demote(now=0.0)
    result = router.complete([], now=1.0)

    assert result.provider == "fallback"
    assert primary.calls == 0
