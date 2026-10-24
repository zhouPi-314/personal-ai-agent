"""Kokoro TTS 侧车：中文文本 → 24k WAV（常驻，模型只加载一次）。"""

from __future__ import annotations

import json
import os
import sys
import time
import wave

import numpy as np
import onnxruntime as ort

_SESSIONS: dict[str, object] = {}
_VOCABS: dict[str, dict[str, int]] = {}
_G2P = None


def vocab_for(base: str) -> dict[str, int]:
    if base not in _VOCABS:
        with open(base + "/tokenizer.json", encoding="utf-8") as handle:
            _VOCABS[base] = json.load(handle)["model"]["vocab"]
    return _VOCABS[base]


def session_for(base: str, model_file: str, threads: int):
    key = base + "|" + model_file + "|" + str(threads)
    if key not in _SESSIONS:
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        _SESSIONS[key] = ort.InferenceSession(
            base + "/" + model_file, sess_options=options, providers=["CPUExecutionProvider"]
        )
    return _SESSIONS[key]


def g2p():
    global _G2P
    if _G2P is None:
        import contextlib

        from misaki import zh as mzh

        # misaki 初始化时会往 stdout 打一行警告，会污染 JSON 协议，重定向到 stderr。
        with contextlib.redirect_stdout(sys.stderr):
            _G2P = mzh.ZHG2P(version="1.1")
    return _G2P


def build_ids(phonemes: str, vocab: dict[str, int]) -> list[int]:
    pad = vocab["$"]
    return [pad] + [vocab[ch] for ch in phonemes if ch in vocab] + [pad]


def handle(request: dict) -> dict:
    text = str(request.get("text") or "").strip()
    model_dir = str(request.get("model_dir") or "")
    out_wav = str(request.get("out_wav") or "")
    voice_name = str(request.get("voice") or "zf_001")
    speed = float(request.get("speed") or 1.0)
    model_file = str(request.get("model_file") or "model.onnx")
    threads = max(1, int(request.get("threads") or 8))

    if not text or not out_wav:
        return {"status": "error", "code": "E_BAD_REQUEST", "detail": "缺少 text 或 out_wav"}

    base = model_dir.rstrip("/\\")
    vocab = vocab_for(base)

    started = time.perf_counter()
    phonemes, _ = g2p()(text)
    g2p_ms = int((time.perf_counter() - started) * 1000)

    session = session_for(base, model_file, threads)

    voice_file = base + "/voices/" + voice_name + ".bin"
    if not os.path.exists(voice_file):
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
    with wave.open(out_wav, "wb") as handle_out:
        handle_out.setnchannels(1)
        handle_out.setsampwidth(2)
        handle_out.setframerate(24000)
        handle_out.writeframes(pcm16.tobytes())

    return {
        "status": "ok",
        "seconds": round(pcm16.size / 24000, 2),
        "g2p_ms": g2p_ms,
        "tts_ms": tts_ms,
        "phonemes": len(phonemes),
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
        except Exception as exc:  # noqa: BLE001
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
