from __future__ import annotations

"""
Integration tests against the real Backblaze B2 bucket.

Run with:
    pytest tests/test_integration.py -v -m integration

These tests create and clean up their own objects under the prefix
"pytest/" so they don't interfere with other data in the bucket.
"""

import uuid
from pathlib import Path

import pytest

from s3napshot.models.profile import Profile
from s3napshot.services import archive as archive_svc
from s3napshot.services import upload as upload_svc
from tests import credentials

ENDPOINT = credentials.ENDPOINT
BUCKET = credentials.BUCKET
ACCESS_KEY_ID = credentials.ACCESS_KEY_ID
SECRET_ACCESS_KEY = credentials.SECRET_ACCESS_KEY
REGION = credentials.REGION
TEST_PREFIX = "pytest/"


@pytest.fixture(scope="module")
def profile() -> Profile:
    return Profile(
        name="integration",
        endpoint_url=ENDPOINT,
        bucket_name=BUCKET,
        access_key_id=ACCESS_KEY_ID,
        secret_access_key=SECRET_ACCESS_KEY,
        region=REGION,
    )


@pytest.fixture()
def unique_key() -> str:
    """A unique S3 key under the pytest/ prefix for test isolation."""
    return f"{TEST_PREFIX}{uuid.uuid4().hex}.tar.gz"


@pytest.fixture(autouse=True)
def cleanup(profile: Profile, unique_key: str):
    """Delete the test object after each test (best-effort)."""
    yield
    try:
        client = upload_svc._make_client(profile)
        client.delete_object(Bucket=BUCKET, Key=unique_key)
    except Exception:
        pass


@pytest.mark.integration
def test_upload_and_list(tmp_path: Path, profile: Profile, unique_key: str):
    src = tmp_path / "testdir"
    src.mkdir()
    (src / "hello.txt").write_text("integration test content")

    archive = archive_svc.create_archive(src, tmp_path)
    uri = upload_svc.upload_archive(archive, unique_key, profile)

    assert uri == f"s3://{BUCKET}/{unique_key}"

    entries = upload_svc.list_snapshots(profile, prefix=TEST_PREFIX)
    keys = [e.key for e in entries]
    assert unique_key in keys


@pytest.mark.integration
def test_upload_progress_callback(tmp_path: Path, profile: Profile, unique_key: str):
    src = tmp_path / "testdir"
    src.mkdir()
    (src / "data.bin").write_bytes(b"x" * 10_000)

    archive = archive_svc.create_archive(src, tmp_path)
    received: list[int] = []
    upload_svc.upload_archive(archive, unique_key, profile, progress_callback=received.append)

    assert len(received) > 0
    assert sum(received) > 0


@pytest.mark.integration
def test_download_round_trip(tmp_path: Path, profile: Profile, unique_key: str):
    src = tmp_path / "testdir"
    src.mkdir()
    (src / "file.txt").write_text("round trip content")

    archive = archive_svc.create_archive(src, tmp_path)
    upload_svc.upload_archive(archive, unique_key, profile)

    dest = tmp_path / "downloaded.tar.gz"
    result = upload_svc.download_snapshot(unique_key, dest, profile)

    assert result == dest
    assert dest.exists()
    assert dest.stat().st_size > 0


@pytest.mark.integration
def test_download_progress_callback(tmp_path: Path, profile: Profile, unique_key: str):
    src = tmp_path / "testdir"
    src.mkdir()
    (src / "data.bin").write_bytes(b"y" * 10_000)

    archive = archive_svc.create_archive(src, tmp_path)
    upload_svc.upload_archive(archive, unique_key, profile)

    dest = tmp_path / "downloaded.tar.gz"
    received: list[int] = []
    upload_svc.download_snapshot(unique_key, dest, profile, progress_callback=received.append)

    assert len(received) > 0


@pytest.mark.integration
def test_list_with_prefix_filter(tmp_path: Path, profile: Profile, unique_key: str):
    src = tmp_path / "testdir"
    src.mkdir()
    (src / "x.txt").write_text("x")

    archive = archive_svc.create_archive(src, tmp_path)
    upload_svc.upload_archive(archive, unique_key, profile)

    # prefix matches our object
    entries = upload_svc.list_snapshots(profile, prefix=TEST_PREFIX)
    assert any(e.key == unique_key for e in entries)

    # prefix that can't match
    entries_none = upload_svc.list_snapshots(profile, prefix="__no_such_prefix__/")
    assert not any(e.key == unique_key for e in entries_none)


@pytest.mark.integration
def test_upload_error_bad_bucket(tmp_path: Path, unique_key: str):
    bad_profile = Profile(
        name="bad",
        endpoint_url=ENDPOINT,
        bucket_name="nonexistent-bucket-xyz",
        access_key_id=ACCESS_KEY_ID,
        secret_access_key=SECRET_ACCESS_KEY,
        region=REGION,
    )
    src = tmp_path / "testdir"
    src.mkdir()
    (src / "f.txt").write_text("data")
    archive = archive_svc.create_archive(src, tmp_path)

    with pytest.raises(upload_svc.UploadError):
        upload_svc.upload_archive(archive, unique_key, bad_profile)
