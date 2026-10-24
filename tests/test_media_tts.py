"""语音合成：SAPI Provider、发送段、闸门。"""

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from paa.adapters.onebot import OneBotSender
from paa.adapters.runner import OneBotRunner
from paa.chat.humanize import OutgoingMedia
from paa.media.contracts import ResultStatus
from paa.media.providers import tts_kokoro, tts_sapi
from paa.media.providers.tts_kokoro import KokoroTTSProvider
from paa.media.providers.tts_sapi import SapiTTSProvider
from paa.media.router import MediaRouter, MediaSettings
from paa.media.stickers import StickerLibrary

WAV = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 2048
BIG_WAV = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 8192


def _provider(tmp_path: Path, **kwargs) -> SapiTTSProvider:
    script = tmp_path / "tts.ps1"
    script.write_text("# stub", encoding="utf-8")
    return SapiTTSProvider(script=script, **kwargs)


def _fake_run(argv, **kwargs):
    out = Path(argv[argv.index("-OutFile") + 1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(WAV)
    return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


# ── Provider ─────────────────────────────────────────────────
def test_tts_success_writes_wav(tmp_path: Path, monkeypatch):
    captured: dict = {}

    def fake(argv, **kwargs):
        captured["argv"] = argv
        text_file = Path(argv[argv.index("-TextFile") + 1])
        captured["text"] = text_file.read_text(encoding="utf-8")
        return _fake_run(argv, **kwargs)

    monkeypatch.setattr(tts_sapi.subprocess, "run", fake)
    result = _provider(tmp_path).synthesize_speech("你好呀", out_dir=tmp_path / "out")

    assert result.status is ResultStatus.OK
    assert captured["text"] == "你好呀"
    assert Path(str(result.data["path"])).is_file()
    # 文本必须走文件，不能拼进命令行
    assert "你好呀" not in " ".join(captured["argv"])
    assert isinstance(captured["argv"], list)


def test_tts_rejects_empty_text(tmp_path: Path):
    result = _provider(tmp_path).synthesize_speech("   ", out_dir=tmp_path)
    assert result.status is ResultStatus.REJECTED
    assert result.error_code == "E_EMPTY_TEXT"


def test_tts_truncates_long_text(tmp_path: Path, monkeypatch):
    captured: dict = {}

    def fake(argv, **kwargs):
        captured["text"] = Path(argv[argv.index("-TextFile") + 1]).read_text(encoding="utf-8")
        return _fake_run(argv, **kwargs)

    monkeypatch.setattr(tts_sapi.subprocess, "run", fake)
    result = _provider(tmp_path, max_chars=5).synthesize_speech("一二三四五六七八", out_dir=tmp_path)
    assert result.status is ResultStatus.OK
    assert captured["text"] == "一二三四五"
    assert result.data["truncated"] is True
    assert result.limitations


def test_tts_failure_returns_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        tts_sapi.subprocess,
        "run",
        lambda argv, **kw: SimpleNamespace(returncode=4, stdout=b"", stderr=b"boom"),
    )
    result = _provider(tmp_path).synthesize_speech("你好", out_dir=tmp_path)
    assert result.status is ResultStatus.FAILED
    assert result.error_code == "E_SYNTH_FAILED"


def test_tts_unavailable_without_script(tmp_path: Path):
    provider = SapiTTSProvider(script=tmp_path / "missing.ps1")
    assert provider.available() is False
    assert provider.synthesize_speech("你好", out_dir=tmp_path).status is ResultStatus.FAILED


# ── 发送 ─────────────────────────────────────────────────────
def _sender(handler) -> OneBotSender:
    return OneBotSender(http_url="http://127.0.0.1:3000", transport=httpx.MockTransport(handler))


def test_send_record_uses_base64(tmp_path: Path):
    captured: dict = {}
    wav = tmp_path / "v.wav"
    wav.write_bytes(WAV)

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"status": "ok"})

    _sender(handler).send_record("private:1", wav)

    message = captured["body"]["message"]
    assert message[0]["type"] == "record"
    assert message[0]["data"]["file"].startswith("base64://")
    assert base64.b64encode(WAV).decode() in message[0]["data"]["file"]


def test_send_record_rejects_oversized(tmp_path: Path):
    captured = {}
    wav = tmp_path / "big.wav"
    wav.write_bytes(b"x" * 100)

    def handler(request: httpx.Request) -> httpx.Response:
        captured["hit"] = True
        return httpx.Response(200, json={"status": "ok"})

    with pytest.raises(ValueError):
        _sender(handler).send_record("private:1", wav, max_bytes=10)
    assert captured == {}


# ── 接收循环分发 ─────────────────────────────────────────────
class _Sender:
    def __init__(self) -> None:
        self.texts: list[tuple[str, str]] = []
        self.images: list[tuple[str, str]] = []
        self.records: list[tuple[str, str]] = []

    def send(self, chat_key: str, text: str) -> None:
        self.texts.append((chat_key, text))

    def send_image(self, chat_key: str, path: Path) -> None:
        self.images.append((chat_key, str(path)))

    def send_record(self, chat_key: str, path: Path) -> None:
        self.records.append((chat_key, str(path)))


def _event():
    return {
        "post_type": "message",
        "message_type": "private",
        "self_id": 100,
        "user_id": 200,
        "message": [{"type": "text", "data": {"text": "在吗"}}],
    }


def _runner(respond, sender) -> OneBotRunner:
    return OneBotRunner(
        ws_url="ws://127.0.0.1:3001",
        access_token="",
        self_id="100",
        sender=sender,
        respond=respond,
        owner_ids=frozenset({"200"}),
    )


@pytest.mark.asyncio
async def test_runner_dispatches_voice_part():
    sender = _Sender()

    async def respond(_message):
        return [OutgoingMedia(kind="voice", path=Path("v.wav"))]

    await _runner(respond, sender).handle(_event(), now=0.0)
    assert sender.records == [("private:200", "v.wav")]
    assert sender.images == []


@pytest.mark.asyncio
async def test_runner_voice_failure_falls_back_to_text():
    sender = _Sender()

    def boom(chat_key, path):
        raise RuntimeError("网关拒绝")

    sender.send_record = boom  # type: ignore[method-assign]

    async def respond(_message):
        return [OutgoingMedia(kind="voice", path=Path("v.wav"))]

    await _runner(respond, sender).handle(_event(), now=0.0)
    assert ("private:200", "想给你发条语音，没发出去") in sender.texts


# ── 闸门 ─────────────────────────────────────────────────────
# ── Kokoro Provider ─────────────────────────────────────────
def _kokoro(tmp_path: Path, **kwargs) -> KokoroTTSProvider:
    model_dir = tmp_path / "kokoro"
    model_dir.mkdir()
    (model_dir / "model_int8.onnx").write_bytes(b"m")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    (model_dir / "zf_001.bin").write_bytes(b"v")
    py = tmp_path / "python.exe"
    py.write_bytes(b"bin")
    script = tmp_path / "kokoro_worker.py"
    script.write_text("# stub", encoding="utf-8")
    return KokoroTTSProvider(
        python_exe=py, worker_script=script, model_dir=model_dir, **kwargs
    )


def test_kokoro_available_when_files_present(tmp_path: Path):
    assert _kokoro(tmp_path).available() is True


def test_kokoro_unavailable_without_model(tmp_path: Path):
    provider = _kokoro(tmp_path)
    (provider.model_dir / "model_int8.onnx").unlink()
    assert provider.available() is False


def test_kokoro_success_returns_wav(tmp_path: Path, monkeypatch):
    provider = _kokoro(tmp_path)
    out_dir = tmp_path / "out"

    def fake_worker(*, payload, **kwargs):
        Path(payload["out_wav"]).parent.mkdir(parents=True, exist_ok=True)
        Path(payload["out_wav"]).write_bytes(BIG_WAV)
        return {"status": "ok", "seconds": 1.5, "tts_ms": 120}

    monkeypatch.setattr(tts_kokoro, "call_worker", fake_worker)
    result = provider.synthesize_speech("你好", out_dir=out_dir)

    assert result.status is ResultStatus.OK
    assert Path(str(result.data["path"])).is_file()
    assert result.data["seconds"] == 1.5


def test_kokoro_worker_error_is_failed(tmp_path: Path, monkeypatch):
    provider = _kokoro(tmp_path)

    def boom(**kwargs):
        raise tts_kokoro.WorkerError("E_WORKER", "bad")

    monkeypatch.setattr(tts_kokoro, "call_worker", boom)
    result = provider.synthesize_speech("你好", out_dir=tmp_path / "o")
    assert result.status is ResultStatus.FAILED
    assert result.error_code == "E_WORKER"


def test_kokoro_truncates(tmp_path: Path, monkeypatch):
    provider = _kokoro(tmp_path, max_chars=3)
    captured: dict = {}

    def fake_worker(*, payload, **kwargs):
        captured["text"] = payload["text"]
        Path(payload["out_wav"]).parent.mkdir(parents=True, exist_ok=True)
        Path(payload["out_wav"]).write_bytes(BIG_WAV)
        return {"status": "ok", "seconds": 0.5}

    monkeypatch.setattr(tts_kokoro, "call_worker", fake_worker)
    result = provider.synthesize_speech("一二三四五", out_dir=tmp_path / "o")
    assert captured["text"] == "一二三"
    assert result.data["truncated"] is True


def test_router_tts_disabled_is_denied(tmp_path: Path):
    router = MediaRouter(
        settings=MediaSettings(enabled=True, tts_enabled=False),
        library=StickerLibrary(),
        tts=None,
        tmp_dir=tmp_path,
    )
    result = router.synthesize_speech("你好", chat_key="c")
    assert result.status is ResultStatus.DENIED
    assert result.error_detail == "tts_disabled"


def test_router_tts_without_provider_fails(tmp_path: Path):
    router = MediaRouter(
        settings=MediaSettings(enabled=True, tts_enabled=True),
        library=StickerLibrary(),
        tts=None,
        tmp_dir=tmp_path,
    )
    result = router.synthesize_speech("你好", chat_key="c")
    assert result.status is ResultStatus.FAILED
    assert result.error_code == "E_MODEL_UNAVAILABLE"
