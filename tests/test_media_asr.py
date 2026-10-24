"""语音链路：转码参数、侧车协议、Provider 与闸门。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from paa.media import audio as audio_mod
from paa.media import worker_client
from paa.media.contracts import MediaInput, MediaRef, ResultStatus
from paa.media.fetcher import MediaFetchError, fetch, sniff
from paa.media.providers.asr_sidecar import ASRSidecarProvider
from paa.media.router import MediaRouter, MediaSettings
from paa.media.stickers import StickerLibrary
from paa.media.worker_client import WorkerError, call_worker

AMR = b"#!AMR\n" + b"0" * 64
WAV = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 32


# ── 转码 ─────────────────────────────────────────────────────
def _fake_run(argv, **kwargs):
    target = Path(argv[-1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(WAV)
    return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


def test_to_wav16k_builds_array_args(tmp_path: Path, monkeypatch):
    captured: dict = {}

    def fake(argv, **kwargs):
        captured["argv"] = argv
        return _fake_run(argv, **kwargs)

    monkeypatch.setattr(audio_mod.subprocess, "run", fake)
    src = tmp_path / "a.amr"
    src.write_bytes(AMR)
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"bin")

    out = audio_mod.to_wav16k(src, ffmpeg=ffmpeg, out_dir=tmp_path / "out")

    argv = captured["argv"]
    assert argv[0].endswith("ffmpeg.exe")
    assert "-ar" in argv and argv[argv.index("-ar") + 1] == "16000"
    assert "-ac" in argv and argv[argv.index("-ac") + 1] == "1"
    assert out.is_file()
    # 绝不能是 shell 字符串
    assert isinstance(argv, list)


def test_to_wav16k_reports_decode_failure(tmp_path: Path, monkeypatch):
    def fake(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"bad data")

    monkeypatch.setattr(audio_mod.subprocess, "run", fake)
    src = tmp_path / "a.amr"
    src.write_bytes(AMR)
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"bin")

    with pytest.raises(audio_mod.AudioError) as err:
        audio_mod.to_wav16k(src, ffmpeg=ffmpeg, out_dir=tmp_path)
    assert err.value.code == "E_DECODE_FAILED"


def test_to_wav16k_requires_ffmpeg(tmp_path: Path):
    src = tmp_path / "a.amr"
    src.write_bytes(AMR)
    with pytest.raises(audio_mod.AudioError) as err:
        audio_mod.to_wav16k(src, ffmpeg=tmp_path / "missing.exe", out_dir=tmp_path)
    assert err.value.code == "E_FFMPEG_MISSING"


# ── 侧车协议 ─────────────────────────────────────────────────
def _worker(tmp_path: Path) -> tuple[Path, Path]:
    py = tmp_path / "python.exe"
    py.write_bytes(b"bin")
    script = tmp_path / "worker.py"
    script.write_text("# stub", encoding="utf-8")
    return py, script


def test_worker_parses_ok(tmp_path: Path, monkeypatch):
    py, script = _worker(tmp_path)

    def fake(argv, **kwargs):
        assert kwargs["input"].endswith(b"\n")
        # 必须强制子进程 UTF-8，否则中文 Windows 上输出是 GBK
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        assert kwargs["env"]["PYTHONUTF8"] == "1"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "ok", "text": "你好"}, ensure_ascii=False).encode(),
            stderr=b"",
        )

    monkeypatch.setattr(worker_client.subprocess, "run", fake)
    result = call_worker(python_exe=py, script=script, payload={"wav_path": "x"})
    assert result["text"] == "你好"


def test_worker_surfaces_error(tmp_path: Path, monkeypatch):
    py, script = _worker(tmp_path)

    def fake(argv, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({"status": "error", "code": "E_WORKER", "detail": "boom"}).encode(),
            stderr=b"",
        )

    monkeypatch.setattr(worker_client.subprocess, "run", fake)
    with pytest.raises(WorkerError) as err:
        call_worker(python_exe=py, script=script, payload={})
    assert err.value.code == "E_WORKER"


def test_worker_empty_output(tmp_path: Path, monkeypatch):
    py, script = _worker(tmp_path)

    def fake(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"traceback")

    monkeypatch.setattr(worker_client.subprocess, "run", fake)
    with pytest.raises(WorkerError) as err:
        call_worker(python_exe=py, script=script, payload={})
    assert err.value.code == "E_EMPTY_OUTPUT"


def test_worker_requires_files(tmp_path: Path):
    with pytest.raises(WorkerError) as err:
        call_worker(python_exe=tmp_path / "nope.exe", script=tmp_path / "nope.py", payload={})
    assert err.value.code == "E_PYTHON_MISSING"


# ── Provider ─────────────────────────────────────────────────
def _provider(tmp_path: Path, **kwargs) -> ASRSidecarProvider:
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"bin")
    py = tmp_path / "python.exe"
    py.write_bytes(b"bin")
    script = tmp_path / "worker.py"
    script.write_text("# stub", encoding="utf-8")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model.int8.onnx").write_bytes(b"m")
    (model_dir / "tokens.txt").write_text("t", encoding="utf-8")
    return ASRSidecarProvider(
        ffmpeg=ffmpeg, python_exe=py, worker_script=script, model_dir=model_dir, **kwargs
    )


def test_provider_passes_wav_straight_through(tmp_path: Path, monkeypatch):
    provider = _provider(tmp_path)
    wav = tmp_path / "a.wav"
    wav.write_bytes(WAV)
    item = MediaInput(MediaRef("audio", "file", str(wav)), wav, "audio/wav", len(WAV), "h")

    monkeypatch.setattr(
        "paa.media.providers.asr_sidecar.call_persistent",
        lambda **kwargs: {"status": "ok", "text": "今天天气不错", "audio_sec": 3.2},
    )
    result = provider.recognize_audio(item)
    assert result.status is ResultStatus.OK
    assert result.text == "今天天气不错"


def test_provider_transcodes_amr(tmp_path: Path, monkeypatch):
    provider = _provider(tmp_path)
    amr = tmp_path / "a.amr"
    amr.write_bytes(AMR)
    item = MediaInput(MediaRef("audio", "file", str(amr)), amr, "audio/amr", len(AMR), "h")

    called = {}

    def fake_transcode(source, **kwargs):
        called["source"] = source
        wav = tmp_path / "converted.wav"
        wav.write_bytes(WAV)
        return wav

    monkeypatch.setattr("paa.media.providers.asr_sidecar.to_wav16k", fake_transcode)
    monkeypatch.setattr(
        "paa.media.providers.asr_sidecar.call_persistent",
        lambda **kwargs: {"status": "ok", "text": "喂", "audio_sec": 1.0},
    )
    result = provider.recognize_audio(item)
    assert called["source"] == amr
    assert result.status is ResultStatus.OK


def test_provider_empty_transcript_is_degraded(tmp_path: Path, monkeypatch):
    provider = _provider(tmp_path)
    wav = tmp_path / "a.wav"
    wav.write_bytes(WAV)
    item = MediaInput(MediaRef("audio", "file", str(wav)), wav, "audio/wav", len(WAV), "h")

    monkeypatch.setattr(
        "paa.media.providers.asr_sidecar.call_persistent",
        lambda **kwargs: {"status": "ok", "text": "  "},
    )
    result = provider.recognize_audio(item)
    assert result.status is ResultStatus.DEGRADED


def test_provider_unavailable_when_model_missing(tmp_path: Path):
    provider = _provider(tmp_path)
    (provider.model_dir / "model.int8.onnx").unlink()
    assert provider.available() is False


# ── 抓取与闸门 ───────────────────────────────────────────────
def test_sniff_recognises_amr():
    assert sniff(AMR) == ("audio/amr", ".amr")


def test_fetch_rejects_audio_unless_allowed(tmp_path: Path):
    src = tmp_path / "a.amr"
    src.write_bytes(AMR)
    ref = MediaRef("audio", "file", str(src))
    with pytest.raises(MediaFetchError) as err:
        fetch(ref, out_dir=tmp_path / "o")
    assert err.value.code == "E_MIME_MISMATCH"

    item = fetch(ref, out_dir=tmp_path / "o", allow_audio=True)
    assert item.mime == "audio/amr"


def test_router_asr_disabled_is_denied(tmp_path: Path):
    router = MediaRouter(
        settings=MediaSettings(enabled=True, asr_enabled=False),
        library=StickerLibrary(),
        asr=None,
        tmp_dir=tmp_path,
    )
    result = router.transcribe_audio(MediaRef("audio", "file", "x"), chat_key="c")
    assert result.status is ResultStatus.DENIED
    assert result.error_detail == "asr_disabled"
