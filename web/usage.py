"""免费次数计费。管理员不计数,普通用户共享 FREE_LIMIT 次。"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import HTTPException

from db import UserUsage, get_session

logger = logging.getLogger(__name__)

FREE_LIMIT = int(os.getenv("FREE_LIMIT", "3"))


def is_admin(user: str) -> bool:
    admin = (os.getenv("ADMIN_USER") or "sherry").strip()
    return user == admin


def get_count(user: str) -> int:
    with get_session() as s:
        row = s.get(UserUsage, user)
        return row.count if row else 0


def remaining(user: str) -> Optional[int]:
    """返回剩余次数;管理员返回 None 表示不限。"""
    if is_admin(user):
        return None
    return max(0, FREE_LIMIT - get_count(user))


def enforce_and_increment(user: str) -> None:
    """检查并 +1。超出额度抛 402。"""
    if is_admin(user):
        return
    with get_session() as s:
        row = s.get(UserUsage, user)
        if row is None:
            row = UserUsage(username=user, count=0)
            s.add(row)
            s.flush()
        if row.count >= FREE_LIMIT:
            raise HTTPException(
                402,
                f"免费次数已用完({FREE_LIMIT}/{FREE_LIMIT})。请点击右上角「联系我们」获取更多额度。",
            )
        row.count += 1
        logger.info("usage %s -> %d/%d", user, row.count, FREE_LIMIT)
