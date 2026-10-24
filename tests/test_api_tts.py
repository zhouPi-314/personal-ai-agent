"""语音偏好接口：读取、保存、试听（不依赖真实模型）。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from paa import api
from paa.media import tts_settings
from paa.media.contracts import MediaResult, ResultStatus


def _settings(tmp_path: Path, **overrides):
    base = {
        "media_tts_enabled": True,
        "media_tts_mode": "voice_input",
        "media_tts_provider": "kokoro",
        "media_tts_kokoro_dir": str(tmp_path / "kokoro"),
        "media_tts_max_chars": 120,
        "media_tts_voice": "Microsoft Huihui Desktop",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def prefs_path(tmp_path: Path, monkeypatch):
    path = tmp_path / "data" / "media" / "tts.json"
    monkeypatch.setattr(api, "TTS_PREFS_PATH", path)
    model_dir = tmp_path / "kokoro"
    model_dir.mkdir()
    for name in ("zf_001", "zf_002"):
        (model_dir / f"{name}.bin").write_bytes(b"v")
    monkeypatch.setattr(api, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    return path


def test_get_returns_defaults_and_voices(prefs_path: Path):
    data = api.get_tts_prefs()
    assert data["voice"] == tts_settings.DEFAULT_VOICE
    assert data["voices"] == ["zf_001", "zf_002"]
    assert data["speed_range"] == [tts_settings.MIN_SPEED, tts_settings.MAX_SPEED]


def test_save_persists_voice_and_speed(prefs_path: Path):
    saved = api.set_tts_prefs({"voice": "zf_002", "speed": 0.8})
    assert saved == {"voice": "zf_002", "speed": 0.8}
    assert api.get_tts_prefs()["voice"] == "zf_002"


def test_save_rejects_unknown_voice(prefs_path: Path):
    with pytest.raises(HTTPException) as err:
        api.set_tts_prefs({"voice": "不存在"})
    assert err.value.status_code == 400


def test_save_clamps_speed(prefs_path: Path):
    saved = api.set_tts_prefs({"voice": "zf_001", "speed": 9.0})
    assert saved["speed"] == tts_settings.MAX_SPEED


def test_save_rejects_bad_speed(prefs_path: Path):
    with pytest.raises(HTTPException):
        api.set_tts_prefs({"voice": "zf_001", "speed": "fast"})


def test_preview_returns_wav(prefs_path: Path, monkeypatch, tmp_path: Path):
    wav = tmp_path / "preview.wav"
    wav.write_bytes(b"RIFF0000WAVE" + b"0" * 64)

    class _Provider:
        def synthesize_speech(self, text, **kwargs):
            return MediaResult(
                status=ResultStatus.OK,
                capability="synthesize_speech",
                data={"path": str(wav)},
            )

    monkeypatch.setattr(api, "build_tts", lambda settings, root: _Provider())
    response = api.preview_tts({})
    assert response.media_type == "audio/wav"
    assert response.body.startswith(b"RIFF")


def test_preview_fails_when_disabled(prefs_path: Path, monkeypatch):
    monkeypatch.setattr(api, "get_settings", lambda: _settings(prefs_path.parent, media_tts_enabled=False))
    with pytest.raises(HTTPException) as err:
        api.preview_tts({})
    assert err.value.status_code == 409
