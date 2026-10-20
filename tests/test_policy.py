from paa.policy import Level, classify


def test_read_is_l1_and_allowed():
    decision = classify("read")

    assert decision.level is Level.L1
    assert decision.allowed and not decision.needs_approval


def test_write_is_l2_and_allowed():
    decision = classify("write")

    assert decision.level is Level.L2
    assert decision.allowed


def test_delete_requires_approval():
    decision = classify("delete")

    assert decision.level is Level.L3
    assert not decision.allowed and decision.needs_approval


def test_unknown_action_defaults_to_l3():
    decision = classify("teleport")

    assert decision.level is Level.L3
    assert decision.needs_approval
    assert "未知动作" in decision.reason


def test_action_is_case_insensitive_and_trimmed():
    assert classify("  READ  ").level is Level.L1
