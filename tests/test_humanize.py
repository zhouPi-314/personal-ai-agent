import random

from paa.chat.humanize import (
    HumanizeConfig,
    gap_seconds,
    plan,
    split_text,
    typing_seconds,
)


def test_split_by_newlines():
    assert split_text("第一句\n第二句") == ["第一句", "第二句"]


def test_long_line_splits_on_sentence_end():
    text = "今天下午我去了一趟超市买了很多东西。回来的时候发现钥匙丢在车里了，只好又跑一趟。"

    parts = split_text(text, max_chars=20)

    assert len(parts) >= 2
    assert all(len(p) <= 60 for p in parts)


def test_short_fragments_are_merged():
    parts = split_text("嗯。好。我在的", max_chars=10)

    assert parts == ["嗯。好。我在的"]


def test_explicit_newlines_are_preserved():
    assert split_text("嗯\n好") == ["嗯", "好"]


def test_parts_capped_and_tail_merged():
    text = "\n".join(f"第{i}句" for i in range(8))

    parts = split_text(text, max_parts=3)

    assert len(parts) == 3
    assert "第7句" in parts[-1]


def test_empty_text_yields_no_parts():
    assert split_text("   \n  ") == []


def test_typing_time_grows_with_length():
    rng = random.Random(1)
    config = HumanizeConfig()

    short = typing_seconds("嗯", hour=12, rng=rng, config=config)
    long = typing_seconds("这是一句明显更长的话，需要打更久", hour=12, rng=rng, config=config)

    assert long > short


def test_typing_time_is_clamped():
    rng = random.Random(2)
    config = HumanizeConfig()

    very_long = "字" * 500

    assert typing_seconds(very_long, hour=12, rng=rng, config=config) <= config.max_typing * 1.2


def test_night_time_is_slower():
    config = HumanizeConfig()
    day = typing_seconds("晚安啦", hour=15, rng=random.Random(7), config=config)
    night = typing_seconds("晚安啦", hour=3, rng=random.Random(7), config=config)

    assert night > day


def test_gap_is_within_configured_bounds():
    config = HumanizeConfig()

    for seed in range(20):
        value = gap_seconds(rng=random.Random(seed), config=config)
        assert config.gap_range[0] <= value <= config.gap_range[1] + config.long_gap_range[1]


def test_plan_has_pauses_between_parts_only():
    result = plan("第一句\n第二句\n第三句", hour=12, rng=random.Random(3))

    assert len(result) == 3
    assert result[-1].pause_after == 0.0
    assert all(part.pause_after > 0 for part in result[:-1])


def test_plan_is_reproducible_with_same_seed():
    first = plan("你好\n今天怎么样", hour=12, rng=random.Random(42))
    second = plan("你好\n今天怎么样", hour=12, rng=random.Random(42))

    assert first == second
