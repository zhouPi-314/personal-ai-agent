# 媒体能力接口契约（Provider Contracts）

> 阶段 B 设计产物｜2026-10-24｜**未实现代码**，本文件即"接口先行"的规格
> 风格对齐现有仓库：frozen dataclass、keyword-only 参数、依赖注入（时间/会话/随机数由调用方传入）、无全局状态。

## 0. 设计原则

1. **协议同步**：现有主链路是同步代码 + `asyncio.to_thread`，Provider 一律同步，超时靠 deadline 而不是 async。
2. **零隐式 I/O**：Provider 只接收**本地文件引用**，不自己下载、不自己拼 URL（下载由 `fetcher` 负责）。
3. **结果可审计**：每个结果都带 `status / elapsed_ms / resource` 三元组，否则无法写审计与做容量规划。
4. **失败可分类**：错误码是枚举，不是自由文本——上层据此决定"降级/重试/拒绝/报警"。
5. **永不返回原始媒体内容**：结果只有结构化字段与摘要文本。

## 1. 通用契约

```python
# src/paa/media/contracts.py  （设计稿，非实现）

class Capability(StrEnum):
    ANALYZE_IMAGE = "analyze_image"
    ANALYZE_STICKER = "analyze_sticker"
    SELECT_STICKER = "select_sticker"
    RECOGNIZE_AUDIO = "recognize_audio"
    SYNTHESIZE_SPEECH = "synthesize_speech"
    GENERATE_MUSIC = "generate_music"

class MediaKind(StrEnum):
    IMAGE = "image"
    STICKER = "sticker"
    ANIMATION = "animation"   # GIF/动态表情，只取有限关键帧
    AUDIO = "audio"
    UNKNOWN = "unknown"

class ConsentScope(StrEnum):
    OWNER_ONLY = "owner_only"      # 默认：只有主人能触发（沿用现有 owner_ids）
    OWNER_AND_AT = "owner_and_at"  # 群里被 @ 也允许（仍需 texts 之外的二次确认，见安全文档）

class ResultStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"      # 有结果但置信度低 / 截断 / 只抽了帧
    REJECTED = "rejected"      # 输入不合格（超大、MIME 不符、时长超限）
    DENIED = "denied"          # 权限或开关不允许
    FAILED = "failed"          # Provider 内部错误
    TIMEOUT = "timeout"

@dataclass(frozen=True)
class MediaRef:
    """入站媒体的最小描述。只描述，不持有字节。"""
    kind: MediaKind
    source: str                # "url" | "file" | "base64" | "gateway"
    locator: str               # 网关给的原始定位（url/file/base64 串），不落日志
    declared_name: str = ""    # 网关给的文件名，仅参考，不作可信输入
    size_hint: int | None = None
    frame_count_hint: int | None = None

@dataclass(frozen=True)
class MediaInput:
    """已通过校验、落在本地临时目录的媒体。"""
    ref: MediaRef
    local_path: Path
    mime: str                  # 由文件头判定，不信任扩展名
    size_bytes: int
    sha256: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    frames: int | None = None

@dataclass(frozen=True)
class ResourceUse:
    elapsed_ms: int
    cpu_ms: int | None = None
    vram_peak_mb: int | None = None

@dataclass(frozen=True)
class MediaResult:
    status: ResultStatus
    capability: Capability
    text: str = ""             # 面向 QQ 的短句，不含原始媒体内容
    data: dict[str, object] = field(default_factory=dict)  # 结构化字段
    confidence: float | None = None
    limitations: tuple[str, ...] = ()   # 必须随结果一起告诉用户的局限
    error_code: str = ""
    error_detail: str = ""     # 内部排查用，脱敏后写日志
    resource: ResourceUse | None = None
]
```

## 2. 六个 Provider 接口

```python
class VisionProvider(Protocol):
    name: str
    def available(self) -> bool: ...
    def analyze_image(
        self,
        item: MediaInput,
        *,
        question: str = "",
        context_text: str = "",   # 聊天语境，已截断；仅用于"可能表达什么"
        deadline_ms: int = 30_000,
    ) -> MediaResult: ...

class StickerProvider(Protocol):
    name: str
    def analyze_sticker(self, item: MediaInput, *, deadline_ms: int = 10_000) -> MediaResult: ...
    def select_sticker(
        self,
        *,
        intent: str,                 # 由对话模型给出的意图标签
        context_text: str = "",
        recent_sent: tuple[str, ...] = (),   # 最近发过的 sha256，用于去重
        now: float = 0.0,
    ) -> MediaResult: ...            # data={"path":..., "tag":..., "sha256":...}

class ASRProvider(Protocol):
    name: str
    def recognize_audio(
        self,
        item: MediaInput,
        *,
        language: str = "zh",
        deadline_ms: int = 60_000,
    ) -> MediaResult: ...

class TTSProvider(Protocol):
    name: str
    def synthesize_speech(
        self,
        text: str,
        *,
        voice_id: str = "",       # 必须来自已授权音色清单
        max_chars: int = 200,
        deadline_ms: int = 60_000,
        out_dir: Path,
    ) -> MediaResult: ...         # data={"path":..., "format":"silk|amr|wav", "duration_ms":...}

class MusicProvider(Protocol):
    name: str
    def generate_music(
        self,
        prompt: str,
        *,
        duration_s: int = 30,
        deadline_ms: int = 600_000,
        out_dir: Path,
    ) -> MediaResult: ...

class MediaFetcher(Protocol):
    def fetch(self, ref: MediaRef, *, consent: ConsentScope, deadline_ms: int = 15_000) -> MediaInput: ...
]
```

## 3. 错误码（固定枚举，禁止自由文本）

| 错误码 | 含义 | 上层动作 |
|---|---|---|
| `E_TOO_LARGE` | 超字节上限 | 拒绝 + 一句提示 |
| `E_TOO_LONG` | 超时长上限 | 拒绝 + 提示 |
| `E_TOO_MANY_FRAMES` | GIF 帧数超限 | 降级为抽帧 |
| `E_MIME_MISMATCH` | 文件头与声明不符 | 拒绝 + 审计 denied |
| `E_PRIVATE_ADDRESS` | URL 解析到私网/回环/元数据 | 拒绝 + 审计 denied（疑似 SSRF） |
| `E_SCHEME_NOT_ALLOWED` | 非 http/https | 拒绝 |
| `E_DECODE_FAILED` | 解码失败 | 拒绝 |
| `E_MODEL_UNAVAILABLE` | Provider 不可用/未装 | 降级为文字 |
| `E_DEADLINE` | 超过 deadline | 降级 + 记 timeout |
| `E_QUEUE_FULL` | 队列溢出 | 拒收本次 |
| `E_BUDGET` | 每日/每次预算用尽 | 拒收 + 提示 |
| `E_CONSENT` | 未授权用户/未授权媒体类型 | 拒绝 + 审计 denied |
| `E_VRAM` | 显存不足 | 卸载后重试一次，仍失败则降级 |

## 4. MediaRouter（唯一对外门面）

```python
@dataclass(frozen=True)
class MediaRequest:
    request_id: str
    conversation_id: str
    actor_id: str
    capability: Capability
    media: tuple[MediaRef, ...] = ()
    text: str = ""
    consent_scope: ConsentScope = ConsentScope.OWNER_ONLY
    timeout_ms: int = 30_000

class MediaRouter:
    def submit(self, req: MediaRequest) -> str: ...       # 返回 job_id，立即返回（不阻塞收包）
    def poll(self, job_id: str) -> MediaResult | None: ... # 非阻塞取结果
    def cancel(self, job_id: str) -> bool: ...
    def stats(self) -> dict[str, object]: ...             # 供 /api/media/status
]
```

**契约要求（对应规范 §3 的字段）**：`request_id / conversation_id / actor_id / capability / media_type / local_file_ref / size_bytes / duration_ms / timeout_ms / consent_scope / result_status` 全部有落点——
其中 `local_file_ref` 落在 `MediaInput.local_path`，`result_status` 落在 `MediaResult.status`。

## 5. 与现有代码的接缝（不改旧签名）

| 现有对象 | 接缝方式 |
|---|---|
| `InboundMessage` | 新增字段 `media: tuple[MediaRef, ...] = ()`（有默认值，现有测试零改动） |
| `OutgoingPart` | **不改**。新增 `OutgoingMedia(kind, path, sha256, typing_seconds)` 与 `plan_media()` |
| `OneBotSender.send` | 保留，内部改走转义；新增 `send_segments()` |
| `ChatSession.ask` | **不改**。媒体理解结果以一段"【图片内容】…"前缀文本进入 ask（并在测试里证明不可注入） |
| `Policy.classify` | **不改**。新增 `MEDIA_ACTIONS: dict[str, Level]` 映射表 |
| `AuditService.record` | 复用，`action` 传能力名，`target` 传 sha256 前 12 位 |

## 6. 版本与兼容

- 契约文件一旦落地，字段只增不删；删除字段必须走一次显式的 breaking 变更并同步测试。
- `Provider.name` 会写进审计与指标，改名视为 breaking。
- 侧车协议带 `protocol_version`，主进程对不认识的版本直接拒绝（不猜）。