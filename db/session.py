"""
数据库会话与初始化。

用法：
    from db.session import init_db, get_session

    init_db()                      # 应用启动时调用一次，建表
    with get_session() as s:       # 业务里用上下文管理器
        s.add(obj)
        s.commit()
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base

# 加载 .env（项目根）
load_dotenv(override=True)

# 数据库 URL 来自 .env，默认 sqlite 文件
_DEFAULT_DB_URL = "sqlite:///data/db.sqlite"
DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_DB_URL)

# 确保 sqlite 文件所在目录存在
if DATABASE_URL.startswith("sqlite:///"):
    _db_path = Path(DATABASE_URL.replace("sqlite:///", "", 1))
    _db_path.parent.mkdir(parents=True, exist_ok=True)

# SQLite 在多线程（Streamlit）场景下需要 check_same_thread=False
_engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, future=True, **_engine_kwargs)
# expire_on_commit=False：让 ORM 对象在 commit 后仍可读属性
# （Streamlit 页面常常拿 manager 返回的对象直接显示，不想再开一次 session 刷新）
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def init_db() -> None:
    """建表（幂等）。应用启动时调用一次。"""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Iterator[Session]:
    """会话上下文管理器，自动 commit/rollback/close。"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
