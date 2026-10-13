"""Private Durable Object backup format for Cloudflare Container restarts."""

from __future__ import annotations

import io
import os
import shutil
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
MAX_ARCHIVE_BYTES = 40 * 1024 * 1024
PERSISTED_PATHS = (
    Path("data/db.sqlite"),
    Path("data/users"),
    Path("data/articles"),
    Path("data/uploads"),
    Path("data/style_lib"),
    Path("config/users.json"),
)


def _checkpoint_databases() -> None:
    # Export runs after an application request has committed. Checkpoint any WAL
    # files so the archive is a complete, self-contained SQLite snapshot.
    try:
        from db.session import _engines, _shared_engine

        engines = [_shared_engine, *_engines.values()]
    except Exception:  # pragma: no cover - defensive for offline tooling
        engines = []
    for engine in engines:
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            # SQLite's default journal mode has no WAL to checkpoint. A busy
            # database is not silently accepted when WAL mode is active.
            with engine.connect() as connection:
                mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
            if str(mode).lower() == "wal":
                raise


def create_state_archive(root: Path = ROOT) -> bytes:
    """Build a compressed archive containing only app state, never secrets/env."""
    root = root.resolve()
    if root == ROOT:
        _checkpoint_databases()
    output = io.BytesIO()
    expanded_size = 0
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for relative in PERSISTED_PATHS:
            source = root / relative
            if not source.exists():
                continue
            candidates = [source] if source.is_file() else sorted(source.rglob("*"))
            for candidate in candidates:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                if candidate.name.endswith(("-wal", "-shm")) or candidate.suffix == ".log":
                    continue
                expanded_size += candidate.stat().st_size
                if expanded_size > MAX_ARCHIVE_BYTES:
                    raise ValueError("expanded state archive exceeds 40 MiB")
                archive_name = candidate.relative_to(root).as_posix()
                info = archive.gettarinfo(str(candidate), arcname=archive_name)
                with candidate.open("rb") as stream:
                    archive.addfile(info, stream)
    payload = output.getvalue()
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("state archive exceeds 40 MiB")
    return payload


def restore_state_archive(payload: bytes, root: Path = ROOT) -> None:
    """Replace persisted state from a trusted backup archive with strict path checks."""
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("state archive is too large")
    root = root.resolve()
    members: list[tuple[tarfile.TarInfo, bytes]] = []
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts or "\\" in member.name:
                    raise ValueError("invalid state archive path")
                if not member.isfile() or member.issym() or member.islnk():
                    raise ValueError("unsupported state archive entry")
                if not (
                    member.name == "data/db.sqlite"
                    or member.name == "config/users.json"
                    or member.name.startswith(("data/users/", "data/articles/", "data/uploads/", "data/style_lib/"))
                ):
                    raise ValueError("unexpected state archive entry")
                total += member.size
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError("expanded state archive is too large")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("invalid state archive entry")
                members.append((member, stream.read()))
    except (tarfile.TarError, OSError) as error:
        raise ValueError("invalid state archive") from error

    validated_members: list[tuple[Path, bytes]] = []
    for member, contents in members:
        destination = (root / PurePosixPath(member.name)).resolve()
        if not destination.is_relative_to(root):
            raise ValueError("state archive path escapes application root")
        validated_members.append((destination, contents))

    reinitialize_database = root == ROOT
    if reinitialize_database:
        from db.session import _engines, _session_factories, _shared_engine

        _shared_engine.dispose()
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
        _session_factories.clear()

    # Validate every entry before changing disk, then replace only persisted
    # roots. Keep unrelated data directories intact.
    for relative in PERSISTED_PATHS:
        destination = root / relative
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink(missing_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    users_file = root / "config" / "users.json"
    users_file.unlink(missing_ok=True)
    for destination, contents in validated_members:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".restore-tmp")
        temporary.write_bytes(contents)
        os.replace(temporary, destination)

    if reinitialize_database:
        from db.session import init_db

        init_db()
