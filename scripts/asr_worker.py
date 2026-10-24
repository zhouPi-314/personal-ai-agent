"""ASR 侧车：把 16k 单声道 WAV 转成文字。

常驻模式：同一进程连续处理多行请求，模型只加载一次（冷启动约 1.7 秒）。
主进程决定何时拉起、何时回收；这里只负责"读一行、算一行、写一行"。
"""

from __future__ import annotations

import array
import json
import sys
import time
import wave

_RECOGNIZERS: dict[str, object] = {}


def read_wav(path: str) -> tuple[list[float], int]:
    with wave.open(path, "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError("需要 16bit 单声道 WAV")
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    pcm = array.array("h")
    pcm.frombytes(raw)
    return [sample / 32768.0 for sample in pcm], rate


def recognizer_for(model_dir: str, language: str):
    key = model_dir + "|" + language
    if key not in _RECOGNIZERS:
        import sherpa_onnx

        _RECOGNIZERS[key] = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model_dir + "/model.int8.onnx",
            tokens=model_dir + "/tokens.txt",
            language=language,
            use_itn=True,
            num_threads=2,
        )
    return _RECOGNIZERS[key]


def handle(request: dict) -> dict:
    wav_path = str(request.get("wav_path") or "")
    model_dir = str(request.get("model_dir") or "")
    language = str(request.get("language") or "zh")

    started = time.perf_counter()
    recognizer = recognizer_for(model_dir, language)
    load_ms = int((time.perf_counter() - started) * 1000)

    samples, rate = read_wav(wav_path)
    started = time.perf_counter()
    stream = recognizer.create_stream()
    stream.accept_waveform(rate, samples)
    recognizer.decode_stream(stream)
    decode_ms = int((time.perf_counter() - started) * 1000)

    return {
        "status": "ok",
        "text": stream.result.text,
        "audio_sec": round(len(samples) / rate, 2) if rate else 0,
        "load_ms": load_ms,
        "decode_ms": decode_ms,
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
        except Exception as exc:  # noqa: BLE001 - 单条失败不能让侧车退出
            print(
                json.dumps(
                    {"status": "error", "code": "E_WORKER", "detail": type(exc).__name__ + ": " + str(exc)[:200]},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
