"""入站媒体解析：只描述位置，不下载。"""

from paa.adapters.onebot import parse_event


def _event(segments):
    return {
        "post_type": "message",
        "message_type": "private",
        "self_id": 100,
        "user_id": 200,
        "message": segments,
    }


def test_image_segment_becomes_media_ref():
    msg = parse_event(
        _event([{"type": "image", "data": {"url": "https://cdn.example/a.png", "file": "a.png"}}])
    )
    assert msg is not None
    assert len(msg.media) == 1
    assert msg.media[0].kind == "image"
    assert msg.media[0].source == "url"
    assert msg.media[0].locator == "https://cdn.example/a.png"


def test_mface_becomes_sticker_media():
    msg = parse_event(
        _event([{"type": "mface", "data": {"url": "https://cdn.example/e.gif", "summary": "[表情]"}}])
    )
    assert msg is not None
    assert msg.media[0].kind == "sticker"
    assert msg.text == "[表情]"


def test_image_without_source_is_dropped():
    msg = parse_event(_event([{"type": "image", "data": {"file": "a.png"}}, {"type": "text", "data": {"text": "看图"}}]))
    assert msg is not None
    assert msg.media == ()
    assert msg.text == "[图片]看图"


def test_record_segment_is_audio_and_keeps_placeholder():
    msg = parse_event(
        _event([{"type": "record", "data": {"file": "abc.amr", "url": "https://cdn.example/v.amr"}}])
    )
    assert msg is not None
    assert msg.media[0].kind == "audio"
    assert msg.media[0].source == "url"
    assert msg.text == "[语音]"


def test_plain_text_has_no_media():
    msg = parse_event(_event([{"type": "text", "data": {"text": "你好"}}]))
    assert msg is not None
    assert msg.media == ()


def test_local_file_path_is_recognised():
    msg = parse_event(_event([{"type": "image", "data": {"file": "C:/temp/x.png"}}]))
    assert msg is not None
    assert msg.media[0].source == "file"


def test_base64_is_recognised():
    msg = parse_event(_event([{"type": "image", "data": {"file": "base64://AAAA"}}]))
    assert msg is not None
    assert msg.media[0].source == "base64"
