from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest
from cryptography.fernet import Fernet
from moto import mock_aws
from typer.testing import CliRunner

from s3napshot.cli.commands import app
from s3napshot.models.profile import Profile
from s3napshot.services import config as config_svc

RUNNER = CliRunner()

AWS_REGION = "us-east-1"
BUCKET_NAME = "test-bucket"


def _make_profile(name: str = "default") -> Profile:
    return Profile(
        name=name,
        endpoint_url="",
        bucket_name=BUCKET_NAME,
        access_key_id="testing",
        secret_access_key="testing",
        region=AWS_REGION,
    )


@pytest.fixture()
def fernet_key() -> bytes:
    return Fernet.generate_key()


@pytest.fixture()
def profiles_file(tmp_path: Path, fernet_key: bytes) -> Path:
    return tmp_path / "profiles.enc"


@pytest.fixture(autouse=True)
def patch_config(profiles_file: Path, fernet_key: bytes):
    """Redirect config to temp paths and inject test Fernet key."""
    with (
        patch.object(config_svc, "PROFILES_FILE", profiles_file),
        patch("s3napshot.cli.commands.config_svc.PROFILES_FILE", profiles_file),
        patch("s3napshot.cli.commands.config_svc.get_fernet", return_value=Fernet(fernet_key)),
        patch.object(config_svc, "get_fernet", return_value=Fernet(fernet_key)),
    ):
        yield


def _save_profile(profile: Profile, profiles_file: Path, fernet_key: bytes) -> None:
    from s3napshot.services.config import save_profiles
    fernet = Fernet(fernet_key)
    save_profiles({profile.name: profile}, profiles_file, fernet)


# ---------------------------------------------------------------------------
# profile add
# ---------------------------------------------------------------------------

class TestProfileAdd:
    def test_add_with_flags(self, profiles_file: Path, fernet_key: bytes):
        result = RUNNER.invoke(app, [
            "profile", "add",
            "--name", "myprofile",
            "--endpoint", "https://s3.example.com",
            "--bucket", "mybucket",
            "--access-key", "AKI123",
            "--secret-key", "SECRET456",
            "--region", "eu-west-1",
        ])
        assert result.exit_code == 0, result.output
        assert "saved" in result.output

        from s3napshot.services.config import load_profiles
        loaded = load_profiles(profiles_file, Fernet(fernet_key))
        assert "myprofile" in loaded
        assert loaded["myprofile"].bucket_name == "mybucket"

    def test_add_duplicate_fails(self, profiles_file: Path, fernet_key: bytes):
        _save_profile(_make_profile("myprofile"), profiles_file, fernet_key)
        result = RUNNER.invoke(app, [
            "profile", "add",
            "--name", "myprofile",
            "--endpoint", "https://s3.example.com",
            "--bucket", "mybucket",
            "--access-key", "AKI123",
            "--secret-key", "SECRET456",
        ])
        assert result.exit_code == 1

    def test_add_with_overwrite(self, profiles_file: Path, fernet_key: bytes):
        _save_profile(_make_profile("myprofile"), profiles_file, fernet_key)
        result = RUNNER.invoke(app, [
            "profile", "add",
            "--name", "myprofile",
            "--endpoint", "https://new.endpoint.com",
            "--bucket", "newbucket",
            "--access-key", "NEWKEY",
            "--secret-key", "NEWSECRET",
            "--overwrite",
        ])
        assert result.exit_code == 0, result.output

    def test_add_invalid_name(self):
        result = RUNNER.invoke(app, [
            "profile", "add",
            "--name", "bad name!",
            "--endpoint", "https://s3.example.com",
            "--bucket", "mybucket",
            "--access-key", "AKI123",
            "--secret-key", "SECRET456",
        ])
        assert result.exit_code == 1

    def test_add_with_prompts(self, profiles_file: Path, fernet_key: bytes):
        result = RUNNER.invoke(app, ["profile", "add"], input=(
            "prompted\n"
            "https://s3.example.com\n"
            "mybucket\n"
            "AKIAPROMPTED\n"
            "SECRETPROMPTED\n"
        ))
        assert result.exit_code == 0, result.output
        assert "saved" in result.output


# ---------------------------------------------------------------------------
# profile list
# ---------------------------------------------------------------------------

class TestProfileList:
    def test_list_empty(self):
        result = RUNNER.invoke(app, ["profile", "list"])
        assert result.exit_code == 0
        assert "No profiles" in result.output

    def test_list_masks_secrets(self, profiles_file: Path, fernet_key: bytes):
        _save_profile(_make_profile(), profiles_file, fernet_key)
        result = RUNNER.invoke(app, ["profile", "list"])
        assert result.exit_code == 0
        assert "testing" not in result.output  # secret_access_key is "testing"
        assert "****" in result.output


# ---------------------------------------------------------------------------
# profile remove
# ---------------------------------------------------------------------------

class TestProfileRemove:
    def test_remove_existing(self, profiles_file: Path, fernet_key: bytes):
        _save_profile(_make_profile(), profiles_file, fernet_key)
        result = RUNNER.invoke(app, ["profile", "remove", "default", "--yes"])
        assert result.exit_code == 0
        assert "removed" in result.output

    def test_remove_nonexistent(self):
        result = RUNNER.invoke(app, ["profile", "remove", "ghost", "--yes"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

class TestUpload:
    @mock_aws
    def test_upload_success(self, tmp_path: Path, profiles_file: Path, fernet_key: bytes):
        boto3.client("s3", region_name=AWS_REGION).create_bucket(Bucket=BUCKET_NAME)
        _save_profile(_make_profile(), profiles_file, fernet_key)

        src = tmp_path / "mydir"
        src.mkdir()
        (src / "file.txt").write_text("hello")

        result = RUNNER.invoke(app, ["upload", str(src)])
        assert result.exit_code == 0, result.output
        assert "s3://" in result.output

    @mock_aws
    def test_upload_missing_dir(self, profiles_file: Path, fernet_key: bytes):
        _save_profile(_make_profile(), profiles_file, fernet_key)
        result = RUNNER.invoke(app, ["upload", "/nonexistent/path"])
        assert result.exit_code == 1

    def test_upload_no_profiles(self, tmp_path: Path):
        src = tmp_path / "mydir"
        src.mkdir()
        result = RUNNER.invoke(app, ["upload", str(src)])
        assert result.exit_code == 1

    @mock_aws
    def test_upload_unknown_profile(self, tmp_path: Path, profiles_file: Path, fernet_key: bytes):
        _save_profile(_make_profile(), profiles_file, fernet_key)
        src = tmp_path / "mydir"
        src.mkdir()
        result = RUNNER.invoke(app, ["upload", str(src), "--profile", "nonexistent"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

class TestList:
    @mock_aws
    def test_list_shows_objects(self, tmp_path: Path, profiles_file: Path, fernet_key: bytes):
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.create_bucket(Bucket=BUCKET_NAME)
        s3.put_object(Bucket=BUCKET_NAME, Key="mydir_2026-03-01T14-00-00.tar.gz", Body=b"data")
        _save_profile(_make_profile(), profiles_file, fernet_key)

        result = RUNNER.invoke(app, ["list"])
        assert result.exit_code == 0, result.output
        assert "mydir_2026-03-01T14-00-00.tar.gz" in result.output

    @mock_aws
    def test_list_empty_bucket(self, profiles_file: Path, fernet_key: bytes):
        boto3.client("s3", region_name=AWS_REGION).create_bucket(Bucket=BUCKET_NAME)
        _save_profile(_make_profile(), profiles_file, fernet_key)

        result = RUNNER.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "No snapshots" in result.output


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------

class TestDownload:
    @mock_aws
    def test_download_success(self, tmp_path: Path, profiles_file: Path, fernet_key: bytes):
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.create_bucket(Bucket=BUCKET_NAME)
        key = "mydir_2026-03-01T14-00-00.tar.gz"
        s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=b"archive contents")
        _save_profile(_make_profile(), profiles_file, fernet_key)

        out_dir = tmp_path / "output"
        out_dir.mkdir()
        result = RUNNER.invoke(app, ["download", key, "--output-dir", str(out_dir)])
        assert result.exit_code == 0, result.output
        assert (out_dir / key).exists()

    @mock_aws
    def test_download_key_not_found(self, tmp_path: Path, profiles_file: Path, fernet_key: bytes):
        boto3.client("s3", region_name=AWS_REGION).create_bucket(Bucket=BUCKET_NAME)
        _save_profile(_make_profile(), profiles_file, fernet_key)

        out_dir = tmp_path / "output"
        out_dir.mkdir()
        result = RUNNER.invoke(app, ["download", "nonexistent.tar.gz", "--output-dir", str(out_dir)])
        assert result.exit_code == 1

    def test_download_missing_output_dir(self, profiles_file: Path, fernet_key: bytes):
        _save_profile(_make_profile(), profiles_file, fernet_key)
        result = RUNNER.invoke(app, ["download", "some.tar.gz", "--output-dir", "/nonexistent/path"])
        assert result.exit_code == 1
