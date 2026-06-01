"""免费次数计费。管理员不限次数；普通用户每周共享 FREE_LIMIT 次。"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from db import UserUsage, shared_session

logger = logging.getLogger(__name__)

FREE_LIMIT = int(os.getenv("FREE_LIMIT", "10"))
USAGE_TIMEZONE = (os.getenv("USAGE_TIMEZONE") or "Asia/Shanghai").strip()


def _usage_tz() -> tzinfo:
    try:
        return ZoneInfo(USAGE_TIMEZONE)
    except ZoneInfoNotFoundError:
        logger.warning("invalid USAGE_TIMEZONE=%s, fallback to Asia/Shanghai", USAGE_TIMEZONE)
        try:
            return ZoneInfo("Asia/Shanghai")
        except ZoneInfoNotFoundError:
            return timezone(timedelta(hours=8))


def is_admin(user: str) -> bool:
    admin = (os.getenv("ADMIN_USER") or "sherry").strip()
    return user == admin


def _local_now(now: Optional[datetime] = None) -> datetime:
    tz = _usage_tz()
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def current_period_start(now: Optional[datetime] = None) -> datetime:
    """返回本周一 00:00 的本地时间(存库时去掉 tzinfo,避免 SQLite 比较偏移差异)。"""
    local = _local_now(now)
    start = local - timedelta(days=local.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def next_reset_at(now: Optional[datetime] = None) -> datetime:
    tz = _usage_tz()
    start = current_period_start(now).replace(tzinfo=tz)
    return start + timedelta(days=7)


def next_reset_at_iso() -> str:
    return next_reset_at().isoformat(timespec="seconds")


def _coerce_period(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(_usage_tz()).replace(tzinfo=None)
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(_usage_tz()).replace(tzinfo=None)
        return parsed
    return None


def _ensure_current_period(row: UserUsage) -> None:
    start = current_period_start()
    if _coerce_period(row.period_start) != start:
        row.count = 0
        row.period_start = start
    if row.extra_quota is None:
        row.extra_quota = 0


def _ensure_row(session, user: str) -> UserUsage:
    row = session.get(UserUsage, user)
    if row is None:
        row = UserUsage(
            username=user,
            count=0,
            period_start=current_period_start(),
            extra_quota=0,
        )
        session.add(row)
        session.flush()
    else:
        _ensure_current_period(row)
    return row


def _status_from_row(user: str, row: Optional[UserUsage]) -> dict:
    unlimited = is_admin(user)
    if row is None:
        weekly_used = 0
        period_start = current_period_start()
        extra_quota = 0
    else:
        _ensure_current_period(row)
        weekly_used = max(0, min(int(row.count or 0), FREE_LIMIT))
        period_start = _coerce_period(row.period_start) or current_period_start()
        extra_quota = max(0, int(row.extra_quota or 0))
    weekly_remaining = max(0, FREE_LIMIT - weekly_used)
    return {
        "username": user,
        "limit": FREE_LIMIT,
        "period": "weekly",
        "period_start": period_start.isoformat(timespec="seconds"),
        "reset_at": next_reset_at_iso(),
        "unlimited": unlimited,
        "weekly_used": weekly_used,
        "weekly_remaining": weekly_remaining,
        "extra_quota": extra_quota,
        "remaining": None if unlimited else weekly_remaining + extra_quota,
    }


def get_count(user: str) -> int:
    with shared_session() as s:
        row = s.get(UserUsage, user)
        if row is None:
            return 0
        _ensure_current_period(row)
        return row.count


def remaining(user: str) -> Optional[int]:
    """返回当前可用剩余次数；管理员返回 None 表示不限。"""
    return usage_status(user)["remaining"]


def usage_status(user: str) -> dict:
    """返回当前用户用量状态,包含本周免费额度和充值余额。"""
    with shared_session() as s:
        row = s.get(UserUsage, user)
        status = _status_from_row(user, row)
        return status


def list_usage_status(users: list[str]) -> list[dict]:
    """批量返回用户用量状态。"""
    with shared_session() as s:
        out = []
        for user in users:
            row = s.get(UserUsage, user)
            out.append(_status_from_row(user, row))
        return out


def add_extra_quota(user: str, amount: int) -> dict:
    """给用户充值额外可用次数。额外次数不随周一免费额度刷新清零。"""
    amount = int(amount)
    if amount <= 0:
        raise HTTPException(400, "充值次数必须大于 0")
    with shared_session() as s:
        row = _ensure_row(s, user)
        row.extra_quota = max(0, int(row.extra_quota or 0)) + amount
        return _status_from_row(user, row)


def enforce_and_increment(user: str) -> None:
    """检查并 +1。超过本周额度抛 402。"""
    if is_admin(user):
        return
    with shared_session() as s:
        row = _ensure_row(s, user)
        if row.count < FREE_LIMIT:
            row.count += 1
            logger.info("usage %s -> %d/%d since %s", user, row.count, FREE_LIMIT, row.period_start)
            return
        if row.extra_quota > 0:
            row.extra_quota -= 1
            logger.info("usage %s consumed extra quota, remaining=%d", user, row.extra_quota)
            return
        if row.count >= FREE_LIMIT:
            raise HTTPException(
                402,
                f"本周免费次数已用完({FREE_LIMIT}/{FREE_LIMIT})，下周一 0 点刷新。"
                "请点击右上角「联系我们」获取更多额度。",
            )
