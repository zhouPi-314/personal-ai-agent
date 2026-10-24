"""Kokoro TTS 侧车：中文文本 → 24k WAV。

跑在独立 Python 3.12 里（onnxruntime + misaki[zh]），主进程不依赖这些包。
协议与 ASR 侧车一致：stdin 一行 JSON，stdout 一行 JSON。
"""

from __future__ import annotations

import json
import sys
import time
import wave

import numpy as np
import onnxruntime as ort


def build_ids(phonemes: str, vocab: dict[str, int]) -> list[int]:
    pad = vocab["$"]
    return [pad] + [vocab[ch] for ch in phonemes if ch in vocab] + [pad]


def main() -> int:
    line = sys.stdin.readline()
    if not line.strip():
        print(json.dumps({"status": "error", "code": "E_EMPTY_REQUEST"}, ensure_ascii=False))
        return 1

    try:
        req = json.loads(line)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "code": "E_BAD_REQUEST", "detail": str(exc)}, ensure_ascii=False))
        return 1

    text = str(req.get("text") or "").strip()
    model_dir = str(req.get("model_dir") or "")
    out_wav = str(req.get("out_wav") or "")
    voice_name = str(req.get("voice") or "zf_001")
    speed = float(req.get("speed") or 1.0)
    model_file = str(req.get("model_file") or "model_int8.onnx")

    if not text or not out_wav:
        print(json.dumps({"status": "error", "code": "E_BAD_REQUEST", "detail": "缺少 text 或 out_wav"}, ensure_ascii=False))
        return 1

    try:
        from misaki import zh as mzh

        base = model_dir.rstrip("/\\")
        with open(base + "/tokenizer.json", encoding="utf-8") as handle:
            vocab = json.load(handle)["model"]["vocab"]

        started = time.perf_counter()
        g2p = mzh.ZHG2P(version="1.1")
        phonemes, _ = g2p(text)
        g2p_ms = int((time.perf_counter() - started) * 1000)

        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = max(1, int(req.get("threads") or 8))
        sess_options.inter_op_num_threads = 1
        session = ort.InferenceSession(
            base + "/" + model_file, sess_options=sess_options, providers=["CPUExecutionProvider"]
        )

        voice_file = base + "/voices/" + voice_name + ".bin"
        if not __import__("os").path.exists(voice_file):
            voice_file = base + "/" + voice_name + ".bin"
        voice = np.fromfile(voice_file, dtype=np.float32).reshape(510, 256)

        ids = build_ids(phonemes, vocab)
        started = time.perf_counter()
        audio = session.run(
            None,
            {
                "input_ids": np.array([ids], dtype=np.int64),
                "style": voice[min(len(ids) - 1, 509)].reshape(1, 256),
                "speed": np.array([speed], dtype=np.float32),
            },
        )[0]
        tts_ms = int((time.perf_counter() - started) * 1000)

        pcm = np.clip(np.asarray(audio).reshape(-1), -1.0, 1.0)
        pcm16 = (pcm * 32767).astype(np.int16)
        with wave.open(out_wav, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(pcm16.tobytes())

        print(
            json.dumps(
                {
                    "status": "ok",
                    "seconds": round(pcm16.size / 24000, 2),
                    "g2p_ms": g2p_ms,
                    "tts_ms": tts_ms,
                    "phonemes": len(phonemes),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - 侧车把失败原因回给主进程
        print(
            json.dumps(
                {"status": "error", "code": "E_WORKER", "detail": type(exc).__name__ + ": " + str(exc)[:200]},
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
