"""数据库会话:每用户一个独立 .sqlite,共享库只放 user_usage。

布局:
    data/
    ├── db.sqlite                    # 共享:user_usage
    └── users/
        ├── _public/content.sqlite   # 公开示例
        ├── sherry/content.sqlite    # 各用户的 topics / articles / revisions
        └── ...

用法:
    with get_session("sherry") as s:   # 默认 = 当前登录用户的库
        ...
    with shared_session() as s:        # user_usage 等跨用户表
        ...
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base, UserUsage  # noqa: F401  ensure tables register

load_dotenv(override=True)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
USERS_DIR = DATA_DIR / "users"
DATA_DIR.mkdir(parents=True, exist_ok=True)
USERS_DIR.mkdir(parents=True, exist_ok=True)

SHARED_DB_PATH = DATA_DIR / "db.sqlite"
PUBLIC_SCOPE = "_public"

# Tables that live in the per-user content DB
PER_USER_TABLES = {"topics", "articles", "article_revisions"}
# Tables that live in the shared DB
SHARED_TABLES = {"user_usage"}

_SCOPE_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _safe_scope(scope: str) -> str:
    s = (scope or "").strip()
    if not s or not _SCOPE_RE.match(s):
        raise ValueError(f"非法的用户 scope: {scope!r}")
    return s


def _scope_db_path(scope: str) -> Path:
    return USERS_DIR / _safe_scope(scope) / "content.sqlite"


_engines: dict[str, "object"] = {}
_session_factories: dict[str, sessionmaker] = {}


def _make_engine(url: str):
    return create_engine(
        url, future=True,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )


def _per_user_metadata():
    """Subset of Base.metadata that should live in per-user DBs."""
    from sqlalchemy import MetaData
    md = MetaData()
    for t in Base.metadata.sorted_tables:
        if t.name in PER_USER_TABLES:
            t.to_metadata(md)
    return md


def _shared_metadata():
    from sqlalchemy import MetaData
    md = MetaData()
    for t in Base.metadata.sorted_tables:
        if t.name in SHARED_TABLES:
            t.to_metadata(md)
    return md


def _ensure_scope_engine(scope: str):
    scope = _safe_scope(scope)
    if scope in _engines:
        return _engines[scope]
    path = _scope_db_path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = _make_engine(f"sqlite:///{path.as_posix()}")
    _per_user_metadata().create_all(bind=engine)
    _engines[scope] = engine
    _session_factories[scope] = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True,
    )
    return engine


# Shared engine for cross-user tables (UserUsage)
_shared_engine = _make_engine(f"sqlite:///{SHARED_DB_PATH.as_posix()}")
_shared_metadata().create_all(bind=_shared_engine)
_SharedSession = sessionmaker(
    bind=_shared_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True,
)


def init_db() -> None:
    """启动时调用一次,保证共享库 + 公开示例库存在(各用户库按需懒加载)。"""
    _shared_metadata().create_all(bind=_shared_engine)
    _ensure_scope_engine(PUBLIC_SCOPE)


@contextmanager
def get_session(scope: str) -> Iterator[Session]:
    """打开指定 scope(=用户名,或 _public)的 session。"""
    _ensure_scope_engine(scope)
    factory = _session_factories[scope]
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def shared_session() -> Iterator[Session]:
    """跨用户表(user_usage 等)使用共享 DB。"""
    session = _SharedSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ===== legacy support: tools that imported `engine` directly =====
engine = _shared_engine  # backwards compatibility alias; do NOT use for per-user tables
