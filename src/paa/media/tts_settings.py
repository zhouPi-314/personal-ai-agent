"""语音合成偏好：存在 data/ 下的一个小 JSON，供维护台读写。

不放进 .env，是因为它要能在面板上随时改、立即生效；
.env 只放"能不能用"这类部署期开关。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_VOICE = "zf_001"
DEFAULT_SPEED = 1.0
MIN_SPEED = 0.5
MAX_SPEED = 1.5


@dataclass(frozen=True)
class TtsPrefs:
    voice: str = DEFAULT_VOICE
    speed: float = DEFAULT_SPEED


def load(path: Path) -> TtsPrefs:
    if not path.is_file():
        return TtsPrefs()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return TtsPrefs()
    voice = str(data.get("voice") or DEFAULT_VOICE)
    try:
        speed = float(data.get("speed") or DEFAULT_SPEED)
    except (TypeError, ValueError):
        speed = DEFAULT_SPEED
    return TtsPrefs(voice=voice, speed=clamp_speed(speed))


def clamp_speed(value: float) -> float:
    return max(MIN_SPEED, min(MAX_SPEED, round(float(value), 2)))


def save(path: Path, prefs: TtsPrefs) -> TtsPrefs:
    cleaned = TtsPrefs(voice=prefs.voice or DEFAULT_VOICE, speed=clamp_speed(prefs.speed))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cleaned), ensure_ascii=False, indent=2), encoding="utf-8")
    return cleaned


def list_voices(model_dir: Path) -> list[str]:
    if not model_dir.is_dir():
        return []
    names = {item.stem for item in model_dir.glob("*.bin")}
    names |= {item.stem for item in (model_dir / "voices").glob("*.bin")}
    return sorted(names)
