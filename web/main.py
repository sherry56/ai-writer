"""FastAPI 后端。

提供选题增删改查 + 大纲/初稿生成 + 落盘接口。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from db import Article, ContentType, Topic, TopicStatus, get_session, init_db
from topic_pool import (
    create_topic,
    delete_topic,
    get_topic,
    list_topics,
    set_status,
    update_topic,
)
from writer import TEMPLATES, generate_draft, generate_outline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "data" / "articles"
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="ai-writer", version="0.2.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    logger.info("ai-writer started, db ready")


# ===== Schemas =====

class TopicIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content_type: ContentType = ContentType.PRODUCT_REVIEW
    notes: Optional[str] = None


class TopicPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    content_type: Optional[ContentType] = None
    notes: Optional[str] = None
    status: Optional[TopicStatus] = None


class ArticlePatch(BaseModel):
    outline: Optional[str] = None
    draft: Optional[str] = None


class TopicOut(BaseModel):
    id: int
    title: str
    content_type: ContentType
    status: TopicStatus
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    has_outline: bool = False
    has_draft: bool = False

    @classmethod
    def from_orm_with_article(cls, t: Topic) -> "TopicOut":
        # Pull from loaded state to avoid lazy load after session close
        art = t.__dict__.get("article")
        return cls(
            id=t.id,
            title=t.title,
            content_type=t.content_type,
            status=t.status,
            notes=t.notes,
            created_at=t.created_at,
            updated_at=t.updated_at,
            has_outline=bool(art and art.outline),
            has_draft=bool(art and art.draft),
        )


class ArticleOut(BaseModel):
    topic_id: int
    outline: Optional[str]
    draft: Optional[str]
    file_path: Optional[str]
    model: Optional[str]


# ===== Helpers =====

def _article_out(topic_id: int) -> ArticleOut:
    with get_session() as s:
        art = s.execute(
            select(Article).where(Article.topic_id == topic_id)
        ).scalar_one_or_none()
        if art is None:
            return ArticleOut(topic_id=topic_id, outline=None, draft=None, file_path=None, model=None)
        return ArticleOut(
            topic_id=art.topic_id,
            outline=art.outline,
            draft=art.draft,
            file_path=art.file_path,
            model=art.model,
        )


def _upsert_article(topic_id: int, *, outline: Optional[str] = None,
                    draft: Optional[str] = None, model: Optional[str] = None,
                    file_path: Optional[str] = None) -> Article:
    with get_session() as s:
        art = s.execute(
            select(Article).where(Article.topic_id == topic_id)
        ).scalar_one_or_none()
        if art is None:
            art = Article(topic_id=topic_id)
            s.add(art)
        if outline is not None:
            art.outline = outline
        if draft is not None:
            art.draft = draft
        if model is not None:
            art.model = model
        if file_path is not None:
            art.file_path = file_path
        s.flush()
        return art


def _slug(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[\\/:*?\"<>|\s]+", "-", text).strip("-")
    return text[:max_len] or "untitled"


def _save_draft_file(topic: Topic, draft: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{ts}-{_slug(topic.title)}.md"
    path = ARTICLES_DIR / name
    path.write_text(f"# {topic.title}\n\n{draft}\n", encoding="utf-8")
    rel = path.relative_to(ROOT).as_posix()
    logger.info("saved draft to %s", rel)
    return rel


# ===== Topic endpoints =====

@app.get("/api/templates")
def api_templates() -> list[dict]:
    return [
        {"value": tpl.NAME, "label": tpl.DISPLAY_NAME}
        for tpl in TEMPLATES.values()
    ]


def _load_topic_with_article(topic_id: int) -> Optional[Topic]:
    with get_session() as s:
        stmt = select(Topic).options(selectinload(Topic.article)).where(Topic.id == topic_id)
        return s.execute(stmt).scalar_one_or_none()


@app.get("/api/topics", response_model=list[TopicOut])
def api_list_topics(status: Optional[TopicStatus] = None) -> list[TopicOut]:
    with get_session() as s:
        stmt = select(Topic).options(selectinload(Topic.article))
        if status is not None:
            stmt = stmt.where(Topic.status == status)
        stmt = stmt.order_by(Topic.updated_at.desc())
        topics = list(s.execute(stmt).scalars().all())
        return [TopicOut.from_orm_with_article(t) for t in topics]


@app.post("/api/topics", response_model=TopicOut, status_code=201)
def api_create_topic(payload: TopicIn) -> TopicOut:
    t = create_topic(
        title=payload.title,
        content_type=payload.content_type,
        notes=payload.notes,
    )
    return TopicOut.from_orm_with_article(_load_topic_with_article(t.id))


@app.get("/api/topics/{topic_id}", response_model=TopicOut)
def api_get_topic(topic_id: int) -> TopicOut:
    t = _load_topic_with_article(topic_id)
    if t is None:
        raise HTTPException(404, "topic not found")
    return TopicOut.from_orm_with_article(t)


@app.patch("/api/topics/{topic_id}", response_model=TopicOut)
def api_patch_topic(topic_id: int, payload: TopicPatch) -> TopicOut:
    data = payload.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    if data:
        if update_topic(topic_id, **data) is None:
            raise HTTPException(404, "topic not found")
    if new_status is not None:
        if set_status(topic_id, new_status) is None:
            raise HTTPException(404, "topic not found")
    t = _load_topic_with_article(topic_id)
    if t is None:
        raise HTTPException(404, "topic not found")
    return TopicOut.from_orm_with_article(t)


@app.delete("/api/topics/{topic_id}", status_code=204, response_class=Response)
def api_delete_topic(topic_id: int) -> Response:
    if not delete_topic(topic_id):
        raise HTTPException(404, "topic not found")
    return Response(status_code=204)


# ===== Article endpoints =====

@app.get("/api/topics/{topic_id}/article", response_model=ArticleOut)
def api_get_article(topic_id: int) -> ArticleOut:
    if get_topic(topic_id) is None:
        raise HTTPException(404, "topic not found")
    return _article_out(topic_id)


@app.patch("/api/topics/{topic_id}/article", response_model=ArticleOut)
def api_patch_article(topic_id: int, payload: ArticlePatch) -> ArticleOut:
    if get_topic(topic_id) is None:
        raise HTTPException(404, "topic not found")
    data = payload.model_dump(exclude_unset=True)
    _upsert_article(topic_id, **data)
    return _article_out(topic_id)


@app.post("/api/topics/{topic_id}/outline", response_model=ArticleOut)
def api_gen_outline(topic_id: int) -> ArticleOut:
    topic = get_topic(topic_id)
    if topic is None:
        raise HTTPException(404, "topic not found")
    try:
        result = generate_outline(topic)
    except Exception as e:  # noqa: BLE001
        logger.exception("outline generation failed")
        raise HTTPException(500, f"outline 生成失败：{e}") from e
    _upsert_article(topic_id, outline=result["outline"], model=result["model"])
    if topic.status == TopicStatus.DRAFT:
        set_status(topic_id, TopicStatus.WRITING)
    return _article_out(topic_id)


@app.post("/api/topics/{topic_id}/draft", response_model=ArticleOut)
def api_gen_draft(topic_id: int) -> ArticleOut:
    topic = get_topic(topic_id)
    if topic is None:
        raise HTTPException(404, "topic not found")
    art = _article_out(topic_id)
    if not art.outline:
        raise HTTPException(400, "请先生成或填写大纲")
    try:
        result = generate_draft(topic, art.outline)
    except Exception as e:  # noqa: BLE001
        logger.exception("draft generation failed")
        raise HTTPException(500, f"draft 生成失败：{e}") from e
    file_path = _save_draft_file(topic, result["draft"])
    _upsert_article(topic_id, draft=result["draft"], model=result["model"], file_path=file_path)
    set_status(topic_id, TopicStatus.DONE)
    return _article_out(topic_id)


# ===== Static frontend =====

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
