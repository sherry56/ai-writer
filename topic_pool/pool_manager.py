"""
选题池(每个 scope 一个 SQLite,scope = 用户名 或 '_public')。

API 不再有 owner 概念,scope 即 owner。Topic.owner 列保留兼容,值固定为 scope。
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from sqlalchemy import select

from db import ContentType, PUBLIC_SCOPE, Topic, TopicStatus, get_session

logger = logging.getLogger(__name__)

# 公开示例还是叫 '*'(对外含义不变),scope 名是 '_public'
PUBLIC_OWNER = "*"


def _db_value(value):
    return value.value if isinstance(value, Enum) else value


def list_topics(
    scope: str,
    status: Optional[TopicStatus] = None,
    limit: int = 200,
) -> list[Topic]:
    with get_session(scope) as s:
        stmt = select(Topic)
        if status is not None:
            stmt = stmt.where(Topic.status == _db_value(status))
        stmt = stmt.order_by(Topic.updated_at.desc()).limit(limit)
        return list(s.execute(stmt).scalars().all())


def get_topic(topic_id: int, scope: str) -> Optional[Topic]:
    with get_session(scope) as s:
        return s.get(Topic, topic_id)


def create_topic(
    *,
    scope: str,
    title: str,
    content_type: ContentType = ContentType.PRODUCT_REVIEW,
    notes: Optional[str] = None,
    status: TopicStatus = TopicStatus.DRAFT,
    model: Optional[str] = None,
    target_length: Optional[int] = None,
) -> Topic:
    with get_session(scope) as s:
        owner_label = PUBLIC_OWNER if scope == PUBLIC_SCOPE else scope
        topic = Topic(
            title=title.strip(),
            content_type=_db_value(content_type),
            notes=notes,
            status=_db_value(status),
            owner=owner_label,
            model=model,
            target_length=target_length,
        )
        s.add(topic)
        s.flush()
        logger.info("create_topic scope=%s id=%s title=%s", scope, topic.id, topic.title[:40])
        return topic


def update_topic(topic_id: int, scope: str, **fields) -> Optional[Topic]:
    ALLOWED = {"title", "content_type", "notes", "model", "target_length"}
    bad = set(fields) - ALLOWED
    if bad:
        raise ValueError(f"不允许通过 update_topic 修改的字段:{bad}(请用 set_status)")
    with get_session(scope) as s:
        topic = s.get(Topic, topic_id)
        if topic is None:
            return None
        for k, v in fields.items():
            if k == "content_type":
                v = _db_value(v)
            setattr(topic, k, v)
        return topic


def set_status(topic_id: int, status: TopicStatus, scope: str) -> Optional[Topic]:
    with get_session(scope) as s:
        topic = s.get(Topic, topic_id)
        if topic is None:
            return None
        topic.status = _db_value(status)
        return topic


def delete_topic(topic_id: int, scope: str) -> bool:
    with get_session(scope) as s:
        topic = s.get(Topic, topic_id)
        if topic is None:
            return False
        s.delete(topic)
        return True
