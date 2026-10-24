# 语音（M3）环境与基准

> 阶段 E｜2026-10-24｜ASR 已装并实测；TTS 待定

## 1. 硬事实（本机实测）

| 项 | 值 |
|---|---|
| QQ 入站语音格式 | **`.amr`**（AMR-NB）+ CDN URL（NapCat `record` 段） |
| 系统 Python | 只有 3.13.1 → 侧车另装便携版 3.12.10 |
| 侧车位置 | `runtime\python312\`（官方 embeddable，11MB，免安装、不动系统、不进仓库） |
| ASR 运行时 | `sherpa-onnx 2.0.0`（Apache-2.0，单 wheel 16.6MB） |
| ASR 模型 | SenseVoiceSmall **int8** 228MB + tokens 0.3MB（HuggingFace `csukuangfj/sherpa-onnx-sense-voice-...-2024-07-17`） |
| ffmpeg | **9.0.2 essentials**（`runtime\ffmpeg`，~99MB），含原生 `amrnb` 解码与 `libopencore_amrnb` 编码 |

## 2. CPU 基准（真实测量）

用 Windows SAPI 合成一段 5.69 秒中文语音，直接喂 SenseVoiceSmall int8：

| 指标 | 值 |
|---|---|
| 模型加载 | **1.66 s** |
| 解码耗时 | **194 ms** |
| 音频时长 | 5.69 s |
| **实时率 RTF** | **0.03**（约 33 倍实时） |
| 识别结果 | `你好，今天天气真不错，我们一起出去走走吧。`（与合成输入完全一致） |

结论：**纯 CPU 足够**，不需要 GPU、不需要常驻显存，符合 Q-04。

## 3. 目录与隔离

```text
runtime/python312/     便携 Python（已 .gitignore）
models/sensevoice/     权重（已 .gitignore）
work/                  临时测试音频（已 .gitignore）
```

侧车与主进程**互不 import**：主进程只通过 NDJSON 协议调用（阶段 E 后续落地）。

## 4. AMR 解码（已解决）

用 ffmpeg 把 WAV 编成真 AMR，再走完整链路（ffmpeg → 16k WAV → 侧车 → SenseVoice）：

| 指标 | 值 |
|---|---|
| 输入 | 5.7s AMR-NB（8.9KB，12.2kbps） |
| **端到端耗时** | **2.28 s**（含 ffmpeg + 子进程启动 + 模型加载 1.7s） |
| 其中解码 | 197 ms |
| 转写结果 | `你好，今天天气真不错，我们一起出去走走吧。` ✅ 与原文一致 |

> 踩坑记录：子进程 stdout 被重定向时 Python 默认用 cp936，中文输出会变 GBK，主进程按 UTF-8 解就是乱码。
> `worker_client` 现在强制 `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`，并有测试盯着。

原始设计里的备选：

QQ 语音是 AMR-NB，SenseVoice 要 16kHz 单声道 WAV。两条路：

1. **装 ffmpeg**（推荐）：`-i in.amr -ar 16000 -ac 1 -f wav`，参数数组调用、禁 shell。
2. 让 NapCat 的 `get_record` 先转 mp3（依赖网关行为，未验证）。

ffmpeg 属于新增工具，需单独批准；本地自用不涉及再分发，GPL 构建可用。

## 5. 已知限制

- 目前只验证了「16k 单声道 WAV」；AMR 路径未通（等 ffmpeg）。
- 长语音会整段转写，暂不切分；超过 120 秒按配置拒绝。
- 转写结果按 M3 规范**不进长期记忆**（待接入时实现）。