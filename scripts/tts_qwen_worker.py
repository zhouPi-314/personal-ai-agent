"""Qwen3-TTS 侧车：克隆音色 / 预设音色合成，输出 24k WAV。

常驻模式：模型只加载一次（0.6B 约 5-10 秒），空闲由主进程回收。
跑在独立 Python 3.12 + CUDA torch 环境，主进程零依赖。
"""

from __future__ import annotations

import json
import sys
import time
import traceback

_MODELS: dict[str, object] = {}


def _model(model_dir: str, device: str):
    key = model_dir + "|" + device
    if key not in _MODELS:
        from qwen_tts import Qwen3TTSModel

        _MODELS[key] = Qwen3TTSModel.from_pretrained(model_dir, device_map=device)
    return _MODELS[key]


def _write_wav(path: str, audio, sample_rate: int) -> int:
    import wave

    import numpy as np

    data = np.asarray(audio).reshape(-1)
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if peak > 1.0:
        data = data / peak
    pcm16 = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm16.tobytes())
    return int(pcm16.size)


def handle(request: dict) -> dict:
    text = str(request.get("text") or "").strip()
    out_wav = str(request.get("out_wav") or "")
    model_dir = str(request.get("model_dir") or "")
    language = str(request.get("language") or "Chinese")
    mode = str(request.get("mode") or "clone")
    ref_audio = str(request.get("ref_audio") or "")
    ref_text = str(request.get("ref_text") or "")
    speaker = str(request.get("speaker") or "")
    device = str(request.get("device") or "cuda")

    if not text or not out_wav or not model_dir:
        return {"status": "error", "code": "E_BAD_REQUEST", "detail": "缺少 text / out_wav / model_dir"}

    started = time.perf_counter()
    model = _model(model_dir, device)
    load_ms = int((time.perf_counter() - started) * 1000)

    started = time.perf_counter()
    if mode == "custom" and speaker:
        audios, sr = model.generate_custom_voice(
            text=[text], speaker=[speaker], language=[language]
        )
    else:
        # 没有参考文本时必须用 x_vector_only_mode，否则模型会要求 ref_text 而报错
        audios, sr = model.generate_voice_clone(
            text=[text],
            language=[language],
            ref_audio=ref_audio or None,
            ref_text=ref_text or None,
            x_vector_only_mode=not bool(ref_text),
        )
    gen_ms = int((time.perf_counter() - started) * 1000)

    samples = _write_wav(out_wav, audios[0], sr)
    return {
        "status": "ok",
        "seconds": round(samples / float(sr), 2) if sr else 0,
        "load_ms": load_ms,
        "gen_ms": gen_ms,
        "mode": mode,
    }


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"status": "error", "code": "E_BAD_REQUEST", "detail": str(exc)}, ensure_ascii=False), flush=True)
            continue
        try:
            print(json.dumps(handle(request), ensure_ascii=False), flush=True)
        except Exception:  # noqa: BLE001 - 侧车把异常转成 JSON
            print(
                json.dumps(
                    {"status": "error", "code": "E_WORKER", "detail": traceback.format_exc()[-800:]},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
