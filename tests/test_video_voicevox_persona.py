"""视频解析、VOICEVOX 音色、人物卡接口。"""

from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import HTTPException

from paa import api
from paa.adapters.onebot import parse_event
from paa.media.contracts import MediaRef, ResultStatus
from paa.media.providers.tts_voicevox import VoicevoxTTSProvider
from paa.media.video import VideoError, extract

MP4 = b"\x00\x00\x00\x20ftypisom" + b"0" * 64
WAV = b"RIFF\x00\x00\x00\x00WAVE" + b"0" * 4096


# ── 入站视频段 ───────────────────────────────────────────────
def test_video_segment_is_recognised():
    msg = parse_event(
        {
            "post_type": "message",
            "message_type": "private",
            "self_id": 1,
            "user_id": 2,
            "message": [{"type": "video", "data": {"url": "https://cdn.example/v.mp4", "file": "v.mp4"}}],
        }
    )
    assert msg is not None
    assert msg.media[0].kind == "video"
    assert msg.text == "[视频]"


# ── 视频抽帧/抽音轨 ─────────────────────────────────────────
def test_video_extract_produces_frames_and_audio(tmp_path: Path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(MP4)
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"bin")
    (tmp_path / "ffprobe.exe").write_bytes(b"bin")
    out_dir = tmp_path / "out"
    ref = MediaRef(kind="video", source="file", locator=str(source), name="clip.mp4")

    class _Done:
        returncode = 0
        stderr = b""
        stdout = b"12.5"

    def fake_run(argv, **kwargs):
        target = Path(argv[-1])
        if target.suffix == ".png":
            prefix = target.name.split("_")[0]
            for i in (1, 2):
                (out_dir / f"{prefix}_{i:02d}.png").write_bytes(b"\x89PNG")
        elif target.suffix == ".wav":
            target.write_bytes(WAV)
        return _Done()

    monkeypatch.setattr("paa.media.video._run", fake_run)
    assets = extract(ref, ffmpeg=ffmpeg, out_dir=out_dir, frames=2)
    assert len(assets.frames) == 2
    assert assets.audio is not None and assets.audio.exists()


def test_video_extract_requires_ffmpeg(tmp_path: Path):
    ref = MediaRef(kind="video", source="file", locator=str(tmp_path / "x.mp4"))
    try:
        extract(ref, ffmpeg=tmp_path / "missing.exe", out_dir=tmp_path)
        raise AssertionError("应当抛错")
    except VideoError as err:
        assert err.code == "E_FFMPEG_MISSING"


# ── VOICEVOX ─────────────────────────────────────────────────
def _voicevox(handler) -> VoicevoxTTSProvider:
    return VoicevoxTTSProvider(
        base_url="http://127.0.0.1:50021", transport=httpx.MockTransport(handler)
    )


def test_voicevox_available_and_voices():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            return httpx.Response(200, json="0.21.0")
        if request.url.path == "/speakers":
            return httpx.Response(200, json=[{"name": "ずんだもん", "styles": [{"id": 3, "name": "ノーマル"}]}])
        return httpx.Response(404)

    provider = _voicevox(handler)
    assert provider.available() is True
    voices = provider.voices()
    assert voices[0].speaker_id == 3 and voices[0].credit == "ずんだもん"


def test_voicevox_synthesize(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/audio_query":
            return httpx.Response(200, json={"speedScale": 1.0})
        if request.url.path == "/synthesis":
            return httpx.Response(200, content=WAV)
        return httpx.Response(404)

    result = _voicevox(handler).synthesize_speech("こんにちは", out_dir=tmp_path, voice_id="3")
    assert result.status is ResultStatus.OK
    assert Path(str(result.data["path"])).is_file()


def test_voicevox_reports_engine_down(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    result = _voicevox(handler).synthesize_speech("hi", out_dir=tmp_path)
    assert result.status is ResultStatus.FAILED
    assert result.error_code == "E_ENGINE_DOWN"


# ── 人物卡 ───────────────────────────────────────────────────
def test_persona_round_trip(tmp_path: Path, monkeypatch):
    persona = tmp_path / "persona.md"
    persona.write_text("旧的角色卡", encoding="utf-8")
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(persona_path="persona.md"))
    import paa.persona as persona_mod

    monkeypatch.setattr(persona_mod, "PROJECT_ROOT", tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(qq=None)))

    got = api.get_persona()
    assert got["exists"] is True and got["text"] == "旧的角色卡"

    saved = api.save_persona({"text": "新的角色卡：温柔一点"}, request)
    assert saved["saved"] is True
    assert persona.read_text(encoding="utf-8") == "新的角色卡：温柔一点"
    assert api.get_persona()["chars"] == len("新的角色卡：温柔一点")


def test_persona_rejects_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(persona_path="persona.md"))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(qq=None)))
    try:
        api.save_persona({"text": "  "}, request)
        raise AssertionError("应当拒绝")
    except HTTPException as err:
        assert err.status_code == 400
