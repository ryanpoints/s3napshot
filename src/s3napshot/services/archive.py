from __future__ import annotations

import socket
import tarfile
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path


def make_archive_name(
    directory: Path | str,
    timestamp: datetime | None = None,
    hostname: str | None = None,
) -> str:
    directory = Path(directory)
    if timestamp is None:
        timestamp = datetime.now()
    if hostname is None:
        hostname = socket.gethostname()
    ts = timestamp.strftime("%Y-%m-%dT%H-%M-%S")
    return f"{hostname}_{directory.name}_{ts}.tar.gz"


def create_archive(
    source_dir: Path | str,
    dest: Path | str,
    *,
    progress_callback: Callable[[int], None] | None = None,
) -> Path:
    source_dir = Path(source_dir)
    dest = Path(dest)

    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source_dir}")

    archive_path = dest / make_archive_name(source_dir)

    with tarfile.open(archive_path, "w:gz") as tar:
        for file_path in sorted(source_dir.rglob("*")):
            if not file_path.is_file():
                continue
            arcname = file_path.relative_to(source_dir.parent)
            tar.add(file_path, arcname=str(arcname))
            if progress_callback is not None:
                progress_callback(file_path.stat().st_size)

    return archive_path
