# AI 唱歌（M4 · F 阶段）可行性与基准方案

> 阶段 F 开工文档｜2026-10-24｜状态：**方案待批准安装**（约 6–10GB）

## 1. 候选

| 项 | 值 |
|---|---|
| 项目 | ACE-Step 1.5（MIT，代码与权重） |
| 官方声明 | base 模型 **< 4GB VRAM**；XL(4B) 需 ≥12GB |
| 本机 | RTX 4050 Laptop **6GB**、RAM 15.3GB、D 盘余 153GB |
| 依赖 | PyTorch(CUDA)、transformers、diffusers、sentencepiece 等 |

## 2. 为什么先做基准而不是直接接进聊天

规范 M4 写得很明确：**6GB 不可行就暂停并报告，不得擅自采购云 GPU**。
所以顺序是：独立基准 → 达标才接入 → 接入也必须默认关、独立队列。

## 3. 基准协议（达标才继续）

| 指标 | 采集方式 | 通过线 |
|---|---|---|
| 峰值显存 | 生成期间轮询 nvidia-smi | **≤ 5.5GB**（留 0.5GB 给桌面） |
| 峰值内存 | 同上 | ≤ 12GB |
| 30 秒片段耗时 | 端到端计时 | ≤ 180 秒 |
| 输出体积 | 文件大小 | ≤ 8MB（QQ 可发） |
| 音质 | 人工试听 | 能听出旋律且不刺耳 |
| 失败释放 | OOM 后采样 | 显存回落到基线 |

**任一硬指标不达标 → 停止该功能并写报告，不采购、不借云。**

## 4. 安装预算（需单独批准）

| 组件 | 体积 | 说明 |
|---|---|---|
| PyTorch CUDA 12.x (cp312) | ~2.5GB | 装进侧车 venv，不动主环境 |
| ACE-Step 代码 + 依赖 | ~1GB | 只装 base 模型，不碰 XL |
| ACE-Step base 权重 | ~4–7GB | 落 models\acestep |
| 合计 | **约 8–11GB** | 全部在项目内，可整目录删除 |

## 5. 风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| 6GB 装不下 | 官方 "<4GB" 是理想值，Windows 桌面已占 0.5–1GB | 基准先测，不行就停 |
| 下载慢 | 权重在国内可能很慢 | 可换 ModelScope 镜像 |
| 版权 | 歌词/旋律不得复制受版权保护作品 | 只做原创片段，默认 30 秒 |
| 影响主链路 | 生成期间占满显存 | 独立队列 + 默认关 + OOM 熔断 |

## 6. 接入形态（达标后才做）

```text
QQ 文字指令（如「唱一段关于下雨的歌」）
  -> 意图识别（关键词，不调模型）
  -> 任务入队（独立队列，串行，默认关）
  -> 侧车生成 30s 片段（GPU）
  -> 转 mp3/wav（ffmpeg）
  -> QQ 以「文件」或语音发送（长音频优先文件）
```

## 7. 与既有约定的关系

- **不使用云 GPU**（规范硬约束）；
- 生成能力**默认关闭**，需显式 `PAA_MEDIA_MUSIC_ENABLED=true`；
- 与 ASR/TTS 一样走**侧车**，主进程零 torch 依赖；
- 失败不得影响聊天主链路。
## 8. 实测结论（2026-10-25）：**当前环境下无法运行**

### 环境已就绪

| 项 | 实测 |
|---|---|
| CUDA | torch 2.7.1+cu128，`cuda.is_available()=True`，RTX 4050 6.0GB，基础张量运算正常 |
| 依赖 | 按仓库 `uv.lock` 安装：diffusers 0.37.1 / transformers 4.57.6 / tokenizers 0.22.2 |
| 权重 | 9.4GB 全部下载完成并落在 **D 盘**（acestep-v15-turbo 4.5GB、LM 1.7B 3.5GB、Qwen3-Embedding 0.6B 1.1GB、VAE 0.3GB） |
| 自检 | 仓库自带 `check_gpu.py` 通过："Your GPU setup appears to be working correctly" |

### 失败点

`initialize_service` 在加载主模型时**原生崩溃**：

```
Process exited with code -1073741819  (0xC0000005  ACCESS_VIOLATION)
日志最后一行：Attempting to load model with attention implementation: sdpa
```

**不是显存不足**（OOM 会是 Python 异常，不是进程级访问违例），也**不是 CPU/GPU 设备选择**——`device="cpu"` 同样崩。

### 已排除的组合（逐个试过）

| transformers | diffusers | 结果 |
|---|---|---|
| 4.57.6 | 0.39.0 | ❌ 访问违例 |
| 4.57.6 | 0.35.2 | ❌ 访问违例 |
| 4.57.6 | **0.37.1（官方 lock）** | ❌ 访问违例 |
| 4.56.2 | 0.37.1 | ❌ 访问违例 |
| 4.55.4 | 0.39.0 | ⚠️ 不崩，但 AC-Step 自身报 `Object of type dtype is not JSON serializable` |
| 4.51.3 | 0.39 / 0.35 | ⚠️ 不崩，但 diffusers 报 `layer_type_validation` 缺失（API 太老） |

另外排除了：DLL 冲突（卸掉 music 环境里的 onnxruntime/misaki/jieba 无效）、torchao（卸掉无效）。

### 结论与建议

- **F 阶段判定：阻塞**。原因是对不上版本的 transformers 在这台 Windows 机器上加载模型即崩，属于环境兼容问题，不是"6GB 显存不够"。
- 因此**没有拿到显存/耗时数据**，也就不能宣布"可行"或"不可行"。
- 建议下一轮再试的三条路（按性价比）：
  1. 用仓库自带的 `install_uv.bat` / `uv sync` 建环境（官方支持路径，能保证与 lock 完全一致）；
  2. 换 **纯 CPU 版 torch**（不带 CUDA）验证是否为 CUDA 运行时 DLL 引发；
  3. 若两条都不成，F 标记为"本机暂不支持"，不再投入时间（不采购云 GPU）。
- 现有 ~16GB 文件（6.5GB 环境 + 9.4GB 权重）保留待复测；不想要可整目录删除。
## 9. 突破：根因是"版本漂移"，不是显存、也不是 transformers

崩溃的真实原因：**依赖版本与仓库 `uv.lock` 不一致**。把下面几个原生相关包对齐到 lock 后，模型立刻能加载：

| 包 | 漂移版本 | lock 版本 |
|---|---|---|
| safetensors | 0.8.0 | **0.7.0** |
| numpy | 2.5.4 | **2.3.5** |
| numba / llvmlite | 0.68 / 0.50 | **0.63.1 / 0.46.0** |
| accelerate | 1.15.0 | **1.12.0** |
| vector-quantize-pytorch | 1.32.0 | **1.27.20** |
| transformers | 4.56.2 | **4.57.6**（保持） |

> 教训：以后跑第三方重依赖项目，**先按 lock 对齐**，不要在版本漂移的环境里反复试错。

## 10. 基准结果（30 秒中文片段，RTX 4050 Laptop 6GB）

| 配置 | 初始化 | 生成耗时 | 峰值显存 | 峰值内存 | 结果 |
|---|---|---|---|---|---|
| 全精度 + CPU offload | 16.7s | 22.6s | **5855 MB** | 12.96 GB | ✅ 但只剩 286MB 余量，超 5.5GB 线 |
| 全精度 + DiT 全卸载 | — | — | — | — | ❌ 生成阶段崩溃 |
| **int8 权重量化 + CPU offload** | **11.1s** | **8.1s** | **4853 MB** | 13.19 GB | ✅ **采用**（79% 显存） |
| fp8 / w8a8_dynamic | — | — | — | — | 未测（本机无 fp8 硬件优势） |

**判定全部达标**：

| 通过线 | 实测 |
|---|---|
| 峰值显存 ≤ 5.5 GB | **4853 MB** ✅ |
| 30 秒片段 ≤ 180 s | **8.1 s** ✅（约 3.7 倍实时） |
| 输出 ≤ 8 MB | WAV 10.99MB → **MP3 0.46MB** ✅（发送前转码） |

**质量抽查**：把生成的 30 秒歌（48kHz）转 16k 后喂给本项目 ASR，能转出"下的傍晚我…走"这类片段——
说明人声确实存在、旋律可辨；唱歌转写本身很难，不能作为音质评分，只作为"不是噪声"的证据。

**推荐配置**：`acestep-v15-turbo` + `offload_to_cpu=True` + `quantization="int8_weight_only"` + `thinking=False`（不加载 LM，省显存）。
## 11. 已接入 PAA（2026-10-25）

| 项 | 实现 |
|---|---|
| 入口 | 主人私聊里出现「唱首歌 / 唱一段 / 来一首 / 给我唱 / 唱一个」 |
| 交互 | 先回一句「好，我哼一段，等十几秒」，后台生成，完成后**以语音条发出** |
| 侧车 | `scripts/music_worker.py`（一次性进程，主进程不依赖 torch） |
| Provider | `media/providers/music_sidecar.py` |
| 门面 | `MediaRouter.generate_music`（开关 + 审计 + 异常隔离） |
| 独占 | `_song_busy` 标志，同一时间只跑一首，避免和视觉/语音抢显存 |
| 输出 | 48k WAV → **128kbps MP3（约 0.46MB）** → `record` 段发送 |

**配置**：

```dotenv
PAA_MEDIA_ENABLED=true
PAA_MEDIA_MUSIC_ENABLED=true
PAA_MEDIA_MUSIC_SECONDS=30
PAA_MEDIA_MUSIC_QUANTIZATION=int8_weight_only
```

**真机验证**：端到端生成 1 首（8.0 秒生成、480KB MP3）并成功发到 QQ 私聊。

## 12. 版权与资源约束

- 只做**原创提示词 + 原创歌词**（默认 30 秒），不复刻特定歌手、不复制受版权保护的歌词/旋律；
- 生成占满显存期间**串行**，失败自动退回文字，不影响聊天；
- 权重与运行环境全部在 `runtime/`、`models/`（已 gitignore），不进仓库。