"""VOICEVOX 音色接入（二次元音色首选，免费）。

VOICEVOX 是独立的本地引擎（HTTP :50021），本模块只调用它的公开 API：
  1. GET  /speakers                 → 音色列表（每角色有独立的商业/署名条款）
  2. POST /audio_query?text&speaker → 生成合成参数
  3. POST /synthesis?speaker        → 合成 WAV

**授权与署名**：每个角色条款不同，多数要求"使用时署名角色名"。
本模块只负责合成；署名由调用方按音色元数据附加（见 VOICE_META）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from ..contracts import Capability, MediaResult, ResultStatus

DEFAULT_URL = "http://127.0.0.1:50021"
MIN_BYTES = 2048


@dataclass(frozen=True)
class VoicevoxVoice:
    """一个可用的音色。credit 是条款要求的署名文本（可为空）。"""

    speaker_id: int
    name: str
    style: str = ""
    credit: str = ""

    @property
    def display(self) -> str:
        return self.style + "（" + self.name + "）" if self.style else self.name


class VoicevoxTTSProvider:
    name = "voicevox"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_URL,
        default_speaker: int = 3,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_URL).rstrip("/")
        self.default_speaker = default_speaker
        self.timeout = timeout
        self._transport = transport

    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=timeout or self.timeout,
            trust_env=False,
            transport=self._transport,
        )

    def available(self) -> bool:
        try:
            with self._client(timeout=2.0) as client:
                return client.get("/version").status_code == 200
        except httpx.HTTPError:
            return False

    def voices(self) -> list[VoicevoxVoice]:
        try:
            with self._client() as client:
                data = client.get("/speakers").json()
        except (httpx.HTTPError, ValueError):
            return []
        result: list[VoicevoxVoice] = []
        for speaker in data if isinstance(data, list) else []:
            name = str(speaker.get("name") or "")
            for style in speaker.get("styles") or []:
                result.append(
                    VoicevoxVoice(
                        speaker_id=int(style.get("id") or 0),
                        name=name,
                        style=str(style.get("name") or ""),
                        credit=name,
                    )
                )
        return result

    def synthesize_speech(
        self,
        text: str,
        *,
        out_dir: Path,
        voice_id: str = "",
        max_chars: int | None = None,
        deadline_ms: int = 60_000,
        speed: float | None = None,
    ) -> MediaResult:
        content = (text or "").strip()
        if not content:
            return MediaResult(
                status=ResultStatus.REJECTED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_EMPTY_TEXT",
            )
        limit = max(1, int(max_chars or 200))
        truncated = len(content) > limit
        if truncated:
            content = content[:limit]

        speaker = self.default_speaker
        if voice_id:
            try:
                speaker = int(str(voice_id).split(":")[-1])
            except ValueError:
                speaker = self.default_speaker

        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / ("voicevox_" + str(speaker) + "_" + str(abs(hash(content)) % 10**8) + ".wav")

        try:
            with self._client() as client:
                query = client.post(
                    "/audio_query", params={"text": content, "speaker": speaker}
                )
                if query.status_code >= 400:
                    return MediaResult(
                        status=ResultStatus.FAILED,
                        capability=Capability.SYNTHESIZE_SPEECH,
                        error_code="E_QUERY",
                        error_detail=f"{query.status_code}",
                    )
                body = query.json()
                if speed is not None:
                    body["speedScale"] = max(0.5, min(2.0, float(speed)))
                synth = client.post("/synthesis", params={"speaker": speaker}, json=body)
                if synth.status_code >= 400 or len(synth.content) < MIN_BYTES:
                    return MediaResult(
                        status=ResultStatus.FAILED,
                        capability=Capability.SYNTHESIZE_SPEECH,
                        error_code="E_SYNTH",
                        error_detail=f"{synth.status_code} {len(synth.content)}B",
                    )
                target.write_bytes(synth.content)
        except httpx.HTTPError as exc:
            return MediaResult(
                status=ResultStatus.FAILED,
                capability=Capability.SYNTHESIZE_SPEECH,
                error_code="E_ENGINE_DOWN",
                error_detail=str(exc)[:160],
            )

        return MediaResult(
            status=ResultStatus.OK,
            capability=Capability.SYNTHESIZE_SPEECH,
            text=content,
            data={"path": str(target), "bytes": target.stat().st_size, "speaker": speaker, "truncated": truncated},
            limitations=(("文本超过 " + str(limit) + " 字，已截断",) if truncated else ()),
        )
