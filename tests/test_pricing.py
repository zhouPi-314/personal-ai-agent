import json

from paa import pricing
from paa.config import get_settings


def test_missing_file_yields_no_prices(monkeypatch, tmp_path):
    monkeypatch.setenv("PAA_PRICING_PATH", "nope.json")
    get_settings.cache_clear()
    try:
        assert pricing.load_prices() == {}
    finally:
        get_settings.cache_clear()


def test_free_model_costs_zero(monkeypatch, tmp_path):
    file = tmp_path / "pricing.json"
    file.write_text(
        json.dumps({"models": {"free-x": {"input_per_mtok": 0, "output_per_mtok": 0}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PAA_PRICING_PATH", str(file))
    get_settings.cache_clear()
    try:
        assert pricing.cost_of("free-x", 1_000_000, 1_000_000) == 0.0
    finally:
        get_settings.cache_clear()


def test_paid_model_math(monkeypatch, tmp_path):
    file = tmp_path / "pricing.json"
    file.write_text(
        json.dumps({"models": {"paid": {"input_per_mtok": 2, "output_per_mtok": 8}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PAA_PRICING_PATH", str(file))
    get_settings.cache_clear()
    try:
        # 50 万输入 + 25 万输出 = 1 元 + 2 元
        assert pricing.cost_of("paid", 500_000, 250_000) == 3.0
    finally:
        get_settings.cache_clear()


def test_unknown_model_returns_none():
    assert pricing.cost_of("never-registered", 1, 1) is None
