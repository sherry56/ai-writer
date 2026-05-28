"""FastAPI 后端 + 登录认证 + 用户数据隔离。"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.middleware.sessions import SessionMiddleware

from db import Article, ContentType, Topic, TopicStatus, get_session, init_db
from topic_pool import (
    PUBLIC_OWNER,
    create_topic,
    delete_topic,
    set_status,
    update_topic,
)
from web.auth import (
    SESSION_COOKIE,
    authenticate,
    current_user,
    get_session_secret,
    register_user,
    require_user,
)
from web.usage import FREE_LIMIT, enforce_and_increment, remaining as usage_remaining
from writer import TEMPLATES, generate_draft, generate_outline, generate_revision
from writer.llm_client import get_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "data" / "articles"
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = ROOT / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = Path(__file__).resolve().parent / "static"

PUBLIC_EXAMPLE_TITLE = "AI-Writer——一键公众号写作排版工具"
PUBLIC_EXAMPLE_OLD_TITLES = tuple(
    title.replace("AI-Writer", "AI-" + "writer")
    for title in (
        PUBLIC_EXAMPLE_TITLE,
        "AI-Writer一键公众号写作排版工具",
    )
)
PUBLIC_EXAMPLE_MODEL = "seed/readme"
ADMIN_USER = os.getenv("ADMIN_USER", "sherry").strip() or "sherry"
MODEL_OPTIONS = [
    {"value": "gpt-5.5", "label": "GPT-5.5"},
    {"value": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
    {"value": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
    {"value": "deepseek-v4-pro", "label": "Deepseek-v4-pro"},
    {"value": "qwen-max", "label": "Qwen Max"},
    {"value": "moonshot-v1-32k", "label": "Moonshot Kimi 32K"},
    {"value": "glm-4-plus", "label": "GLM-4 Plus"},
    {"value": "doubao-seed-1.6", "label": "豆包 Seed 1.6"},
]

app = FastAPI(title="ai-writer", version="0.3.0")

app.add_middleware(
    SessionMiddleware,
    secret_key=get_session_secret(),
    session_cookie=SESSION_COOKIE,
    same_site="lax",
    https_only=False,  # set True if always served via HTTPS
    max_age=60 * 60 * 24 * 30,  # 30 days
)


def _read_readme_for_example() -> str:
    try:
        return (ROOT / "README.md").read_text(encoding="utf-8").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("read README.md for public example failed: %s", e)
        return "AI-Writer 是一个面向中文公众号的 AI 写作、预览与排版工具。"


def _model_options() -> list[dict]:
    from writer.model_config import default_model, list_models
    options = list_models()
    default = default_model()
    for item in options:
        if item["value"] == default:
            item["label"] = f"{item['label']}（默认）"
            break
    return options


def _topic_model(model: Optional[str]) -> str:
    value = (model or "").strip()
    return value or get_model()


def is_admin_user(user: Optional[str]) -> bool:
    return bool(user and user == ADMIN_USER)


def _public_example_outline() -> str:
    return """## 1. 开头定位
- 用一句话说明 AI-Writer 解决什么问题：把公众号文章从选题、生成、预览到复制排版串起来。

## 2. 功能速览
- 用表格展示选题池、AI 生成、Markdown 预览、富文本复制、图片上传等能力。

## 3. 实操流程
- 用分步骤说明从新建选题到复制到公众号编辑器的完整链路。

## 4. 技术示例
- 放一个启动命令代码块和一个 API payload 代码块，展示代码排版效果。

## 5. 适用场景和限制
- 说明适合谁、不适合谁，并用分割线做段落收束。"""


def _public_example_draft(readme: str) -> str:
    return """## 一句话定位

AI-Writer 是一个面向中文公众号作者的写作排版工具：你给标题、备注和素材，它帮你生成大纲、生成初稿，并在右侧实时预览公众号样式。

> 更准确地说，它不是“自动替你思考一切”的内容机器，而是一个把写作链路整理顺手的工作台。

---

## 功能速览

| 模块 | 解决的问题 | 适合展示的排版 |
| --- | --- | --- |
| 选题池 | 管理标题、素材、状态和模型 | 列表、标签、状态 |
| AI 大纲 | 把零散素材组织成结构 | 二级标题、项目符号 |
| AI 初稿 | 基于大纲生成公众号草稿 | 段落、引用、重点句 |
| 右侧预览 | 边写边看排版效果 | 主题、字体、代码高亮 |
| 富文本复制 | 粘贴到公众号编辑器 | 表格、分割线、代码块 |

---

## 一个典型流程

1. 新建选题，写清楚标题、内容类型和模型。
2. 把写作角度、参考资料、产品信息直接放进备注。
3. 先生成大纲，人工调整结构。
4. 再生成初稿，必要时用 AI 修改局部段落。
5. 在右侧检查公众号样式，最后复制富文本。

这套流程的重点不是“少点几次按钮”，而是让每一步都有明确位置：素材放哪里、结构在哪里改、正文在哪里预览，都不用来回切工具。

## 代码块展示：本地启动

```bash
pip install -r requirements.txt
uvicorn web.main:app --reload --port 8000
```

如果用 Docker，也可以这样启动：

```bash
docker compose up -d --build
```

## 代码块展示：创建选题 payload

```json
{
  "title": "AI-Writer——一键公众号写作排版工具",
  "content_type": "tutorial",
  "model": "按前端模型下拉手动选择",
  "notes": "目标读者：公众号作者。重点展示表格、代码块、分割线和富文本复制。"
}
```

## 为什么要把排版放进写作流程

很多文章不是写完才需要排版。标题层级、段落长度、表格宽度、代码块背景，这些都会反过来影响正文怎么写。

比如技术教程里，代码块如果默认是浅色背景，在公众号里很容易和正文混成一片；黑色背景会更像一个独立的“操作区”，读者扫一眼就知道这里可以复制命令。

---

## 适合谁

- 经常写 AI、工具、教程、产品解读的公众号作者。
- 需要把 Markdown 内容粘贴到公众号编辑器的人。
- 希望本地部署、数据自己保存的小团队。

## 暂时不适合谁

- 想自动抓热点、自动洗稿的人。
- 不愿意提供素材，只想让模型凭空编内容的人。
- 需要复杂协作审批、定时发布的大型团队。

---

## 小结

AI-Writer 的价值不在于替作者“无中生有”，而在于把公众号写作里那些重复、割裂、容易丢格式的步骤放到同一个界面里。

当选题、大纲、初稿、预览和复制都在一个工作台完成，写作者能把注意力放回内容本身。"""


def _write_public_example_file(draft: str) -> str:
    public_dir = ARTICLES_DIR / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    path = public_dir / f"{PUBLIC_EXAMPLE_TITLE}.md"
    path.write_text(f"# {PUBLIC_EXAMPLE_TITLE}\n\n{draft}\n", encoding="utf-8")
    return path.relative_to(ROOT).as_posix()


def _read_public_example_file(default_draft: str) -> tuple[str, str]:
    public_dir = ARTICLES_DIR / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    path = public_dir / f"{PUBLIC_EXAMPLE_TITLE}.md"
    if not path.exists():
        for old_title in PUBLIC_EXAMPLE_OLD_TITLES:
            old_path = public_dir / f"{old_title}.md"
            if old_path.exists():
                old_path.replace(path)
                break
    if not path.exists():
        file_path = _write_public_example_file(default_draft)
        return default_draft, file_path

    text = path.read_text(encoding="utf-8").strip()
    prefix = f"# {PUBLIC_EXAMPLE_TITLE}\n\n"
    draft = text[len(prefix):].strip() if text.startswith(prefix) else text
    return draft, path.relative_to(ROOT).as_posix()


def _seed_public_example() -> None:
    readme = _read_readme_for_example()
    notes = f"公开示例素材来源：README.md\n\n{readme}"
    outline = _public_example_outline()
    draft, file_path = _read_public_example_file(_public_example_draft(readme))

    with get_session() as s:
        titles = (PUBLIC_EXAMPLE_TITLE, *PUBLIC_EXAMPLE_OLD_TITLES)
        topic = s.execute(
            select(Topic).where(Topic.owner == PUBLIC_OWNER, Topic.title.in_(titles))
        ).scalar_one_or_none()
        if topic is None:
            topic = Topic(
                title=PUBLIC_EXAMPLE_TITLE,
                content_type=ContentType.TUTORIAL.value,
                status=TopicStatus.DONE.value,
                notes=notes,
                owner=PUBLIC_OWNER,
                model=get_model(),
            )
            s.add(topic)
            s.flush()
        else:
            topic.title = PUBLIC_EXAMPLE_TITLE
            topic.content_type = ContentType.TUTORIAL.value
            topic.status = TopicStatus.DONE.value
            topic.notes = notes
            topic.model = topic.model or get_model()

        art = s.execute(select(Article).where(Article.topic_id == topic.id)).scalar_one_or_none()
        if art is None:
            art = Article(topic_id=topic.id)
            s.add(art)
        art.outline = outline
        art.draft = draft
        art.model = PUBLIC_EXAMPLE_MODEL
        art.file_path = file_path
        logger.info("public example ready: topic_id=%s", topic.id)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    _seed_public_example()
    logger.info("ai-writer started, db ready")


# ===== Schemas =====

class TopicIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content_type: ContentType = ContentType.PRODUCT_REVIEW
    notes: Optional[str] = None
    model: Optional[str] = Field(None, max_length=160)


class TopicPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    content_type: Optional[ContentType] = None
    notes: Optional[str] = None
    model: Optional[str] = Field(None, max_length=160)
    status: Optional[TopicStatus] = None


class ArticlePatch(BaseModel):
    outline: Optional[str] = None
    draft: Optional[str] = None


class ReviseIn(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=2000)


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=200)


class TopicOut(BaseModel):
    id: int
    title: str
    content_type: ContentType
    status: TopicStatus
    notes: Optional[str]
    model: str
    is_public: bool = False
    created_at: datetime
    updated_at: datetime
    has_outline: bool = False
    has_draft: bool = False

    @classmethod
    def from_orm_with_article(cls, t: Topic) -> "TopicOut":
        art = t.__dict__.get("article")
        return cls(
            id=t.id,
            title=t.title,
            content_type=t.content_type,
            status=t.status,
            notes=t.notes,
            model=_topic_model(t.model),
            is_public=t.owner == PUBLIC_OWNER,
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


def _save_draft_file(topic: Topic, draft: str, owner: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{ts}-{_slug(topic.title)}.md"
    user_dir = ARTICLES_DIR / _slug(owner, 32)
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / name
    path.write_text(f"# {topic.title}\n\n{draft}\n", encoding="utf-8")
    rel = path.relative_to(ROOT).as_posix()
    logger.info("saved draft to %s", rel)
    return rel


def _load_topic_owned(topic_id: int, owner: str) -> Optional[Topic]:
    with get_session() as s:
        stmt = (
            select(Topic)
            .options(selectinload(Topic.article))
            .where(Topic.id == topic_id, Topic.owner == owner)
        )
        return s.execute(stmt).scalar_one_or_none()


def _load_topic_visible(topic_id: int, owner: Optional[str]) -> Optional[Topic]:
    owners = [PUBLIC_OWNER]
    if owner:
        owners.append(owner)
    with get_session() as s:
        stmt = (
            select(Topic)
            .options(selectinload(Topic.article))
            .where(Topic.id == topic_id, Topic.owner.in_(owners))
        )
        return s.execute(stmt).scalar_one_or_none()


def _load_topic_writable(topic_id: int, owner: str) -> Topic:
    topic = _load_topic_owned(topic_id, owner)
    if topic is not None:
        return topic
    topic = _load_topic_visible(topic_id, owner)
    if topic is not None:
        if topic.owner == PUBLIC_OWNER and is_admin_user(owner):
            return topic
        if topic.owner == PUBLIC_OWNER:
            raise HTTPException(403, "公开示例仅管理员可修改")
        raise HTTPException(403, "无权修改该选题")
    raise HTTPException(404, "topic not found")


def _topic_write_owner(topic: Topic, user: str) -> str:
    if topic.owner == PUBLIC_OWNER and is_admin_user(user):
        return PUBLIC_OWNER
    return user


# ===== Auth endpoints =====

@app.get("/api/me")
def api_me(request: Request) -> dict:
    user = current_user(request)
    return {"user": user, "is_admin": is_admin_user(user)}


@app.post("/api/login")
def api_login(payload: LoginIn, request: Request) -> dict:
    user = authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    request.session["user"] = user
    logger.info("login: %s", user)
    return {"user": user, "is_admin": is_admin_user(user)}


@app.get("/api/usage")
def api_usage(user: str = Depends(require_user)) -> dict:
    rem = usage_remaining(user)
    return {
        "limit": FREE_LIMIT,
        "unlimited": rem is None,
        "remaining": rem,
    }


@app.get("/api/contact")
def api_contact() -> dict:
    """联系方式 + 宣传图。图片优先 web/static/contact.png/.jpg,缺省回退到占位 SVG。"""
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        p = STATIC_DIR / f"contact{ext}"
        if p.exists():
            return {
                "image": f"/static/{p.name}",
                "title": "联系我们",
                "subtitle": "扫码关注公众号 / 加微信获取更多额度",
            }
    return {
        "image": "/static/contact-placeholder.svg",
        "title": "联系我们",
        "subtitle": "把公众号宣传图保存为 web/static/contact.png 替换占位图",
    }


@app.post("/api/logout")
def api_logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@app.post("/api/register")
def api_register(payload: LoginIn, request: Request) -> dict:
    ok, msg = register_user(payload.username, payload.password)
    if not ok:
        raise HTTPException(400, msg)
    request.session["user"] = payload.username
    return {"user": payload.username, "is_admin": is_admin_user(payload.username)}


# ===== Topic endpoints =====

@app.get("/api/templates")
def api_templates() -> list[dict]:
    return [{"value": tpl.NAME, "label": tpl.DISPLAY_NAME} for tpl in TEMPLATES.values()]


@app.get("/api/models")
def api_models() -> list[dict]:
    return _model_options()


@app.get("/api/topics", response_model=list[TopicOut])
def api_list_topics(
    status: Optional[TopicStatus] = None,
    user: Optional[str] = Depends(current_user),
) -> list[TopicOut]:
    owners = [PUBLIC_OWNER]
    if user:
        owners.append(user)
    with get_session() as s:
        stmt = select(Topic).options(selectinload(Topic.article)).where(Topic.owner.in_(owners))
        if status is not None:
            stmt = stmt.where(Topic.status == status.value)
        stmt = stmt.order_by(Topic.updated_at.desc())
        topics = list(s.execute(stmt).scalars().all())
        return [TopicOut.from_orm_with_article(t) for t in topics]


@app.post("/api/topics", response_model=TopicOut, status_code=201)
def api_create_topic(payload: TopicIn, user: str = Depends(require_user)) -> TopicOut:
    t = create_topic(
        owner=user,
        title=payload.title,
        content_type=payload.content_type,
        notes=payload.notes,
        model=_topic_model(payload.model),
    )
    return TopicOut.from_orm_with_article(_load_topic_owned(t.id, user))


@app.get("/api/topics/{topic_id}", response_model=TopicOut)
def api_get_topic(topic_id: int, user: Optional[str] = Depends(current_user)) -> TopicOut:
    t = _load_topic_visible(topic_id, user)
    if t is None:
        raise HTTPException(404, "topic not found")
    return TopicOut.from_orm_with_article(t)


@app.patch("/api/topics/{topic_id}", response_model=TopicOut)
def api_patch_topic(topic_id: int, payload: TopicPatch, user: str = Depends(require_user)) -> TopicOut:
    topic = _load_topic_writable(topic_id, user)
    write_owner = _topic_write_owner(topic, user)
    data = payload.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    if "model" in data:
        data["model"] = _topic_model(data["model"])
    if data:
        if update_topic(topic_id, write_owner, **data) is None:
            raise HTTPException(404, "topic not found")
    if new_status is not None:
        if set_status(topic_id, new_status, write_owner) is None:
            raise HTTPException(404, "topic not found")
    t = _load_topic_visible(topic_id, user)
    if t is None:
        raise HTTPException(404, "topic not found")
    return TopicOut.from_orm_with_article(t)


@app.delete("/api/topics/{topic_id}", status_code=204, response_class=Response)
def api_delete_topic(topic_id: int, user: str = Depends(require_user)) -> Response:
    topic = _load_topic_writable(topic_id, user)
    if topic.owner == PUBLIC_OWNER:
        raise HTTPException(403, "公开示例不能删除")
    if not delete_topic(topic_id, user):
        raise HTTPException(404, "topic not found")
    return Response(status_code=204)


# ===== Article endpoints =====

@app.get("/api/topics/{topic_id}/article", response_model=ArticleOut)
def api_get_article(topic_id: int, user: Optional[str] = Depends(current_user)) -> ArticleOut:
    if _load_topic_visible(topic_id, user) is None:
        raise HTTPException(404, "topic not found")
    return _article_out(topic_id)


@app.patch("/api/topics/{topic_id}/article", response_model=ArticleOut)
def api_patch_article(topic_id: int, payload: ArticlePatch, user: str = Depends(require_user)) -> ArticleOut:
    topic = _load_topic_writable(topic_id, user)
    data = payload.model_dump(exclude_unset=True)
    if topic.owner == PUBLIC_OWNER and "draft" in data:
        data["file_path"] = _write_public_example_file(data["draft"] or "")
    _upsert_article(topic_id, **data)
    return _article_out(topic_id)


@app.post("/api/topics/{topic_id}/outline", response_model=ArticleOut)
def api_gen_outline(topic_id: int, user: str = Depends(require_user)) -> ArticleOut:
    topic = _load_topic_writable(topic_id, user)
    write_owner = _topic_write_owner(topic, user)
    enforce_and_increment(user)
    try:
        result = generate_outline(topic)
    except Exception as e:  # noqa: BLE001
        logger.exception("outline generation failed")
        raise HTTPException(500, f"outline 生成失败：{e}") from e
    _upsert_article(topic_id, outline=result["outline"], model=result["model"])
    if topic.status == TopicStatus.DRAFT.value:
        set_status(topic_id, TopicStatus.WRITING, write_owner)
    return _article_out(topic_id)


@app.post("/api/topics/{topic_id}/draft/revise", response_model=ArticleOut)
def api_revise_draft(topic_id: int, payload: ReviseIn, user: str = Depends(require_user)) -> ArticleOut:
    topic = _load_topic_writable(topic_id, user)
    art = _article_out(topic_id)
    if not art.draft:
        raise HTTPException(400, "当前没有初稿可修改，请先生成初稿")
    enforce_and_increment(user)
    try:
        result = generate_revision(topic, art.outline or "", art.draft, payload.instruction)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("revise failed")
        raise HTTPException(500, f"修改失败：{e}") from e
    file_path = (
        _write_public_example_file(result["draft"])
        if topic.owner == PUBLIC_OWNER
        else _save_draft_file(topic, result["draft"], user)
    )
    _upsert_article(topic_id, draft=result["draft"], model=result["model"], file_path=file_path)
    return _article_out(topic_id)


@app.post("/api/topics/{topic_id}/draft", response_model=ArticleOut)
def api_gen_draft(topic_id: int, user: str = Depends(require_user)) -> ArticleOut:
    topic = _load_topic_writable(topic_id, user)
    write_owner = _topic_write_owner(topic, user)
    art = _article_out(topic_id)
    if not art.outline:
        raise HTTPException(400, "请先生成或填写大纲")
    enforce_and_increment(user)
    try:
        result = generate_draft(topic, art.outline)
    except Exception as e:  # noqa: BLE001
        logger.exception("draft generation failed")
        raise HTTPException(500, f"draft 生成失败：{e}") from e
    file_path = (
        _write_public_example_file(result["draft"])
        if topic.owner == PUBLIC_OWNER
        else _save_draft_file(topic, result["draft"], user)
    )
    _upsert_article(topic_id, draft=result["draft"], model=result["model"], file_path=file_path)
    set_status(topic_id, TopicStatus.DONE, write_owner)
    return _article_out(topic_id)


# ===== Uploads =====

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


@app.post("/api/upload/image")
async def api_upload_image(file: UploadFile = File(...), user: str = Depends(require_user)) -> dict:
    name = file.filename or "image"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(400, f"不支持的图片格式：{ext}")
    user_dir = UPLOADS_DIR / _slug(user, 32)
    user_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe = _slug(Path(name).stem) + ext
    out = user_dir / f"{ts}-{safe}"
    data = await file.read()
    out.write_bytes(data)
    rel = out.relative_to(ROOT).as_posix()
    logger.info("uploaded image %s (%d bytes) for %s", rel, len(data), user)
    return {"url": f"/uploads/{user_dir.name}/{out.name}", "path": rel, "size": len(data)}


# ===== Static frontend =====

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
