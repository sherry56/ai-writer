"""
SQLAlchemy 2.0 数据模型。

两张表：
- Topic    选题（自定义）
- Article  文章（大纲 + 初稿）

关系：Topic 1 ── 0..1 Article
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """全局 Declarative Base。"""


class ContentType(str, enum.Enum):
    TUTORIAL = "tutorial"
    PRODUCT_REVIEW = "product_review"


class TopicStatus(str, enum.Enum):
    DRAFT = "draft"
    WRITING = "writing"
    DONE = "done"
    DISCARDED = "discarded"


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[ContentType] = mapped_column(
        String(30), nullable=False, default=ContentType.PRODUCT_REVIEW.value
    )
    status: Mapped[TopicStatus] = mapped_column(
        String(20), nullable=False, default=TopicStatus.DRAFT.value, index=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    article: Mapped[Optional["Article"]] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def __repr__(self) -> str:
        return f"<Topic id={self.id} status={self.status} title={self.title[:30]!r}>"


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    outline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    topic: Mapped["Topic"] = relationship(back_populates="article")

    def __repr__(self) -> str:
        return f"<Article id={self.id} topic_id={self.topic_id}>"
