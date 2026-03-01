from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from s3napshot.models.profile import Profile
from s3napshot.models.snapshot import SnapshotEntry
from s3napshot.services import archive as archive_svc
from s3napshot.services import config as config_svc
from s3napshot.services import upload as upload_svc

app = typer.Typer(help="Snapshot local directories to S3-compatible object storage.")
profile_app = typer.Typer(help="Manage named S3 profiles.")
app.add_typer(profile_app, name="profile")

console = Console()
err_console = Console(stderr=True)

_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_profile_name(name: str) -> str:
    if not _PROFILE_NAME_RE.match(name):
        err_console.print(f"[red]Invalid profile name '{name}'. Only letters, digits, hyphens, and underscores allowed.[/red]")
        raise typer.Exit(code=1)
    return name


def _load_profiles() -> tuple[dict[str, Profile], object]:
    fernet = config_svc.get_fernet()
    profiles = config_svc.load_profiles(config_svc.PROFILES_FILE, fernet)
    return profiles, fernet


def _resolve_profile(profiles: dict[str, Profile], profile_name: Optional[str]) -> Profile:
    if not profiles:
        err_console.print("[red]No profiles configured. Run 's3napshot profile add' first.[/red]")
        raise typer.Exit(code=1)

    if profile_name:
        if profile_name not in profiles:
            err_console.print(f"[red]Profile '{profile_name}' not found.[/red]")
            raise typer.Exit(code=1)
        return profiles[profile_name]

    if len(profiles) == 1:
        return next(iter(profiles.values()))

    names = list(profiles.keys())
    console.print("Available profiles:")
    for i, n in enumerate(names, 1):
        console.print(f"  {i}. {n}")
    choice = typer.prompt("Select profile (name or number)")
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(names):
            return profiles[names[idx]]
    if choice in profiles:
        return profiles[choice]
    err_console.print(f"[red]Invalid selection '{choice}'.[/red]")
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# profile add
# ---------------------------------------------------------------------------

@profile_app.command("add")
def profile_add(
    name: Annotated[Optional[str], typer.Option("--name", help="Profile name")] = None,
    endpoint: Annotated[Optional[str], typer.Option("--endpoint", help="S3 endpoint URL")] = None,
    bucket: Annotated[Optional[str], typer.Option("--bucket", help="Bucket name")] = None,
    access_key: Annotated[Optional[str], typer.Option("--access-key", help="Access key ID")] = None,
    secret_key: Annotated[Optional[str], typer.Option("--secret-key", help="Secret access key")] = None,
    region: Annotated[str, typer.Option("--region", help="Region (optional)")] = "",
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Overwrite existing profile")] = False,
) -> None:
    """Add a new S3 profile."""
    if name is None:
        name = typer.prompt("Profile name")
    _validate_profile_name(name)

    if endpoint is None:
        endpoint = typer.prompt("Endpoint URL (e.g. https://s3.amazonaws.com or Backblaze endpoint)")
    if bucket is None:
        bucket = typer.prompt("Bucket name")
    if access_key is None:
        access_key = typer.prompt("Access key ID")
    if secret_key is None:
        secret_key = typer.prompt("Secret access key", hide_input=True)

    profile = Profile(
        name=name,
        endpoint_url=endpoint,
        bucket_name=bucket,
        access_key_id=access_key,
        secret_access_key=secret_key,
        region=region,
    )

    profiles, fernet = _load_profiles()
    try:
        profiles = config_svc.add_profile(profiles, profile, overwrite=overwrite)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    config_svc.save_profiles(profiles, config_svc.PROFILES_FILE, fernet)
    console.print(f"[green]Profile '{name}' saved.[/green]")


# ---------------------------------------------------------------------------
# profile list
# ---------------------------------------------------------------------------

@profile_app.command("list")
def profile_list() -> None:
    """List all configured profiles."""
    profiles, _ = _load_profiles()
    if not profiles:
        console.print("No profiles configured.")
        return

    table = Table(title="Profiles")
    table.add_column("Name", style="cyan")
    table.add_column("Endpoint URL")
    table.add_column("Bucket")
    table.add_column("Access Key")
    table.add_column("Region")

    for p in profiles.values():
        d = p.safe_display()
        table.add_row(d["name"], d["endpoint_url"], d["bucket_name"], d["access_key_id"], d["region"])

    console.print(table)


# ---------------------------------------------------------------------------
# profile remove
# ---------------------------------------------------------------------------

@profile_app.command("remove")
def profile_remove(
    name: Annotated[str, typer.Argument(help="Profile name to remove")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Remove a profile."""
    if not yes:
        typer.confirm(f"Remove profile '{name}'?", abort=True)

    profiles, fernet = _load_profiles()
    try:
        profiles = config_svc.remove_profile(profiles, name)
    except KeyError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    config_svc.save_profiles(profiles, config_svc.PROFILES_FILE, fernet)
    console.print(f"[green]Profile '{name}' removed.[/green]")


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

@app.command("upload")
def upload(
    directory: Annotated[Path, typer.Argument(help="Local directory to snapshot")],
    profile_name: Annotated[Optional[str], typer.Option("--profile", "-p", help="Profile name")] = None,
) -> None:
    """Compress a directory and upload it to S3."""
    if not directory.exists():
        err_console.print(f"[red]Directory not found: {directory}[/red]")
        raise typer.Exit(code=1)
    if not directory.is_dir():
        err_console.print(f"[red]Path is not a directory: {directory}[/red]")
        raise typer.Exit(code=1)

    profiles, _ = _load_profiles()
    profile = _resolve_profile(profiles, profile_name)

    # Pre-scan for total bytes
    all_files = [f for f in directory.rglob("*") if f.is_file()]
    total_bytes = sum(f.stat().st_size for f in all_files)

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        # Phase 1: compress
        console.print(f"[bold]Compressing[/bold] {directory} ...")
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Compressing", total=total_bytes)

            def compress_callback(file_bytes: int) -> None:
                progress.advance(task, file_bytes)

            archive_path = archive_svc.create_archive(
                directory, tmp_dir, progress_callback=compress_callback
            )

        archive_size = archive_path.stat().st_size
        s3_key = archive_path.name

        # Phase 2: upload
        console.print(f"[bold]Uploading[/bold] {archive_path.name} ({archive_size:,} bytes) ...")
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Uploading", total=archive_size)

            def upload_callback(chunk_bytes: int) -> None:
                progress.advance(task, chunk_bytes)

            try:
                uri = upload_svc.upload_archive(
                    archive_path, s3_key, profile, progress_callback=upload_callback
                )
            except upload_svc.UploadError as exc:
                err_console.print(f"[red]Upload failed: {exc}[/red]")
                raise typer.Exit(code=1)

        console.print(f"[green]Uploaded:[/green] {uri}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@app.command("list")
def list_snapshots(
    profile_name: Annotated[Optional[str], typer.Option("--profile", "-p", help="Profile name")] = None,
    prefix: Annotated[str, typer.Option("--prefix", help="Filter by key prefix")] = "",
) -> None:
    """List snapshots in the S3 bucket."""
    profiles, _ = _load_profiles()
    profile = _resolve_profile(profiles, profile_name)

    try:
        entries = upload_svc.list_snapshots(profile, prefix=prefix)
    except upload_svc.UploadError as exc:
        err_console.print(f"[red]Failed to list snapshots: {exc}[/red]")
        raise typer.Exit(code=1)

    if not entries:
        console.print("No snapshots found.")
        return

    table = Table(title=f"Snapshots in {profile.bucket_name}")
    table.add_column("Key", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Last Modified")

    for entry in entries:
        size_str = _human_size(entry.size)
        table.add_row(entry.key, size_str, str(entry.last_modified))

    console.print(table)


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------

@app.command("download")
def download(
    key: Annotated[str, typer.Argument(help="S3 object key to download")],
    profile_name: Annotated[Optional[str], typer.Option("--profile", "-p", help="Profile name")] = None,
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Output directory")] = Path("."),
) -> None:
    """Download a snapshot from S3."""
    profiles, _ = _load_profiles()
    profile = _resolve_profile(profiles, profile_name)

    if not output_dir.exists():
        err_console.print(f"[red]Output directory not found: {output_dir}[/red]")
        raise typer.Exit(code=1)
    if not output_dir.is_dir():
        err_console.print(f"[red]Output path is not a directory: {output_dir}[/red]")
        raise typer.Exit(code=1)

    filename = Path(key).name
    dest_path = output_dir / filename

    # Get object size for progress bar
    try:
        fernet = config_svc.get_fernet()
        client = upload_svc._make_client(profile)
        head = client.head_object(Bucket=profile.bucket_name, Key=key)
        total_size = head["ContentLength"]
    except Exception:
        total_size = None

    console.print(f"[bold]Downloading[/bold] {key} ...")
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading", total=total_size)

        def dl_callback(chunk_bytes: int) -> None:
            progress.advance(task, chunk_bytes)

        try:
            result = upload_svc.download_snapshot(key, dest_path, profile, progress_callback=dl_callback)
        except upload_svc.UploadError as exc:
            err_console.print(f"[red]Download failed: {exc}[/red]")
            raise typer.Exit(code=1)

    console.print(f"[green]Downloaded to:[/green] {result}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
