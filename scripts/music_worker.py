"""AC-Step 音乐生成侧车：一次生成 30 秒片段，输出 WAV + MP3。

跑在独立 Python 3.12 + CUDA torch 里，主进程不依赖 torch。
配置来自环境变量：ACESTEP_CHECKPOINTS_DIR / ACESTEP_PROJECT_ROOT。
协议：stdin 一行 JSON，stdout 一行 JSON（与 ASR/TTS 侧车一致）。
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_k, None)


def handle(request: dict) -> dict:
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music

    prompt = str(request.get("prompt") or "").strip()
    lyrics = str(request.get("lyrics") or "").strip()
    seconds = int(request.get("seconds") or 30)
    out_dir = str(request.get("out_dir") or "")
    quant = request.get("quantization") or "int8_weight_only"
    project_root = str(request.get("project_root") or "")

    if not prompt or not out_dir:
        return {"status": "error", "code": "E_BAD_REQUEST", "detail": "缺少 prompt 或 out_dir"}

    os.makedirs(out_dir, exist_ok=True)

    started = time.perf_counter()
    handler = AceStepHandler()
    msg, ok = handler.initialize_service(
        project_root=project_root,
        config_path="acestep-v15-turbo",
        device="auto",
        offload_to_cpu=True,
        quantization=quant,
    )
    init_s = round(time.perf_counter() - started, 1)
    if not ok:
        return {"status": "error", "code": "E_INIT", "detail": str(msg)[:400]}

    params = GenerationParams(
        task_type="text2music",
        thinking=False,
        caption=prompt,
        lyrics=lyrics or "[instrumental]",
        vocal_language="zh",
        duration=max(10, min(60, seconds)),
        inference_steps=8,
        guidance_scale=1.0,
        seed=-1,
    )
    config = GenerationConfig(batch_size=1, audio_format="wav")

    started = time.perf_counter()
    result = generate_music(handler, None, params=params, config=config, save_dir=out_dir)
    gen_s = round(time.perf_counter() - started, 1)

    if not getattr(result, "success", False):
        return {
            "status": "error",
            "code": "E_GENERATE",
            "detail": str(getattr(result, "status_message", ""))[:400],
            "init_s": init_s,
            "gen_s": gen_s,
        }

    files = [a.get("path") for a in (getattr(result, "audios", []) or []) if a.get("path")]
    if not files:
        return {"status": "error", "code": "E_NO_FILE", "detail": "没有产出文件"}

    wav = files[0]
    mp3 = os.path.splitext(wav)[0] + ".mp3"
    ffmpeg = request.get("ffmpeg") or "ffmpeg"
    import subprocess

    converted = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", wav,
         "-codec:a", "libmp3lame", "-b:a", "128k", mp3],
        capture_output=True,
        check=False,
    )
    return {
        "status": "ok",
        "wav": wav,
        "mp3": mp3 if converted.returncode == 0 and os.path.exists(mp3) else "",
        "bytes": os.path.getsize(mp3) if os.path.exists(mp3) else os.path.getsize(wav),
        "init_s": init_s,
        "gen_s": gen_s,
        "seconds": max(10, min(60, seconds)),
    }


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
    try:
        print(json.dumps(handle(request), ensure_ascii=False), flush=True)
        return 0
    except Exception:  # noqa: BLE001 - 侧车要把任何异常都转成 JSON 回给主进程
        print(
            json.dumps(
                {"status": "error", "code": "E_WORKER", "detail": traceback.format_exc()[-800:]},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
