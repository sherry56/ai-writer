"""
选题池增删改查（按 owner 隔离）。
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from sqlalchemy import select

from db import ContentType, Topic, TopicStatus, get_session

logger = logging.getLogger(__name__)


def _db_value(value):
    return value.value if isinstance(value, Enum) else value


PUBLIC_OWNER = "*"  # owner='*' 表示公开示例,所有登录用户可见(只读)


def list_topics(
    owner: str,
    status: Optional[TopicStatus] = None,
    limit: int = 200,
) -> list[Topic]:
    with get_session() as s:
        stmt = select(Topic).where(Topic.owner.in_([owner, PUBLIC_OWNER]))
        if status is not None:
            stmt = stmt.where(Topic.status == _db_value(status))
        stmt = stmt.order_by(Topic.updated_at.desc()).limit(limit)
        return list(s.execute(stmt).scalars().all())


def get_topic(topic_id: int, owner: Optional[str] = None) -> Optional[Topic]:
    """按 id 查;owner 提供时允许本人或 PUBLIC 资源,否则返回 None。"""
    with get_session() as s:
        t = s.get(Topic, topic_id)
        if t is None:
            return None
        if owner is not None and t.owner != owner and t.owner != PUBLIC_OWNER:
            return None
        return t


def create_topic(
    *,
    owner: str,
    title: str,
    content_type: ContentType = ContentType.PRODUCT_REVIEW,
    notes: Optional[str] = None,
    model: Optional[str] = None,
    status: TopicStatus = TopicStatus.DRAFT,
) -> Topic:
    with get_session() as s:
        topic = Topic(
            title=title.strip(),
            content_type=_db_value(content_type),
            notes=notes,
            model=model,
            status=_db_value(status),
            owner=owner,
        )
        s.add(topic)
        s.flush()
        logger.info("create_topic id=%s owner=%s title=%s", topic.id, owner, topic.title[:40])
        return topic


def update_topic(topic_id: int, owner: str, **fields) -> Optional[Topic]:
    ALLOWED = {"title", "content_type", "notes", "model"}
    bad = set(fields) - ALLOWED
    if bad:
        raise ValueError(f"不允许通过 update_topic 修改的字段：{bad}（请用 set_status）")

    with get_session() as s:
        topic = s.get(Topic, topic_id)
        if topic is None or topic.owner != owner:
            return None
        for k, v in fields.items():
            if k == "content_type":
                v = _db_value(v)
            setattr(topic, k, v)
        return topic


def set_status(topic_id: int, status: TopicStatus, owner: str) -> Optional[Topic]:
    with get_session() as s:
        topic = s.get(Topic, topic_id)
        if topic is None or topic.owner != owner:
            return None
        topic.status = _db_value(status)
        logger.info("set_status id=%s -> %s (owner=%s)", topic_id, status, owner)
        return topic


def delete_topic(topic_id: int, owner: str) -> bool:
    with get_session() as s:
        topic = s.get(Topic, topic_id)
        if topic is None or topic.owner != owner:
            return False
        s.delete(topic)
        return True
