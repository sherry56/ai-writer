"""
选题池增删改查（仅自定义选题）。
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select

from db import ContentType, Topic, TopicStatus, get_session

logger = logging.getLogger(__name__)


def list_topics(
    status: Optional[TopicStatus] = None,
    limit: int = 200,
) -> list[Topic]:
    with get_session() as s:
        stmt = select(Topic)
        if status is not None:
            stmt = stmt.where(Topic.status == status)
        stmt = stmt.order_by(Topic.updated_at.desc()).limit(limit)
        return list(s.execute(stmt).scalars().all())


def get_topic(topic_id: int) -> Optional[Topic]:
    with get_session() as s:
        return s.get(Topic, topic_id)


def create_topic(
    *,
    title: str,
    content_type: ContentType = ContentType.PRODUCT_REVIEW,
    notes: Optional[str] = None,
    status: TopicStatus = TopicStatus.DRAFT,
) -> Topic:
    with get_session() as s:
        topic = Topic(
            title=title.strip(),
            content_type=content_type,
            notes=notes,
            status=status,
        )
        s.add(topic)
        s.flush()
        logger.info("create_topic id=%s title=%s", topic.id, topic.title[:40])
        return topic


def update_topic(topic_id: int, **fields) -> Optional[Topic]:
    ALLOWED = {"title", "content_type", "notes"}
    bad = set(fields) - ALLOWED
    if bad:
        raise ValueError(f"不允许通过 update_topic 修改的字段：{bad}（请用 set_status）")

    with get_session() as s:
        topic = s.get(Topic, topic_id)
        if topic is None:
            return None
        for k, v in fields.items():
            setattr(topic, k, v)
        return topic


def set_status(topic_id: int, status: TopicStatus) -> Optional[Topic]:
    with get_session() as s:
        topic = s.get(Topic, topic_id)
        if topic is None:
            return None
        topic.status = status
        logger.info("set_status id=%s -> %s", topic_id, status)
        return topic


def delete_topic(topic_id: int) -> bool:
    with get_session() as s:
        topic = s.get(Topic, topic_id)
        if topic is None:
            return False
        s.delete(topic)
        return True
