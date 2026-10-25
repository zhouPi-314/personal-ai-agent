"""音色登记表：每条音色都要有来源与授权状态。

存 data/voices/index.json，文件本身放 data/voices/（不进 Git）。
默认只接受「明确允许二创」或「本人授权」的音色，登记时二选一必填。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

INDEX = "index.json"
LICENSE_KINDS = ("derivative-allowed", "self-authorized")


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    file: str
    license_kind: str
    source: str = ""
    credit: str = ""
    authorized_by: str = ""
    created_at: str = ""


def _index_path(root: Path) -> Path:
    return root / INDEX


def load(root: Path | str) -> list[Voice]:
    base = Path(root)
    path = _index_path(base)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    voices = []
    for item in data.get("voices", []) if isinstance(data, dict) else []:
        try:
            voices.append(Voice(**item))
        except TypeError:
            continue
    return voices


def save(root: Path | str, voices: list[Voice]) -> None:
    base = Path(root)
    base.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "voices": [asdict(voice) for voice in voices]}
    _index_path(base).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def register(
    root: Path | str,
    *,
    name: str,
    file: str,
    license_kind: str,
    source: str = "",
    credit: str = "",
    authorized_by: str = "",
    created_at: str = "",
) -> Voice:
    if license_kind not in LICENSE_KINDS:
        raise ValueError("license_kind 必须是 " + " / ".join(LICENSE_KINDS))
    if not name.strip() or not file.strip():
        raise ValueError("name 与 file 必填")
    voices = load(root)
    voice = Voice(
        id=uuid.uuid4().hex[:12],
        name=name.strip(),
        file=file.strip(),
        license_kind=license_kind,
        source=source.strip(),
        credit=credit.strip(),
        authorized_by=authorized_by.strip(),
        created_at=created_at,
    )
    voices.append(voice)
    save(root, voices)
    return voice


def resolve(root: Path | str, voice_id: str) -> Voice | None:
    target = (voice_id or "").strip()
    if not target:
        return None
    for voice in load(root):
        if voice.id == target or voice.name == target:
            return voice
    return None
