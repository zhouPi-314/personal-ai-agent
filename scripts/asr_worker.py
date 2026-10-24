"""ASR 侧车：把一段 16k 单声道 WAV 转成文字。

由主进程按需拉起（一次一个请求），跑在独立的 Python 3.12 里，
所以主进程不需要 torch / onnxruntime，模型崩溃也波及不到 QQ 主链路。

协议：stdin 一行 JSON 请求，stdout 一行 JSON 响应，stderr 不参与解析。
"""

from __future__ import annotations

import array
import json
import sys
import time
import wave


def read_wav(path: str) -> tuple[list[float], int]:
    with wave.open(path, "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError("需要 16bit 单声道 WAV")
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    pcm = array.array("h")
    pcm.frombytes(raw)
    return [sample / 32768.0 for sample in pcm], rate


def main() -> int:
    line = sys.stdin.readline()
    if not line.strip():
        print(json.dumps({"status": "error", "code": "E_EMPTY_REQUEST"}, ensure_ascii=False))
        return 1

    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "code": "E_BAD_REQUEST", "detail": str(exc)}, ensure_ascii=False))
        return 1

    wav_path = str(request.get("wav_path") or "")
    model_dir = str(request.get("model_dir") or "")
    language = str(request.get("language") or "zh")

    try:
        import sherpa_onnx  # 只有这个侧车环境里才有

        started = time.perf_counter()
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model_dir + "/model.int8.onnx",
            tokens=model_dir + "/tokens.txt",
            language=language,
            use_itn=True,
            num_threads=2,
        )
        load_ms = int((time.perf_counter() - started) * 1000)

        samples, rate = read_wav(wav_path)
        started = time.perf_counter()
        stream = recognizer.create_stream()
        stream.accept_waveform(rate, samples)
        recognizer.decode_stream(stream)
        decode_ms = int((time.perf_counter() - started) * 1000)

        print(
            json.dumps(
                {
                    "status": "ok",
                    "text": stream.result.text,
                    "audio_sec": round(len(samples) / rate, 2) if rate else 0,
                    "load_ms": load_ms,
                    "decode_ms": decode_ms,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - 侧车要把失败原因回给主进程
        print(
            json.dumps(
                {"status": "error", "code": "E_WORKER", "detail": type(exc).__name__ + ": " + str(exc)[:200]},
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
