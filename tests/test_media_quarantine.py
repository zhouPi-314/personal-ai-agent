"""学习线隔离区：收录、去重、配额、晋级、丢弃。"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from paa.media.contracts import MediaInput, MediaRef
from paa.media.quarantine import Quarantine
from paa.media.stickers import INDEX_NAME, TAGS, StickerLibrary

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40
NOW = datetime(2026, 10, 24, 15, 0, 0)


def _item(tmp_path: Path, *, name: str = "a.png", data: bytes = PNG) -> MediaInput:
    source = tmp_path / "src" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    return MediaInput(
        ref=MediaRef(kind="image", source="file", locator=str(source)),
        local_path=source,
        mime="image/png",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _store(tmp_path: Path, **kwargs) -> Quarantine:
    return Quarantine(tmp_path / "quarantine", **kwargs)


def test_offer_puts_item_in_pending(tmp_path: Path):
    store = _store(tmp_path)
    status, reason = store.offer(
        _item(tmp_path), actor="qq:1", chat_key="private:1", context_text="哈哈哈", now=NOW
    )
    assert (status, reason) == ("pending", "ok")
    pending = store.pending()
    assert len(pending) == 1
    assert pending[0].tag_guess == "开心"
    assert (store.root / pending[0].file).is_file()


def test_offer_dedupes_by_hash(tmp_path: Path):
    store = _store(tmp_path)
    store.offer(_item(tmp_path), actor="qq:1", chat_key="c", now=NOW)
    status, reason = store.offer(_item(tmp_path), actor="qq:1", chat_key="c", now=NOW)
    assert (status, reason) == ("duplicate", "already_seen")


def test_daily_cap(tmp_path: Path):
    store = _store(tmp_path, daily_cap=2)
    for index in range(2):
        store.offer(
            _item(tmp_path, name=f"{index}.png", data=PNG + bytes([index])),
            actor="qq:1",
            chat_key="c",
            now=NOW,
        )
    status, reason = store.offer(
        _item(tmp_path, name="x.png", data=PNG + b"x"), actor="qq:1", chat_key="c", now=NOW
    )
    assert (status, reason) == ("cap", "daily_cap")


def test_total_cap(tmp_path: Path):
    store = _store(tmp_path, daily_cap=100, total_cap=1)
    store.offer(_item(tmp_path), actor="qq:1", chat_key="c", now=NOW)
    status, reason = store.offer(
        _item(tmp_path, name="b.png", data=PNG + b"b"), actor="qq:1", chat_key="c", now=NOW
    )
    assert (status, reason) == ("cap", "total_cap")


def test_unsupported_suffix_is_rejected(tmp_path: Path):
    store = _store(tmp_path)
    status, reason = store.offer(_item(tmp_path, name="a.bmp"), actor="qq:1", chat_key="c", now=NOW)
    assert (status, reason) == ("reject", "unsupported_format")


def test_promote_moves_file_and_appends_index(tmp_path: Path):
    store = _store(tmp_path)
    item = _item(tmp_path)
    store.offer(item, actor="qq:1", chat_key="c", context_text="气死我了", now=NOW)
    stickers = tmp_path / "stickers"

    dest = store.promote(item.sha256[:8], sticker_root=stickers, captured_at="2026-10-24")
    assert Path(dest).is_file()
    assert Path(dest).parent.name == "生气"

    index = json.loads((stickers / INDEX_NAME).read_text(encoding="utf-8"))
    assert len(index["entries"]) == 1
    assert index["entries"][0]["license"] == "owner-provided"
    assert index["entries"][0]["source_url"].startswith("chat:")

    library = StickerLibrary.load(stickers)
    assert len(library) == 1
    assert library.tags() == ("生气",)

    assert store.pending() == ()
    assert store.stats()["promoted"] == 1


def test_promote_requires_tag_when_guess_empty(tmp_path: Path):
    store = _store(tmp_path)
    item = _item(tmp_path)
    store.offer(item, actor="qq:1", chat_key="c", context_text="明天九点开会", now=NOW)
    with pytest.raises(ValueError):
        store.promote(item.sha256, sticker_root=tmp_path / "stickers")


def test_promote_with_explicit_tag_overrides_guess(tmp_path: Path):
    store = _store(tmp_path)
    item = _item(tmp_path)
    store.offer(item, actor="qq:1", chat_key="c", context_text="哈哈哈", now=NOW)
    dest = store.promote(item.sha256, sticker_root=tmp_path / "stickers", tag="无语")
    assert Path(dest).parent.name == "无语"
    assert "无语" in TAGS


def test_promote_twice_fails(tmp_path: Path):
    store = _store(tmp_path)
    item = _item(tmp_path)
    store.offer(item, actor="qq:1", chat_key="c", context_text="哈哈", now=NOW)
    store.promote(item.sha256, sticker_root=tmp_path / "stickers")
    with pytest.raises(ValueError):
        store.promote(item.sha256, sticker_root=tmp_path / "stickers")


def test_reject_removes_file(tmp_path: Path):
    store = _store(tmp_path)
    item = _item(tmp_path)
    store.offer(item, actor="qq:1", chat_key="c", now=NOW)
    stored = store.root / store.pending()[0].file
    assert stored.is_file()

    assert store.reject(item.sha256[:8]) is True
    assert not stored.exists()
    assert store.stats()["rejected"] == 1
    assert store.pending() == ()


def test_reject_unknown_returns_false(tmp_path: Path):
    assert _store(tmp_path).reject("deadbeef") is False


def test_missing_manifest_means_empty(tmp_path: Path):
    store = _store(tmp_path)
    assert store.pending() == ()
    assert store.stats() == {"total": 0, "pending": 0, "promoted": 0, "rejected": 0}
