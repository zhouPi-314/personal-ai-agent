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

# AC-Step 用 loguru 往 stdout 打日志，会污染 JSON 行协议；统一改到 stderr。
import contextlib as _contextlib

with _contextlib.suppress(Exception):
    from loguru import logger as _logger

    _logger.remove()
    _logger.add(sys.stderr, level="INFO")


def _release(*objects) -> None:
    """把模型与显存还给系统：唱歌是低频操作，用完就退比常驻更划算。"""
    import contextlib
    import gc

    for obj in objects:
        with contextlib.suppress(Exception):
            del obj
    gc.collect()
    with contextlib.suppress(Exception):
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()


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

    # 人声要靠 LM 规划歌词与演唱；不加载 LM 时 turbo 倾向只出伴奏。
    llm = None
    llm_s = 0.0
    if request.get("thinking"):
        from acestep.llm_inference import LLMHandler

        llm_started = time.perf_counter()
        llm = LLMHandler()
        import torch as _torch

        lm_dtype = None
        if str(request.get("lm_dtype") or "").lower() == "bf16":
            lm_dtype = _torch.bfloat16  # CPU 上省一半内存，避免和 DiT 的 CPU 副本一起把 RAM 撑爆
        lm_msg, lm_ok = llm.initialize(
            checkpoint_dir=os.path.join(project_root, "runtime", "acestep", "checkpoints"),
            lm_model_path=request.get("lm_model") or "acestep-5Hz-lm-1.7B",
            backend="pt",
            # LM 默认放 CPU：1.7B fp32 约占 6.8GB RAM，但 GPU 只有 6GB，和 DiT 抢会 OOM
            device=request.get("lm_device") or "cpu",
            offload_to_cpu=True,
            dtype=lm_dtype,
        )
        llm_s = round(time.perf_counter() - llm_started, 1)
        if not lm_ok:
            return {"status": "error", "code": "E_LM_INIT", "detail": str(lm_msg)[:400]}

    params = GenerationParams(
        task_type="text2music",
        thinking=bool(request.get("thinking")),
        caption=prompt,
        # 明确要求有演唱：原先歌词为空时回退成 [instrumental]，导致只有伴奏
        lyrics=lyrics if lyrics.strip() else "[verse]\n轻轻地唱给你听\n[chorus]\n这一首歌只为你",
        instrumental=False,
        vocal_language="zh",
        duration=max(10, min(60, seconds)),
        inference_steps=8,
        guidance_scale=1.0,
        seed=-1,
    )
    config = GenerationConfig(batch_size=1, audio_format="wav")

    started = time.perf_counter()
    result = generate_music(handler, llm, params=params, config=config, save_dir=out_dir)
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
    _release(handler, llm)

    return {
        "status": "ok",
        "wav": wav,
        "mp3": mp3 if converted.returncode == 0 and os.path.exists(mp3) else "",
        "bytes": os.path.getsize(mp3) if os.path.exists(mp3) else os.path.getsize(wav),
        "init_s": init_s,
        "lm_init_s": llm_s,
        "thinking": bool(request.get("thinking")),
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
