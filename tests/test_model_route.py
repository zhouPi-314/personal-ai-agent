"""模型路由切换：强制本地 / 强制云端 / 自动。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from paa import api
from paa.llm.client import Completion, ModelError
from paa.llm.router import BrainRouter


class _Client:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls = 0

    def complete(self, messages, *, temperature=1.0):
        self.calls += 1
        if self.fail:
            raise ModelError("boom")
        return Completion(text=self.name, model=self.name, input_tokens=1, output_tokens=1)


def test_auto_mode_prefers_primary():
    primary, fallback = _Client("p"), _Client("c")
    router = BrainRouter(primary=primary, fallback=fallback)
    result = router.complete([{"role": "user", "content": "hi"}])
    assert result.provider == "primary" and primary.calls == 1


def test_forced_fallback_skips_primary():
    primary, fallback = _Client("p"), _Client("c")
    router = BrainRouter(primary=primary, fallback=fallback)
    router.set_mode("fallback")
    result = router.complete([{"role": "user", "content": "hi"}])
    assert result.provider == "fallback"
    assert primary.calls == 0


def test_forced_primary_does_not_fall_back():
    primary, fallback = _Client("p", fail=True), _Client("c")
    router = BrainRouter(primary=primary, fallback=fallback)
    router.set_mode("primary")
    with pytest.raises(ModelError):
        router.complete([{"role": "user", "content": "hi"}])
    assert fallback.calls == 0


def test_unknown_mode_falls_back_to_auto():
    router = BrainRouter(primary=_Client("p"), fallback=_Client("c"))
    assert router.set_mode("whatever") == "auto"


def test_route_api_round_trip(tmp_path: Path, monkeypatch):
    route_file = tmp_path / "model_route.json"
    monkeypatch.setattr(api, "ROUTE_PATH", route_file)
    router = BrainRouter(primary=_Client("p"), fallback=_Client("c"))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(router=router)))
    monkeypatch.setattr(
        api, "get_settings", lambda: SimpleNamespace(local_model="local-x", model_name="cloud-y", model_base_url="u", model_api_key="k")
    )

    assert api.get_model_route(request)["mode"] == "auto"
    assert api.set_model_route({"mode": "fallback"}, request)["mode"] == "fallback"
    assert router.mode == "fallback"
    assert route_file.is_file()
    assert api.get_model_route(request)["mode"] == "fallback"


def test_route_api_without_router(tmp_path: Path):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(router=None)))
    with pytest.raises(HTTPException):
        api.set_model_route({"mode": "fallback"}, request)
