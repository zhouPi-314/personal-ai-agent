from paa.chat import ChatMessage, WakePolicy


def _policy(**kwargs) -> WakePolicy:
    defaults = {
        "names": ("小满",),
        "keywords": ("在吗",),
        "owner_ids": frozenset({"owner"}),
        "probability": 0.0,
        "cooldown_seconds": 0.0,
    }
    defaults.update(kwargs)
    return WakePolicy(**defaults)


def test_at_mention_wakes_in_diving_mode():
    result = _policy().should_wake(ChatMessage("随便说点啥", "u1", is_at_me=True), now=0)

    assert result.wake and result.reason == "at_mention"


def test_plain_message_is_ignored_while_diving():
    result = _policy().should_wake(ChatMessage("今天好热", "u1"), now=0)

    assert not result.wake


def test_name_mention_wakes():
    result = _policy().should_wake(ChatMessage("小满你在干嘛", "u1"), now=0)

    assert result.wake and result.reason.startswith("name:")


def test_keyword_wakes():
    result = _policy().should_wake(ChatMessage("在吗", "u1"), now=0)

    assert result.wake and result.reason.startswith("keyword:")


def test_question_wakes():
    result = _policy().should_wake(ChatMessage("这个怎么弄啊", "u1"), now=0)

    assert result.wake and result.reason == "question"


def test_single_question_mark_is_not_a_question():
    result = _policy().should_wake(ChatMessage("?", "u1"), now=0)

    assert not result.wake


def test_owner_always_wakes():
    result = _policy().should_wake(ChatMessage("嗯", "owner"), now=0)

    assert result.wake and result.reason == "owner"


def test_active_mode_wakes_on_anything():
    policy = _policy(mode="active", owner_ids=frozenset())

    assert policy.should_wake(ChatMessage("随便", "u9"), now=0).wake


def test_probability_zero_never_wakes():
    policy = _policy(owner_ids=frozenset(), question=False, name_mention=False, keywords=())

    assert not policy.should_wake(ChatMessage("平淡的一句话", "u1"), now=0).wake


def test_probability_one_always_wakes():
    policy = _policy(
        owner_ids=frozenset(),
        question=False,
        name_mention=False,
        keywords=(),
        probability=1.0,
    )

    assert policy.should_wake(ChatMessage("平淡的一句话", "u1"), now=0).reason == "probability"


def test_cooldown_blocks_proactive_but_not_mentions():
    policy = _policy(probability=1.0, cooldown_seconds=60.0)
    policy.last_wake_at = 100.0

    blocked = policy.should_wake(ChatMessage("随便说说", "u2"), now=120.0)
    mentioned = policy.should_wake(ChatMessage("小满", "u2", is_at_me=True), now=120.0)

    assert not blocked.wake
    assert mentioned.wake
