"""FastAPI 后端 + 登录认证 + 用户独立 SQLite。"""

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

from db import (
    Article,
    ArticleRevision,
    ContentType,
    PUBLIC_SCOPE,
    Topic,
    TopicStatus,
    get_session,
    init_db,
)
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
    list_usernames,
    register_user,
    require_user,
)
from web.usage import (
    FREE_LIMIT,
    add_extra_quota,
    enforce_and_increment,
    list_usage_status,
    next_reset_at_iso,
    usage_status,
)
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


def is_admin_user(user: Optional[str]) -> bool:
    return bool(user and user == ADMIN_USER)


def require_admin(user: str = Depends(require_user)) -> str:
    if not is_admin_user(user):
        raise HTTPException(403, "需要管理员权限")
    return user


app = FastAPI(title="ai-writer", version="0.4.0")

app.add_middleware(
    SessionMiddleware,
    secret_key=get_session_secret(),
    session_cookie=SESSION_COOKIE,
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 30,
)


# ===== misc helpers =====

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


def _slug(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[\\/:*?\"<>|\s]+", "-", text).strip("-")
    return text[:max_len] or "untitled"


def _outline_from_draft(draft: str) -> str:
    lines: list[str] = []
    in_code = False
    for raw in draft.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{2,3})\s+(.+?)\s*#*\s*$", stripped)
        if not m:
            continue
        level = len(m.group(1))
        indent = "  " * (level - 2)
        lines.append(f"{indent}- {m.group(2)}")
    return "\n".join(lines) or "（参考正文结构）"


def _write_public_example_file(draft: str) -> str:
    public_dir = ARTICLES_DIR / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    path = public_dir / f"{PUBLIC_EXAMPLE_TITLE}.md"
    path.write_text(f"# {PUBLIC_EXAMPLE_TITLE}\n\n{draft}\n", encoding="utf-8")
    return path.relative_to(ROOT).as_posix()


def _read_public_example_file() -> tuple[Optional[str], Optional[str]]:
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
        return None, None
    text = path.read_text(encoding="utf-8").strip()
    prefix = f"# {PUBLIC_EXAMPLE_TITLE}\n\n"
    draft = text[len(prefix):].strip() if text.startswith(prefix) else text
    return draft, path.relative_to(ROOT).as_posix()


def _seed_public_example() -> None:
    draft, file_path = _read_public_example_file()
    if not draft:
        logger.info("public example .md missing, skip seeding")
        return
    outline = _outline_from_draft(draft)
    notes = "公开示例素材来源：data/articles/public/" + f"{PUBLIC_EXAMPLE_TITLE}.md"
    titles = (PUBLIC_EXAMPLE_TITLE, *PUBLIC_EXAMPLE_OLD_TITLES)

    with get_session(PUBLIC_SCOPE) as s:
        topic = s.execute(
            select(Topic).where(Topic.title.in_(titles))
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
            topic.owner = PUBLIC_OWNER

        art = s.execute(select(Article).where(Article.topic_id == topic.id)).scalar_one_or_none()
        if art is None:
            art = Article(topic_id=topic.id)
            s.add(art)
        art.outline = outline
        art.draft = draft
        art.model = PUBLIC_EXAMPLE_MODEL
        art.file_path = file_path
        logger.info("public example synced -> topic_id=%s", topic.id)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    _seed_public_example()
    logger.info("ai-writer started")


# ===== Schemas =====

class TopicIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content_type: ContentType = ContentType.PRODUCT_REVIEW
    notes: Optional[str] = None
    model: Optional[str] = Field(None, max_length=160)
    target_length: Optional[int] = Field(None, ge=200, le=20000)


class TopicPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    content_type: Optional[ContentType] = None
    notes: Optional[str] = None
    model: Optional[str] = Field(None, max_length=160)
    target_length: Optional[int] = Field(None, ge=200, le=20000)
    status: Optional[TopicStatus] = None


class ArticlePatch(BaseModel):
    outline: Optional[str] = None
    draft: Optional[str] = None


class ReviseIn(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=2000)


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=200)


class QuotaAddIn(BaseModel):
    amount: int = Field(..., ge=1, le=100000)


class TopicOut(BaseModel):
    id: int
    title: str
    content_type: ContentType
    status: TopicStatus
    notes: Optional[str]
    model: str
    target_length: Optional[int] = None
    is_public: bool = False
    created_at: datetime
    updated_at: datetime
    has_outline: bool = False
    has_draft: bool = False

    @classmethod
    def from_orm_with_article(cls, t: Topic, *, is_public: bool) -> "TopicOut":
        art = t.__dict__.get("article")
        return cls(
            id=t.id,
            title=t.title,
            content_type=t.content_type,
            status=t.status,
            notes=t.notes,
            model=_topic_model(t.model),
            target_length=t.target_length,
            is_public=is_public,
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


# ===== scope helpers =====

def _scope_for(user: Optional[str], public: bool) -> str:
    """请求作用域:公开示例 → _public,否则 → 当前用户(必须登录)。"""
    if public:
        return PUBLIC_SCOPE
    if not user:
        raise HTTPException(401, "未登录")
    return user


def _require_write_perm(scope: str, user: Optional[str]) -> None:
    """公开示例只允许管理员写。"""
    if scope == PUBLIC_SCOPE and not is_admin_user(user):
        raise HTTPException(403, "公开示例仅管理员可修改")


def _load_topic(scope: str, topic_id: int) -> Topic:
    with get_session(scope) as s:
        stmt = select(Topic).options(selectinload(Topic.article)).where(Topic.id == topic_id)
        t = s.execute(stmt).scalar_one_or_none()
        if t is None:
            raise HTTPException(404, "topic not found")
        return t


def _article_out(scope: str, topic_id: int) -> ArticleOut:
    with get_session(scope) as s:
        art = s.execute(select(Article).where(Article.topic_id == topic_id)).scalar_one_or_none()
        if art is None:
            return ArticleOut(topic_id=topic_id, outline=None, draft=None, file_path=None, model=None)
        return ArticleOut(
            topic_id=art.topic_id,
            outline=art.outline,
            draft=art.draft,
            file_path=art.file_path,
            model=art.model,
        )


def _upsert_article(scope: str, topic_id: int, *,
                    outline: Optional[str] = None,
                    draft: Optional[str] = None,
                    model: Optional[str] = None,
                    file_path: Optional[str] = None) -> None:
    with get_session(scope) as s:
        art = s.execute(select(Article).where(Article.topic_id == topic_id)).scalar_one_or_none()
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


def _snapshot_revision(scope: str, topic_id: int, draft: str, *,
                       model: Optional[str], source: str,
                       note: Optional[str] = None) -> None:
    if not draft or not draft.strip():
        return
    with get_session(scope) as s:
        s.add(ArticleRevision(
            topic_id=topic_id, draft=draft, model=model, source=source, note=note,
        ))


def _save_draft_file(scope: str, topic: Topic, draft: str) -> str:
    folder_name = "public" if scope == PUBLIC_SCOPE else _slug(scope, 32)
    user_dir = ARTICLES_DIR / folder_name
    user_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = user_dir / f"{ts}-{_slug(topic.title)}.md"
    path.write_text(f"# {topic.title}\n\n{draft}\n", encoding="utf-8")
    return path.relative_to(ROOT).as_posix()


# ===== Auth =====

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
    return {"user": user, "is_admin": is_admin_user(user)}


@app.post("/api/logout")
def api_logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@app.post("/api/register")
def api_register(payload: LoginIn, request: Request) -> dict:
    username = payload.username.strip().lower()
    ok, msg = register_user(username, payload.password)
    if not ok:
        raise HTTPException(400, msg)
    request.session["user"] = username
    return {"user": username, "is_admin": is_admin_user(username)}


@app.get("/api/usage")
def api_usage(user: str = Depends(require_user)) -> dict:
    return usage_status(user)


@app.get("/api/admin/quotas")
def api_admin_quotas(user: str = Depends(require_admin)) -> dict:
    users = list_usernames()
    return {
        "limit": FREE_LIMIT,
        "period": "weekly",
        "reset_at": next_reset_at_iso(),
        "admin": user,
        "users": list_usage_status(users),
    }


@app.post("/api/admin/quotas/{username}/add")
def api_admin_quota_add(username: str, payload: QuotaAddIn, user: str = Depends(require_admin)) -> dict:
    users = set(list_usernames())
    if username not in users:
        raise HTTPException(404, "用户不存在")
    if is_admin_user(username):
        raise HTTPException(400, "管理员账号不限次数,无需充值")
    return add_extra_quota(username, payload.amount)


@app.get("/api/contact")
def api_contact() -> dict:
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        p = STATIC_DIR / f"contact{ext}"
        if p.exists():
            return {"image": f"/static/{p.name}", "title": "联系我们",
                    "subtitle": "扫码关注公众号 / 加微信获取更多额度"}
    return {"image": "/static/contact-placeholder.svg", "title": "联系我们",
            "subtitle": "把公众号宣传图保存为 web/static/contact.png 替换占位图"}


# ===== Topic listing (merged) =====

@app.get("/api/templates")
def api_templates() -> list[dict]:
    return [{"value": tpl.NAME, "label": tpl.DISPLAY_NAME} for tpl in TEMPLATES.values()]


@app.get("/api/models")
def api_models() -> list[dict]:
    return _model_options()


@app.get("/api/topics", response_model=list[TopicOut])
def api_list_topics(
    request: Request,
    status: Optional[TopicStatus] = None,
) -> list[TopicOut]:
    user = current_user(request)
    out: list[TopicOut] = []

    # public scope: always visible
    with get_session(PUBLIC_SCOPE) as s:
        stmt = select(Topic).options(selectinload(Topic.article))
        if status is not None:
            stmt = stmt.where(Topic.status == status.value)
        stmt = stmt.order_by(Topic.updated_at.desc())
        for t in s.execute(stmt).scalars().all():
            out.append(TopicOut.from_orm_with_article(t, is_public=True))

    # user scope
    if user:
        with get_session(user) as s:
            stmt = select(Topic).options(selectinload(Topic.article))
            if status is not None:
                stmt = stmt.where(Topic.status == status.value)
            stmt = stmt.order_by(Topic.updated_at.desc())
            for t in s.execute(stmt).scalars().all():
                out.append(TopicOut.from_orm_with_article(t, is_public=False))

    out.sort(key=lambda x: x.updated_at, reverse=True)
    return out


# ===== Per-topic ops: factor by scope =====

def _topic_routes(prefix: str, public: bool, write_dep) -> None:
    """注册 /api{prefix}/topics/... 一组路由。public=True 时 prefix='/public'。"""

    @app.post(f"/api{prefix}/topics", response_model=TopicOut, status_code=201)
    def _create_topic(payload: TopicIn, user: str = Depends(write_dep)) -> TopicOut:
        scope = _scope_for(user, public)
        t = create_topic(
            scope=scope,
            title=payload.title,
            content_type=payload.content_type,
            notes=payload.notes,
            model=_topic_model(payload.model),
            target_length=payload.target_length,
        )
        return TopicOut.from_orm_with_article(_load_topic(scope, t.id), is_public=public)

    @app.get(f"/api{prefix}/topics/{{topic_id}}", response_model=TopicOut)
    def _get_topic(topic_id: int, request: Request) -> TopicOut:
        scope = _scope_for(current_user(request), public)
        return TopicOut.from_orm_with_article(_load_topic(scope, topic_id), is_public=public)

    @app.patch(f"/api{prefix}/topics/{{topic_id}}", response_model=TopicOut)
    def _patch_topic(topic_id: int, payload: TopicPatch, user: str = Depends(write_dep)) -> TopicOut:
        scope = _scope_for(user, public)
        _require_write_perm(scope, user)
        data = payload.model_dump(exclude_unset=True)
        new_status = data.pop("status", None)
        if "model" in data:
            data["model"] = _topic_model(data["model"])
        if data:
            if update_topic(topic_id, scope, **data) is None:
                raise HTTPException(404, "topic not found")
        if new_status is not None:
            if set_status(topic_id, new_status, scope) is None:
                raise HTTPException(404, "topic not found")
        return TopicOut.from_orm_with_article(_load_topic(scope, topic_id), is_public=public)

    @app.delete(f"/api{prefix}/topics/{{topic_id}}", status_code=204, response_class=Response)
    def _delete_topic(topic_id: int, user: str = Depends(write_dep)) -> Response:
        scope = _scope_for(user, public)
        _require_write_perm(scope, user)
        if scope == PUBLIC_SCOPE:
            raise HTTPException(403, "公开示例不能删除")
        if not delete_topic(topic_id, scope):
            raise HTTPException(404, "topic not found")
        return Response(status_code=204)

    @app.get(f"/api{prefix}/topics/{{topic_id}}/article", response_model=ArticleOut)
    def _get_article(topic_id: int, request: Request) -> ArticleOut:
        scope = _scope_for(current_user(request), public)
        _load_topic(scope, topic_id)
        return _article_out(scope, topic_id)

    @app.patch(f"/api{prefix}/topics/{{topic_id}}/article", response_model=ArticleOut)
    def _patch_article(topic_id: int, payload: ArticlePatch, user: str = Depends(write_dep)) -> ArticleOut:
        scope = _scope_for(user, public)
        _require_write_perm(scope, user)
        _load_topic(scope, topic_id)
        data = payload.model_dump(exclude_unset=True)
        if scope == PUBLIC_SCOPE and "draft" in data:
            data["file_path"] = _write_public_example_file(data["draft"] or "")
        _upsert_article(scope, topic_id, **data)
        return _article_out(scope, topic_id)

    @app.post(f"/api{prefix}/topics/{{topic_id}}/outline", response_model=ArticleOut)
    def _gen_outline(topic_id: int, user: str = Depends(write_dep)) -> ArticleOut:
        scope = _scope_for(user, public)
        _require_write_perm(scope, user)
        topic = _load_topic(scope, topic_id)
        enforce_and_increment(user)
        try:
            result = generate_outline(topic)
        except Exception as e:  # noqa: BLE001
            logger.exception("outline failed")
            raise HTTPException(500, f"outline 生成失败：{e}") from e
        _upsert_article(scope, topic_id, outline=result["outline"], model=result["model"])
        if topic.status == TopicStatus.DRAFT.value:
            set_status(topic_id, TopicStatus.WRITING, scope)
        return _article_out(scope, topic_id)

    @app.post(f"/api{prefix}/topics/{{topic_id}}/draft", response_model=ArticleOut)
    def _gen_draft(topic_id: int, user: str = Depends(write_dep)) -> ArticleOut:
        scope = _scope_for(user, public)
        _require_write_perm(scope, user)
        topic = _load_topic(scope, topic_id)
        art = _article_out(scope, topic_id)
        if not art.outline:
            raise HTTPException(400, "请先生成或填写大纲")
        enforce_and_increment(user)
        try:
            result = generate_draft(topic, art.outline)
        except Exception as e:  # noqa: BLE001
            logger.exception("draft failed")
            raise HTTPException(500, f"draft 生成失败：{e}") from e
        file_path = (
            _write_public_example_file(result["draft"]) if scope == PUBLIC_SCOPE
            else _save_draft_file(scope, topic, result["draft"])
        )
        _upsert_article(scope, topic_id, draft=result["draft"], model=result["model"], file_path=file_path)
        _snapshot_revision(scope, topic_id, result["draft"], model=result["model"], source="draft")
        set_status(topic_id, TopicStatus.DONE, scope)
        return _article_out(scope, topic_id)

    @app.post(f"/api{prefix}/topics/{{topic_id}}/draft/revise", response_model=ArticleOut)
    def _revise_draft(topic_id: int, payload: ReviseIn, user: str = Depends(write_dep)) -> ArticleOut:
        scope = _scope_for(user, public)
        _require_write_perm(scope, user)
        topic = _load_topic(scope, topic_id)
        art = _article_out(scope, topic_id)
        if not art.draft:
            raise HTTPException(400, "当前没有初稿可修改,请先生成初稿")
        enforce_and_increment(user)
        try:
            result = generate_revision(topic, art.outline or "", art.draft, payload.instruction)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("revise failed")
            raise HTTPException(500, f"修改失败：{e}") from e
        file_path = (
            _write_public_example_file(result["draft"]) if scope == PUBLIC_SCOPE
            else _save_draft_file(scope, topic, result["draft"])
        )
        _upsert_article(scope, topic_id, draft=result["draft"], model=result["model"], file_path=file_path)
        _snapshot_revision(scope, topic_id, result["draft"], model=result["model"],
                           source="revise", note=payload.instruction[:200])
        return _article_out(scope, topic_id)

    @app.get(f"/api{prefix}/topics/{{topic_id}}/revisions")
    def _list_revisions(topic_id: int, request: Request) -> list[dict]:
        scope = _scope_for(current_user(request), public)
        _load_topic(scope, topic_id)
        with get_session(scope) as s:
            rows = list(s.execute(
                select(ArticleRevision).where(ArticleRevision.topic_id == topic_id)
                .order_by(ArticleRevision.created_at.desc()).limit(50)
            ).scalars().all())
            return [
                {
                    "id": r.id, "source": r.source, "model": r.model, "note": r.note,
                    "created_at": r.created_at.isoformat(),
                    "preview": (r.draft[:120] + "…") if len(r.draft) > 120 else r.draft,
                    "length": len(r.draft),
                }
                for r in rows
            ]

    @app.get(f"/api{prefix}/topics/{{topic_id}}/revisions/{{rev_id}}")
    def _get_revision(topic_id: int, rev_id: int, request: Request) -> dict:
        scope = _scope_for(current_user(request), public)
        _load_topic(scope, topic_id)
        with get_session(scope) as s:
            rev = s.get(ArticleRevision, rev_id)
            if rev is None or rev.topic_id != topic_id:
                raise HTTPException(404, "revision not found")
            return {
                "id": rev.id, "source": rev.source, "model": rev.model, "note": rev.note,
                "created_at": rev.created_at.isoformat(), "draft": rev.draft,
            }


# 用户路由(/api/topics/*) - require login
_topic_routes("", public=False, write_dep=require_user)
# 公开示例路由(/api/public/topics/*) - 读公开可匿名,写需管理员
_topic_routes("/public", public=True, write_dep=require_admin)


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


# ===== Static =====

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
