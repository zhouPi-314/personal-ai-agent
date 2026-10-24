"""素材库：加载校验、检索、去重、限频、索引重建。"""

import hashlib
import json
import random
from pathlib import Path

import pytest

from paa.media.stickers import (
    INDEX_NAME,
    MAX_BYTES,
    StickerLibrary,
    StickerRateLimiter,
)

TAG = "开心"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_library(tmp_path: Path, entries: list[dict], *, write_files: bool = True):
    root = tmp_path / "stickers"
    (root / TAG).mkdir(parents=True, exist_ok=True)
    for entry in entries:
        rel = entry["file"]
        target = root / rel
        if write_files and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"PNG" + rel.encode())
    (root / INDEX_NAME).write_text(
        json.dumps({"version": 1, "entries": entries}, ensure_ascii=False), encoding="utf-8"
    )
    return root


def _entry(name: str, *, tag: str = TAG, license_name: str = "CC0-1.0", **extra) -> dict:
    payload = {
        "file": f"{tag}/{name}",
        "tag": tag,
        "license": license_name,
        "source_url": "https://example.invalid/a",
        "captured_at": "2026-10-24",
    }
    payload.update(extra)
    return payload


def test_missing_index_means_empty_library(tmp_path: Path):
    root = tmp_path / "none"
    root.mkdir()
    assert len(StickerLibrary.load(root)) == 0


def test_missing_dir_means_empty_library(tmp_path: Path):
    assert len(StickerLibrary.load(tmp_path / "nope")) == 0


def test_loads_valid_entry(tmp_path: Path):
    root = _make_library(tmp_path, [_entry("a.jpg")])
    library = StickerLibrary.load(root)
    assert len(library) == 1
    assert library.tags() == (TAG,)
    assert library.entries[0].sha256  # 索引没给哈希时会现算


def test_skips_entry_without_license(tmp_path: Path):
    root = _make_library(tmp_path, [_entry("a.jpg", license_name=""), _entry("b.jpg")])
    assert len(StickerLibrary.load(root)) == 1


def test_skips_unknown_tag(tmp_path: Path):
    root = _make_library(tmp_path, [_entry("a.jpg", tag="不存在"), _entry("b.jpg")])
    assert len(StickerLibrary.load(root)) == 1


def test_skips_path_traversal(tmp_path: Path):
    smuggled = _entry("b.jpg")
    smuggled["file"] = "../../secret.jpg"
    root = _make_library(tmp_path, [smuggled, _entry("c.jpg")])
    assert len(StickerLibrary.load(root)) == 1


def test_skips_missing_file(tmp_path: Path):
    root = _make_library(tmp_path, [_entry("ghost.jpg"), _entry("b.jpg")])
    (root / TAG / "ghost.jpg").unlink()
    assert len(StickerLibrary.load(root)) == 1


def test_skips_oversized_file(tmp_path: Path):
    root = _make_library(tmp_path, [_entry("big.jpg"), _entry("small.jpg")])
    (root / TAG / "big.jpg").write_bytes(b"x" * (MAX_BYTES + 1))
    library = StickerLibrary.load(root)
    assert [entry.path.name for entry in library.entries] == ["small.jpg"]


def test_dedupes_identical_content(tmp_path: Path):
    shared = b"PNG-same"
    root = _make_library(tmp_path, [_entry("a.jpg"), _entry("b.jpg")])
    (root / TAG / "a.jpg").write_bytes(shared)
    (root / TAG / "b.jpg").write_bytes(shared)
    index = [_entry("a.jpg"), _entry("b.jpg")]
    for item in index:
        item["sha256"] = _sha(shared)
    (root / INDEX_NAME).write_text(json.dumps({"entries": index}), encoding="utf-8")
    assert len(StickerLibrary.load(root)) == 1


def test_pick_skips_recent_hashes(tmp_path: Path):
    root = _make_library(tmp_path, [_entry("a.jpg"), _entry("b.jpg")])
    library = StickerLibrary.load(root)
    first = library.pick(TAG, rng=random.Random(0))
    second = library.pick(TAG, recent=(first.sha256,), rng=random.Random(0))
    assert first is not None and second is not None
    assert first.sha256 != second.sha256


def test_pick_returns_none_when_everything_recent(tmp_path: Path):
    root = _make_library(tmp_path, [_entry("a.jpg")])
    library = StickerLibrary.load(root)
    entry = library.entries[0]
    assert library.pick(TAG, recent=(entry.sha256,)) is None


def test_pick_unknown_tag_returns_none(tmp_path: Path):
    root = _make_library(tmp_path, [_entry("a.jpg")])
    assert StickerLibrary.load(root).pick("生气") is None


def test_rebuild_index_requires_license(tmp_path: Path):
    root = tmp_path / "stickers"
    (root / TAG).mkdir(parents=True)
    (root / TAG / "a.jpg").write_bytes(b"PNG")
    with pytest.raises(ValueError):
        StickerLibrary.rebuild_index(root, license="  ", source_url="x", captured_at="")

    count = StickerLibrary.rebuild_index(
        root, license="CC0-1.0", source_url="https://example.invalid", captured_at="2026-10-24"
    )
    assert count == 1
    payload = json.loads((root / INDEX_NAME).read_text(encoding="utf-8"))
    assert payload["entries"][0]["license"] == "CC0-1.0"
    assert len(StickerLibrary.load(root)) == 1


def test_rebuild_index_ignores_unknown_tag_dir(tmp_path: Path):
    root = tmp_path / "stickers"
    (root / TAG).mkdir(parents=True)
    (root / "乱放").mkdir(parents=True)
    (root / TAG / "a.jpg").write_bytes(b"PNG")
    (root / "乱放" / "b.jpg").write_bytes(b"PNG")
    assert StickerLibrary.rebuild_index(
        root, license="CC0-1.0", source_url="x", captured_at=""
    ) == 1


# ── 限频 ──────────────────────────────────────────────────────
def test_rate_limiter_blocks_within_cooldown():
    limiter = StickerRateLimiter(cooldown_seconds=60, daily_cap=10)
    assert limiter.take("private:1", now=0.0, day="2026-10-24") == (True, "ok")
    allowed, why = limiter.take("private:1", now=10.0, day="2026-10-24")
    assert allowed is False and why == "cooldown"


def test_rate_limiter_allows_after_cooldown():
    limiter = StickerRateLimiter(cooldown_seconds=60, daily_cap=10)
    limiter.take("private:1", now=0.0, day="2026-10-24")
    assert limiter.take("private:1", now=61.0, day="2026-10-24") == (True, "ok")


def test_rate_limiter_enforces_daily_cap():
    limiter = StickerRateLimiter(cooldown_seconds=0, daily_cap=2)
    assert limiter.take("c", now=1.0, day="d1")[0] is True
    assert limiter.take("c", now=2.0, day="d1")[0] is True
    allowed, why = limiter.take("c", now=3.0, day="d1")
    assert allowed is False and why == "daily_cap"


def test_rate_limiter_resets_on_new_day():
    limiter = StickerRateLimiter(cooldown_seconds=0, daily_cap=1)
    limiter.take("c", now=1.0, day="d1")
    assert limiter.take("c", now=2.0, day="d2") == (True, "ok")


def test_rate_limiter_is_per_chat():
    limiter = StickerRateLimiter(cooldown_seconds=60, daily_cap=10)
    limiter.take("private:1", now=0.0, day="d")
    assert limiter.take("private:2", now=1.0, day="d") == (True, "ok")
