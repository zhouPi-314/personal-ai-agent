# 语音合成（M3 · TTS）

> 阶段 E｜2026-10-24｜状态：SAPI 链路**已打通并真机验证**；Kokoro 待评估。

## 1. 关键结论：不需要 silk 编码

真机验证：把 **16k 单声道 WAV** 以 `base64://` 塞进 OneBot `record` 段发出去，
**NapCat 自动转码，QQ 能正常播放**。省掉了自建 silk 编码器这一整块风险。

## 2. 链路

```text
模型回复文字 → 截断到 150 字 → SAPI 合成 WAV（16k 单声道）
  → base64 → record 段 → NapCat → QQ 语音（可播放）
```

- **零下载**：用 Windows 自带 System.Speech，不装任何包；
- **零注入**：文本写临时文件传给 PowerShell，绝不经命令行（有测试断言）；
- **失败降级**：合成失败自动退回文字，并说一句「想给你发条语音，没发出去」。

## 3. 什么时候发语音

`PAA_MEDIA_TTS_MODE`：

| 值 | 行为 |
|---|---|
| `off` | 永不发语音 |
| `voice_input`（当前）| 你发语音，它就用语音回；你发文字，它回文字 |
| `always` | 每条回复都发语音 |

## 4. 实测

| 项 | 值 |
|---|---|
| 合成耗时 | 约 0.4 s（12 字） |
| 输出体积 | 150–185 KB（WAV 16k） |
| 真机 | 已发送 2 条，QQ 端确认可播放 |

## 5. 已知限制

- SAPI 音色偏机器（Microsoft Huihui Desktop），可换系统已装音色；
- 只合成纯文字，不处理 Markdown/表情符号（表情会被念出来）；
- 未做时长上限：150 字上限只是字符限制，超长文本会截断；
- 合成出的 WAV 暂存在 `data/media/tmp/`，尚无定时清理（见 DEBT.md D49）。

## 6. 下一个候选：Kokoro-82M

- 体积约 330MB，Apache-2.0，CPU 可跑；中文需要 misaki[zh] 之类 G2P 依赖；
- 音色明显优于 SAPI，可换 speaker；
- 接入方式与 ASR 相同：独立侧车，主进程只经 NDJSON 调用。

切换前需要你先听 SAPI 的效果，确认「值得为音色多装 330MB」。
## 7. Kokoro 已接入（2026-10-24）

| 项 | 值 |
|---|---|
| 模型 | onnx-community/Kokoro-82M-v1.1-zh-ONNX（**Apache-2.0**），`models/kokoro/` |
| 体积 | fp32 `model.onnx` 326MB + tokenizer + 中文音色 `zf_001/zf_002` |
| G2P | `misaki[zh]==0.9.4` 的 `ZHG2P(version="1.1")`，输出**注音符号**（覆盖率 100%） |
| 运行时 | 侧车 Python 3.12 + onnxruntime（CPU），主进程零依赖 |

### 关键实测

| 配置 | 语音时长 | 合成耗时 | 结论 |
|---|---|---|---|
| int8 `model_int8.onnx` | 2.92 s | **5652 ms** | 本机反而慢 8 倍 |
| **fp32 `model.onnx`** | 2.92 s | **714 ms** | ✅ 默认用它 |
| fp32（长句） | 5.7 s | 1461 ms | 约 4 倍实时 |

**质量验证**：把 Kokoro 合成的语音再喂回 SenseVoice，转写结果与原文**逐字一致**——说明发音正确、可懂。

### 踩过的坑

1. `misaki` 的 `zh` 模块要用 `version="1.1"`（注音），默认版本输出 IPA，与模型词表对不上（丢 24% 音素，念出来是乱的）。
2. `pip install "misaki[zh]"` 会解析到 0.3.0 并拖进 **torch + spacy**（950MB）；显式装 `misaki[zh]==0.9.4` 后只有 368MB。
3. `tokenizer.json` 用 `tokenizers` 库加载会报错，直接读 JSON 的 `model.vocab` 更稳。