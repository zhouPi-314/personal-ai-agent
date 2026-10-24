"""媒体拉取守卫：格式、大小、协议、私网地址。"""

import base64
import hashlib
from pathlib import Path

import httpx
import pytest

from paa.media import fetcher
from paa.media.contracts import MediaRef
from paa.media.fetcher import MediaFetchError, fetch, sniff

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40
JPEG = b"\xff\xd8\xff" + b"0" * 40


def test_sniff_recognises_common_formats():
    assert sniff(PNG) == ("image/png", ".png")
    assert sniff(JPEG) == ("image/jpeg", ".jpg")
    assert sniff(b"GIF89a" + b"0" * 20) == ("image/gif", ".gif")
    assert sniff(b"not an image") is None


def test_base64_source_round_trip(tmp_path: Path):
    ref = MediaRef(kind="image", source="base64", locator=base64.b64encode(PNG).decode())
    item = fetch(ref, out_dir=tmp_path)
    assert item.mime == "image/png"
    assert item.size_bytes == len(PNG)
    assert item.sha256 == hashlib.sha256(PNG).hexdigest()
    assert item.local_path.is_file()


def test_file_source_reads_local_file(tmp_path: Path):
    source = tmp_path / "a.png"
    source.write_bytes(PNG)
    item = fetch(MediaRef(kind="image", source="file", locator=str(source)), out_dir=tmp_path / "out")
    assert item.local_path.parent.name == "out"
    assert item.local_path.read_bytes() == PNG


def test_file_source_missing_raises(tmp_path: Path):
    with pytest.raises(MediaFetchError) as err:
        fetch(MediaRef(kind="image", source="file", locator=str(tmp_path / "nope.png")), out_dir=tmp_path)
    assert err.value.code == "E_NOT_FOUND"


def test_size_limit_is_enforced(tmp_path: Path):
    source = tmp_path / "big.png"
    source.write_bytes(PNG * 100)
    with pytest.raises(MediaFetchError) as err:
        fetch(MediaRef(kind="image", source="file", locator=str(source)), out_dir=tmp_path, max_bytes=32)
    assert err.value.code == "E_TOO_LARGE"


def test_fake_extension_is_rejected(tmp_path: Path):
    source = tmp_path / "evil.png"
    source.write_bytes(b"<html>not an image</html>")
    with pytest.raises(MediaFetchError) as err:
        fetch(MediaRef(kind="image", source="file", locator=str(source)), out_dir=tmp_path)
    assert err.value.code == "E_MIME_MISMATCH"


def test_non_http_scheme_is_rejected(tmp_path: Path):
    with pytest.raises(MediaFetchError) as err:
        fetch(MediaRef(kind="image", source="url", locator="gopher://example.com/x"), out_dir=tmp_path)
    assert err.value.code == "E_SCHEME_NOT_ALLOWED"


def test_loopback_url_is_blocked(tmp_path: Path):
    with pytest.raises(MediaFetchError) as err:
        fetch(MediaRef(kind="image", source="url", locator="http://127.0.0.1/a.png"), out_dir=tmp_path)
    assert err.value.code == "E_PRIVATE_ADDRESS"


def test_http_source_uses_injected_transport(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(fetcher, "_is_blocked", lambda host: False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PNG)

    item = fetch(
        MediaRef(kind="image", source="url", locator="https://example.com/a.png"),
        out_dir=tmp_path,
        transport=httpx.MockTransport(handler),
    )
    assert item.mime == "image/png"


def test_http_source_stops_at_size_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(fetcher, "_is_blocked", lambda host: False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PNG * 100)

    with pytest.raises(MediaFetchError) as err:
        fetch(
            MediaRef(kind="image", source="url", locator="https://example.com/big.png"),
            out_dir=tmp_path,
            max_bytes=64,
            transport=httpx.MockTransport(handler),
        )
    assert err.value.code == "E_TOO_LARGE"
