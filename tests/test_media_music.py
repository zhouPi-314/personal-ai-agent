"""唱歌（M4）：Provider、闸门、参数校验。"""

from pathlib import Path
from types import SimpleNamespace

from paa.media.contracts import ResultStatus
from paa.media.providers import music_sidecar
from paa.media.providers.music_sidecar import MusicSidecarProvider
from paa.media.router import MediaRouter, MediaSettings
from paa.media.stickers import StickerLibrary

MP3 = b"ID3" + b"\x00" * 16384


def _provider(tmp_path: Path, **kwargs) -> MusicSidecarProvider:
    project = tmp_path / "acestep"
    (project / "acestep").mkdir(parents=True)
    (project / "acestep" / "handler.py").write_text("# stub", encoding="utf-8")
    ckpt = tmp_path / "checkpoints"
    (ckpt / "acestep-v15-turbo").mkdir(parents=True)
    (ckpt / "acestep-v15-turbo" / "model.safetensors").write_bytes(b"w")
    py = tmp_path / "python.exe"
    py.write_bytes(b"bin")
    worker = tmp_path / "music_worker.py"
    worker.write_text("# stub", encoding="utf-8")
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"bin")
    return MusicSidecarProvider(
        python_exe=py,
        worker_script=worker,
        project_root=project,
        checkpoints_dir=ckpt,
        ffmpeg=ffmpeg,
        **kwargs,
    )


def test_music_provider_available(tmp_path: Path):
    assert _provider(tmp_path).available() is True


def test_music_provider_unavailable_without_weights(tmp_path: Path):
    provider = _provider(tmp_path)
    (provider.checkpoints_dir / "acestep-v15-turbo" / "model.safetensors").unlink()
    assert provider.available() is False


def test_music_provider_success(tmp_path: Path, monkeypatch):
    provider = _provider(tmp_path)
    out = tmp_path / "out" / "song.mp3"
    out.parent.mkdir(parents=True)
    out.write_bytes(MP3)

    monkeypatch.setattr(
        music_sidecar,
        "call_worker",
        lambda **kwargs: {"status": "ok", "mp3": str(out), "bytes": len(MP3), "gen_s": 8.1, "seconds": 30},
    )
    result = provider.generate_music("温柔的钢琴曲", out_dir=tmp_path / "out")

    assert result.status is ResultStatus.OK
    assert Path(str(result.data["path"])).is_file()
    assert result.data["gen_s"] == 8.1


def test_music_provider_worker_error(tmp_path: Path, monkeypatch):
    provider = _provider(tmp_path)

    def boom(**kwargs):
        raise music_sidecar.WorkerError("E_INIT", "模型加载失败")

    monkeypatch.setattr(music_sidecar, "call_worker", boom)
    result = provider.generate_music("test", out_dir=tmp_path / "o")
    assert result.status is ResultStatus.FAILED
    assert result.error_code == "E_INIT"


def test_music_provider_rejects_empty_prompt(tmp_path: Path):
    result = _provider(tmp_path).generate_music("   ", out_dir=tmp_path / "o")
    assert result.status is ResultStatus.REJECTED
    assert result.error_code == "E_EMPTY_PROMPT"


def test_music_provider_rejects_tiny_output(tmp_path: Path, monkeypatch):
    provider = _provider(tmp_path)
    tiny = tmp_path / "tiny.mp3"
    tiny.write_bytes(b"ID3")
    monkeypatch.setattr(
        music_sidecar, "call_worker", lambda **kwargs: {"status": "ok", "mp3": str(tiny)}
    )
    result = provider.generate_music("test", out_dir=tmp_path / "o")
    assert result.status is ResultStatus.FAILED
    assert result.error_code == "E_TOO_SMALL"


def test_router_music_disabled_is_denied(tmp_path: Path):
    router = MediaRouter(
        settings=MediaSettings(enabled=True, music_enabled=False),
        library=StickerLibrary(),
        music=None,
        tmp_dir=tmp_path,
    )
    result = router.generate_music("唱一首", chat_key="c")
    assert result.status is ResultStatus.DENIED
    assert result.error_detail == "music_disabled"


def test_router_music_without_provider_fails(tmp_path: Path):
    router = MediaRouter(
        settings=MediaSettings(enabled=True, music_enabled=True),
        library=StickerLibrary(),
        music=None,
        tmp_dir=tmp_path,
    )
    result = router.generate_music("唱一首", chat_key="c")
    assert result.status is ResultStatus.FAILED
    assert result.error_code == "E_MODEL_UNAVAILABLE"


def test_router_music_success_is_audited(tmp_path: Path):
    events: list[dict] = []

    class _Music:
        def available(self):
            return True

        def generate_music(self, prompt, *, out_dir, lyrics="", seconds=None):
            return SimpleNamespace(
                status=ResultStatus.OK,
                error_code="",
                data={"path": "x.mp3", "bytes": 1000},
            )

    router = MediaRouter(
        settings=MediaSettings(enabled=True, music_enabled=True),
        library=StickerLibrary(),
        music=_Music(),
        audit=lambda **kw: events.append(kw),
        tmp_dir=tmp_path,
    )
    result = router.generate_music("唱一首", chat_key="c", actor="qq:1")
    assert result.status is ResultStatus.OK
    assert events and events[0]["verdict"] == "allowed"
