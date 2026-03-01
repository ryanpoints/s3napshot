from __future__ import annotations

import tarfile
from datetime import datetime
from pathlib import Path

import pytest

from s3napshot.services.archive import create_archive, make_archive_name


def test_make_archive_name_format():
    ts = datetime(2026, 3, 1, 14, 32, 0)
    name = make_archive_name(Path("/some/path/mydir"), timestamp=ts, hostname="myhost")
    assert name == "myhost_mydir_2026-03-01T14-32-00.tar.gz"


def test_make_archive_name_uses_basename():
    ts = datetime(2026, 1, 1, 0, 0, 0)
    name = make_archive_name("/deep/nested/folder", timestamp=ts, hostname="host")
    assert name.startswith("host_folder_")


def test_make_archive_name_default_timestamp():
    name = make_archive_name("mydir", hostname="host")
    assert name.startswith("host_mydir_")
    assert name.endswith(".tar.gz")


def test_make_archive_name_includes_hostname():
    import socket
    name = make_archive_name("mydir")
    assert name.startswith(socket.gethostname() + "_")


def test_create_archive_round_trip(tmp_path: Path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "hello.txt").write_text("hello world")
    (src / "sub").mkdir()
    (src / "sub" / "deep.txt").write_text("nested")

    dest = tmp_path / "out"
    dest.mkdir()
    archive = create_archive(src, dest)

    assert archive.exists()
    assert archive.suffix == ".gz"

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()

    assert any("hello.txt" in n for n in names)
    assert any("deep.txt" in n for n in names)


def test_create_archive_progress_callback(tmp_path: Path):
    src = tmp_path / "source"
    src.mkdir()
    content = b"x" * 1024
    (src / "a.bin").write_bytes(content)
    (src / "b.bin").write_bytes(content)

    dest = tmp_path / "out"
    dest.mkdir()
    total = 0

    def callback(n: int) -> None:
        nonlocal total
        total += n

    create_archive(src, dest, progress_callback=callback)
    assert total == 2 * 1024


def test_create_archive_missing_source(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        create_archive(tmp_path / "nonexistent", tmp_path)


def test_create_archive_not_a_directory(tmp_path: Path):
    f = tmp_path / "file.txt"
    f.write_text("data")
    with pytest.raises(NotADirectoryError):
        create_archive(f, tmp_path)


def test_create_archive_excludes_symlinked_dirs(tmp_path: Path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "real.txt").write_text("real")

    # Create a symlink to a directory — should be skipped
    target = tmp_path / "target_dir"
    target.mkdir()
    (target / "secret.txt").write_text("should not appear")
    (src / "link").symlink_to(target)

    dest = tmp_path / "out"
    dest.mkdir()
    archive = create_archive(src, dest)

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()

    assert not any("secret.txt" in n for n in names)
