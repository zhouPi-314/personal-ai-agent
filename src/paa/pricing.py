"""价格表：模型 → 每百万 token 单价（元）。

找不到价格时返回 None，让调用方显示「未知」——猜一个数比不显示更糟。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .config import PROJECT_ROOT, get_settings


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float


def load_prices() -> dict[str, Price]:
    path = PROJECT_ROOT / get_settings().pricing_path
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    models = data.get("models") or {}
    prices: dict[str, Price] = {}
    for name, raw in models.items():
        try:
            prices[name] = Price(
                input_per_mtok=float(raw["input_per_mtok"]),
                output_per_mtok=float(raw["output_per_mtok"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return prices


def cost_of(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = load_prices().get(model)
    if price is None:
        return None
    return (
        input_tokens / 1_000_000 * price.input_per_mtok
        + output_tokens / 1_000_000 * price.output_per_mtok
    )
