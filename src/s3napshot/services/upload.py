from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import boto3
import boto3.exceptions
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import BotoCoreError, ClientError

_BOTO_ERRORS = (BotoCoreError, ClientError, boto3.exceptions.S3UploadFailedError)

from s3napshot.models.profile import Profile
from s3napshot.models.snapshot import SnapshotEntry


class UploadError(Exception):
    """Wrapper for boto3/botocore exceptions."""


def _normalize_endpoint(url: str) -> str:
    if url and not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url


def _make_client(profile: Profile):
    kwargs: dict = {
        "aws_access_key_id": profile.access_key_id,
        "aws_secret_access_key": profile.secret_access_key,
    }
    if profile.endpoint_url:
        kwargs["endpoint_url"] = _normalize_endpoint(profile.endpoint_url)
    if profile.region:
        kwargs["region_name"] = profile.region
    return boto3.client("s3", **kwargs)


def upload_archive(
    archive_path: Path,
    s3_key: str,
    profile: Profile,
    *,
    progress_callback: Callable[[int], None] | None = None,
) -> str:
    client = _make_client(profile)
    config = TransferConfig(multipart_threshold=8 * 1024 * 1024)
    try:
        client.upload_file(
            str(archive_path),
            profile.bucket_name,
            s3_key,
            Config=config,
            Callback=progress_callback,
        )
    except _BOTO_ERRORS as exc:
        raise UploadError(str(exc)) from exc
    return f"s3://{profile.bucket_name}/{s3_key}"


def list_snapshots(profile: Profile, prefix: str = "") -> list[SnapshotEntry]:
    client = _make_client(profile)
    entries: list[SnapshotEntry] = []
    paginator = client.get_paginator("list_objects_v2")
    try:
        for page in paginator.paginate(Bucket=profile.bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                entries.append(
                    SnapshotEntry(
                        key=obj["Key"],
                        size=obj["Size"],
                        last_modified=obj["LastModified"],
                    )
                )
    except _BOTO_ERRORS as exc:
        raise UploadError(str(exc)) from exc
    return entries


def download_snapshot(
    key: str,
    dest_path: Path,
    profile: Profile,
    *,
    progress_callback: Callable[[int], None] | None = None,
) -> Path:
    client = _make_client(profile)
    try:
        client.download_file(
            profile.bucket_name,
            key,
            str(dest_path),
            Callback=progress_callback,
        )
    except _BOTO_ERRORS as exc:
        raise UploadError(str(exc)) from exc
    return dest_path
