"""一次性迁移:把旧的 data/db.sqlite(单库 + owner 列)拆成每个用户独立 .sqlite。

跑法:
    python scripts/migrate_per_user.py            # dry-run,只打印计划
    python scripts/migrate_per_user.py --apply    # 实际执行

执行后:
    data/db.sqlite                          (保留, 只保留 user_usage)
    data/db.sqlite.legacy.<ts>              备份
    data/users/<owner>/content.sqlite       拆出的内容库
    data/users/_public/content.sqlite       公开示例

不会动 data/articles 或 data/uploads(文件路径已经按用户分目录)。
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("migrate")

from sqlalchemy import create_engine, select  # noqa: E402

from db.models import Article, ArticleRevision, Base, Topic, UserUsage  # noqa: E402
from db.session import _ensure_scope_engine, _per_user_metadata, _session_factories, _shared_engine  # noqa: E402
from db.session import PUBLIC_SCOPE, SHARED_DB_PATH  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


def main(apply: bool) -> int:
    legacy_path = ROOT / "data" / "db.sqlite"
    if not legacy_path.exists():
        log.warning("旧库不存在: %s, 无需迁移", legacy_path)
        return 0

    # Open the legacy DB read-only via a separate engine
    legacy_engine = create_engine(
        f"sqlite:///{legacy_path.as_posix()}", future=True,
        connect_args={"check_same_thread": False},
    )
    LegacySession = sessionmaker(bind=legacy_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)

    with LegacySession() as s:
        topics = list(s.execute(select(Topic)).scalars().all())
        log.info("旧库中共 %d 条 topic", len(topics))
        by_owner: dict[str, list[Topic]] = defaultdict(list)
        for t in topics:
            by_owner[t.owner].append(t)
        for owner, items in by_owner.items():
            log.info("  owner=%r -> %d 条", owner, len(items))

        if not apply:
            log.info("dry-run 完成。加 --apply 真正写入。")
            return 0

        # backup
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup = legacy_path.with_suffix(f".sqlite.legacy.{ts}")
        shutil.copy2(legacy_path, backup)
        log.info("备份完成: %s", backup)

        for owner, items in by_owner.items():
            scope = PUBLIC_SCOPE if owner == "*" else owner
            _ensure_scope_engine(scope)
            factory = _session_factories[scope]
            with factory() as out:
                for legacy_topic in items:
                    # build new Topic in target DB (fresh id)
                    new_topic = Topic(
                        title=legacy_topic.title,
                        content_type=legacy_topic.content_type,
                        status=legacy_topic.status,
                        notes=legacy_topic.notes,
                        owner=("*" if scope == PUBLIC_SCOPE else owner),
                        model=getattr(legacy_topic, "model", None),
                        created_at=legacy_topic.created_at,
                        updated_at=legacy_topic.updated_at,
                    )
                    out.add(new_topic)
                    out.flush()

                    # carry over article
                    legacy_art = s.execute(
                        select(Article).where(Article.topic_id == legacy_topic.id)
                    ).scalar_one_or_none()
                    if legacy_art:
                        out.add(Article(
                            topic_id=new_topic.id,
                            outline=legacy_art.outline,
                            draft=legacy_art.draft,
                            file_path=legacy_art.file_path,
                            model=legacy_art.model,
                            created_at=legacy_art.created_at,
                            updated_at=legacy_art.updated_at,
                        ))

                    # carry over revisions (table may not exist on very old DBs)
                    try:
                        revs = list(s.execute(
                            select(ArticleRevision).where(ArticleRevision.topic_id == legacy_topic.id)
                        ).scalars().all())
                    except Exception:
                        revs = []
                    for r in revs:
                        out.add(ArticleRevision(
                            topic_id=new_topic.id,
                            draft=r.draft,
                            model=r.model,
                            source=r.source,
                            note=r.note,
                            created_at=r.created_at,
                        ))
                out.commit()
                log.info("[ok] scope=%s 写入 %d topic 完成", scope, len(items))

        # rewrite legacy db to keep only user_usage table
        log.info("清理旧库:仅保留 user_usage 表")
        with LegacySession() as s:
            try:
                usage_rows = list(s.execute(select(UserUsage)).scalars().all())
            except Exception:
                usage_rows = []

        # release all locks on legacy file before unlink
        legacy_engine.dispose()
        try:
            _shared_engine.dispose()
        except Exception:
            pass

        # drop & recreate legacy file with only shared tables
        legacy_path.unlink()
        new_engine = create_engine(
            f"sqlite:///{legacy_path.as_posix()}", future=True,
            connect_args={"check_same_thread": False},
        )
        from sqlalchemy import MetaData
        md = MetaData()
        UserUsage.__table__.to_metadata(md).create(bind=new_engine)
        NewSession = sessionmaker(bind=new_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
        with NewSession() as s:
            for u in usage_rows:
                s.add(UserUsage(
                    username=u.username,
                    count=u.count,
                    period_start=getattr(u, "period_start", None),
                    extra_quota=getattr(u, "extra_quota", 0),
                    updated_at=u.updated_at,
                ))
            s.commit()
        log.info("迁移完成。请检查 data/users/<scope>/content.sqlite")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际执行迁移(默认只 dry-run)")
    args = parser.parse_args()
    sys.exit(main(args.apply))
