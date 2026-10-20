"""测试基础设施：每个用例跑在一个最终回滚的事务里，不污染开发库。"""

import uuid

import pytest
from sqlalchemy.orm import Session

from paa.db import get_engine
from paa.models import User


@pytest.fixture
def session():
    try:
        engine = get_engine()
        engine.connect().close()
    except Exception as exc:  # noqa: BLE001 - 任何连接失败都应跳过而非中断整套测试
        pytest.skip(f"数据库不可用：{exc}")

    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection)
    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def user(session):
    record = User(id=uuid.uuid4(), display_name="测试用户")
    session.add(record)
    session.flush()
    return record
