"""媒体权限分级与路由器决策（开关、限频、去重、审计）。"""

from pathlib import Path

from paa.media.providers.sticker_local import intent_for
from paa.media.router import MediaRouter, MediaSettings
from paa.media.stickers import StickerEntry, StickerLibrary, StickerRateLimiter
from paa.policy import Level, classify_media


class _Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _library(tag: str = "开心", count: int = 1) -> StickerLibrary:
    entries = tuple(
        StickerEntry(
            tag=tag,
            path=Path(f"{tag}-{index}.jpg"),
            sha256=f"{tag}-hash-{index}",
            size_bytes=10,
            source_url="https://example.invalid",
            license="CC0-1.0",
            captured_at="2026-10-24",
        )
        for index in range(count)
    )
    return StickerLibrary(entries)


def _router(*, library=None, clock=None, audit=None, **overrides) -> MediaRouter:
    settings = MediaSettings(
        enabled=overrides.pop("enabled", True),
        sticker_enabled=overrides.pop("sticker_enabled", True),
        **overrides,
    )
    return MediaRouter(
        settings=settings,
        library=library if library is not None else _library(),
        limiter=StickerRateLimiter(
            cooldown_seconds=settings.sticker_cooldown_sec,
            daily_cap=settings.sticker_daily_cap,
        ),
        audit=audit,
        clock=clock or _Clock(),
    )


# ── 权限分级 ──────────────────────────────────────────────────
def test_local_sticker_selection_is_l1():
    decision = classify_media("select_sticker")
    assert decision.level is Level.L1
    assert decision.allowed and not decision.needs_approval


def test_cloud_vision_escalates_to_l2():
    assert classify_media("analyze_image").level is Level.L1
    assert classify_media("analyze_image", egress=True).level is Level.L2


def test_audio_egress_escalates_to_l3():
    decision = classify_media("recognize_audio", egress=True)
    assert decision.level is Level.L3
    assert decision.needs_approval and not decision.allowed


def test_generate_music_always_needs_approval():
    assert classify_media("generate_music").needs_approval is True


def test_unregistered_media_capability_is_denied_by_default():
    decision = classify_media("deepfake_voice")
    assert decision.level is Level.L3
    assert decision.allowed is False and decision.needs_approval is True


# ── 意图判定 ──────────────────────────────────────────────────
def test_intent_matches_emotion_keyword():
    assert intent_for("哈哈哈太好了") == "开心"
    assert intent_for("气死我了") == "生气"


def test_intent_returns_none_without_emotion():
    assert intent_for("明天九点开会") is None
    assert intent_for("") is None


def test_intent_prefers_earliest_keyword():
    assert intent_for("真的假的，哈哈哈") == "震惊"


# ── 路由器 ────────────────────────────────────────────────────
def test_master_switch_off_returns_denied():
    router = _router(enabled=False)
    assert router.sticker_for(chat_key="c", reply_text="哈哈", day="d").reason == "media_disabled"


def test_capability_switch_off_returns_denied():
    router = _router(sticker_enabled=False)
    assert router.sticker_for(chat_key="c", reply_text="哈哈", day="d").reason == "sticker_disabled"


def test_empty_library_returns_empty_library():
    router = _router(library=StickerLibrary())
    assert router.sticker_for(chat_key="c", reply_text="哈哈", day="d").reason == "empty_library"


def test_user_text_alone_can_drive_intent():
    # 组合文本（用户话在前）里带情绪词就应命中，哪怕模型回复很平淡
    router = _router()
    decision = router.sticker_for(
        chat_key="private:1", reply_text="哈哈哈\n嗯，我在", day="d"
    )
    assert decision.ok and decision.tag == "开心"


def test_group_is_blocked_by_default():
    decision = _router().sticker_for(
        chat_key="group:1", reply_text="哈哈", day="d", is_group=True
    )
    assert decision.pick is None and decision.reason == "group_disabled"


def test_group_allowed_when_private_only_off():
    router = _router(sticker_private_only=False)
    decision = router.sticker_for(
        chat_key="group:1", reply_text="哈哈", day="d", is_group=True
    )
    assert decision.ok and decision.tag == "开心"


def test_private_chat_unaffected_by_private_only_flag():
    assert _router().sticker_for(chat_key="private:1", reply_text="哈哈", day="d").ok


def test_no_intent_means_no_sticker():
    decision = _router().sticker_for(chat_key="c", reply_text="明天九点开会", day="d")
    assert decision.pick is None and decision.reason == "no_intent"


def test_successful_pick_is_audited():
    events: list[dict] = []
    router = _router(audit=lambda **payload: events.append(payload))
    decision = router.sticker_for(chat_key="c", reply_text="哈哈哈", day="d")

    assert decision.ok and decision.pick is not None
    assert decision.tag == "开心"
    assert len(events) == 1
    assert events[0]["verdict"] == "allowed"
    assert events[0]["action"] == "select_sticker"
    assert 0 < len(events[0]["target"]) <= 12


def test_cooldown_blocks_second_sticker_and_audits_denial():
    events: list[dict] = []
    router = _router(audit=lambda **payload: events.append(payload))
    assert router.sticker_for(chat_key="c", reply_text="哈哈", day="d").ok

    decision = router.sticker_for(chat_key="c", reply_text="哈哈", day="d")
    assert decision.reason == "rate_limit:cooldown"
    assert decisions_verdicts(events) == ["allowed", "denied"]


def test_daily_cap_blocks_after_limit():
    router = _router(
        library=_library(count=5), sticker_cooldown_sec=0, sticker_daily_cap=2
    )
    assert router.sticker_for(chat_key="c", reply_text="哈哈", day="d").ok
    assert router.sticker_for(chat_key="c", reply_text="哈哈", day="d").ok
    assert router.sticker_for(chat_key="c", reply_text="哈哈", day="d").reason.endswith("daily_cap")


def test_recent_dedupe_returns_no_candidate():
    router = _router()
    assert router.sticker_for(chat_key="c", reply_text="哈哈", day="d").ok
    router.clock.advance(120.0)
    assert router.sticker_for(chat_key="c", reply_text="哈哈", day="d").reason == "no_candidate"


def test_enabled_reflects_switches():
    router = _router()
    from paa.media.contracts import Capability

    assert router.enabled(Capability.SELECT_STICKER) is True
    assert router.enabled(Capability.ANALYZE_IMAGE) is False
    assert _router(enabled=False).enabled(Capability.SELECT_STICKER) is False


def test_audit_failure_does_not_break_sending():
    def boom(**_payload):
        raise RuntimeError("db down")

    router = _router(audit=boom)
    assert router.sticker_for(chat_key="c", reply_text="哈哈", day="d").ok


def decisions_verdicts(events: list[dict]) -> list[str]:
    return [event.get("verdict", "") for event in events]
