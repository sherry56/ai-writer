"""
登录认证 & 用户隔离。

用户配置：config/users.json 或 .env 中 USERS_JSON 环境变量。
格式：
    {
      "users": {
        "admin": "明文密码或 $2b$ 开头的 bcrypt 哈希",
        "alice": "..."
      }
    }

会话：Starlette SessionMiddleware（签名 cookie），密钥来自 SESSION_SECRET。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
USERS_FILE = ROOT / "config" / "users.json"

SESSION_COOKIE = "ai_writer_session"


def get_session_secret() -> str:
    """从环境变量取签名密钥;未配置则生成临时随机串(进程重启会让旧 session 失效)。"""
    s = os.getenv("SESSION_SECRET")
    if s:
        return s
    s = secrets.token_urlsafe(48)
    logger.warning("SESSION_SECRET 未设置,本次启动用临时随机串(重启失效)")
    return s


def _load_users() -> dict[str, str]:
    """读取用户表 {username: password_or_hash}。"""
    if env := os.getenv("USERS_JSON"):
        try:
            data = json.loads(env)
            return dict(data.get("users", {}))
        except Exception as e:  # noqa: BLE001
            logger.error("USERS_JSON 解析失败: %s", e)
    if USERS_FILE.exists():
        try:
            data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
            return dict(data.get("users", {}))
        except Exception as e:  # noqa: BLE001
            logger.error("读取 %s 失败: %s", USERS_FILE, e)
    logger.warning("无用户配置(config/users.json 或 USERS_JSON 都没有),所有登录会被拒绝")
    return {}


def _verify(plain: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("$2"):
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        except Exception:  # noqa: BLE001
            return False
    return secrets.compare_digest(plain, stored)


def authenticate(username: str, password: str) -> Optional[str]:
    """验证账户密码,返回规范化的用户名(或 None)。"""
    if not username or not password:
        return None
    users = _load_users()
    stored = users.get(username)
    if stored is None:
        return None
    if _verify(password, stored):
        return username
    return None


def current_user(request: Request) -> Optional[str]:
    return request.session.get("user")


def require_user(request: Request) -> str:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "未登录")
    return user


def hash_password(plain: str) -> str:
    """工具:生成 bcrypt 哈希(给运维用)。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def register_user(username: str, password: str) -> tuple[bool, str]:
    """新注册用户写入 config/users.json,密码自动 bcrypt 哈希。
    返回 (success, message)。"""
    import re as _re
    username = (username or "").strip()
    if not _re.match(r"^[A-Za-z0-9_\-]{2,32}$", username):
        return False, "用户名只能用字母/数字/_/-,长度 2-32"
    if not password or len(password) < 6:
        return False, "密码至少 6 位"
    users = _load_users()
    if username in users:
        return False, "用户名已存在"
    users[username] = hash_password(password)
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"users": users}
    USERS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("registered user: %s", username)
    return True, "ok"
