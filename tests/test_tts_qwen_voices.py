"""音色登记与 Qwen3-TTS 克隆 Provider。"""

from pathlib import Path

from paa.media import voices as registry
from paa.media.contracts import ResultStatus
from paa.media.providers import tts_qwen

WAV = b"RIFF\x00\x00\x00\x00WAVE" + b"0" * 8192


def test_register_and_resolve(tmp_path: Path):
    ref = tmp_path / "a.wav"
    ref.write_bytes(WAV)
    voice = registry.register(
        tmp_path, name="测试音色", file="a.wav", license_kind="self-authorized",
        source="unit-test", authorized_by="owner", created_at="2026-10-25",
    )
    assert voice.id and voice.license_kind == "self-authorized"
    assert registry.resolve(tmp_path, "测试音色").id == voice.id
    assert registry.resolve(tmp_path, voice.id).name == "测试音色"
    assert registry.resolve(tmp_path, "不存在") is None


def test_register_rejects_bad_license(tmp_path: Path):
    try:
        registry.register(tmp_path, name="x", file="x.wav", license_kind="whatever")
        raise AssertionError("应当拒绝")
    except ValueError:
        pass


def test_register_requires_name_and_file(tmp_path: Path):
    for kwargs in ({"name": "", "file": "a.wav"}, {"name": "a", "file": ""}):
        try:
            registry.register(tmp_path, license_kind="self-authorized", **kwargs)
            raise AssertionError("应当拒绝")
        except ValueError:
            pass


def _provider(tmp_path: Path, **kwargs) -> tts_qwen.QwenTTSProvider:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model.safetensors").write_bytes(b"w")
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    py = tmp_path / "python.exe"
    py.write_bytes(b"bin")
    worker = tmp_path / "worker.py"
    worker.write_text("# stub", encoding="utf-8")
    return tts_qwen.QwenTTSProvider(
        python_exe=py, worker_script=worker, model_dir=model_dir,
        voices_root=tmp_path / "voices", **kwargs,
    )


def test_provider_available(tmp_path: Path):
    assert _provider(tmp_path).available() is True


def test_provider_clone_uses_registered_voice(tmp_path: Path, monkeypatch):
    provider = _provider(tmp_path)
    root = provider.voices_root
    root.mkdir(parents=True, exist_ok=True)
    (root / "ref.wav").write_bytes(WAV)
    registry.register(root, name="我的", file="ref.wav", license_kind="self-authorized", credit="某角色")

    seen = {}

    def fake_call(**kwargs):
        seen.update(kwargs["payload"])
        Path(kwargs["payload"]["out_wav"]).write_bytes(WAV)
        return {"status": "ok", "seconds": 2.0, "gen_ms": 900}

    monkeypatch.setattr(tts_qwen, "call_persistent", fake_call)
    result = provider.synthesize_speech("你好", out_dir=tmp_path / "out", voice_id="我的")

    assert result.status is ResultStatus.OK
    assert seen["mode"] == "clone"
    assert seen["ref_audio"].endswith("ref.wav")
    assert result.data["credit"] == "某角色"


def test_provider_custom_mode_without_voice(tmp_path: Path, monkeypatch):
    provider = _provider(tmp_path, speaker="Cherry")

    def fake_call(**kwargs):
        Path(kwargs["payload"]["out_wav"]).write_bytes(WAV)
        return {"status": "ok"}

    monkeypatch.setattr(tts_qwen, "call_persistent", fake_call)
    result = provider.synthesize_speech("你好", out_dir=tmp_path / "out")
    assert result.status is ResultStatus.OK
    assert result.data["mode"] == "custom"


def test_provider_rejects_empty_text(tmp_path: Path):
    result = _provider(tmp_path).synthesize_speech("  ", out_dir=tmp_path / "o")
    assert result.status is ResultStatus.REJECTED


def test_provider_reports_worker_error(tmp_path: Path, monkeypatch):
    provider = _provider(tmp_path)

    def boom(**kwargs):
        raise tts_qwen.WorkerError("E_WORKER", "boom")

    monkeypatch.setattr(tts_qwen, "call_persistent", boom)
    result = provider.synthesize_speech("你好", out_dir=tmp_path / "o")
    assert result.status is ResultStatus.FAILED and result.error_code == "E_WORKER"


def test_provider_unavailable_without_weights(tmp_path: Path):
    provider = _provider(tmp_path)
    (provider.model_dir / "model.safetensors").unlink()
    result = provider.synthesize_speech("你好", out_dir=tmp_path / "o")
    assert result.status is ResultStatus.FAILED
    assert result.error_code == "E_MODEL_UNAVAILABLE"
