# s3napshot

Snapshot local directories to S3-compatible object storage. Compresses a directory into a `.tar.gz` archive and uploads it to Amazon S3, Backblaze B2, or any other S3-compatible service.

Archives are named `<hostname>_<dirname>_<YYYY-MM-DDTHH-MM-SS>.tar.gz` so snapshots from different machines are always distinguishable.

## Installation

```bash
pipx install git+https://github.com/ryanpoints/s3napshot.git
```

Or clone and install locally:

```bash
git clone https://github.com/ryanpoints/s3napshot.git
cd s3napshot
pipx install .
```

For development:

```bash
git clone https://github.com/ryanpoints/s3napshot.git
cd s3napshot
pip install -e .
```

## Quick start

```bash
# Add a profile
s3napshot profile add

# Snapshot a directory
s3napshot upload ./my-project

# List snapshots in the bucket
s3napshot list

# Download a snapshot
s3napshot download Hostname_my-project_2026-03-01T14-32-00.tar.gz
```

## Profiles

Credentials are stored AES-encrypted at `~/.config/s3napshot/profiles.enc`. The encryption key is kept in the OS keyring where available, with a fallback to `~/.config/s3napshot/.key` (mode `0600`) on headless systems.

### Add a profile

Interactively:

```bash
s3napshot profile add
```

With flags (useful for scripting):

```bash
s3napshot profile add \
  --name        b2 \
  --endpoint    s3.us-west-001.backblazeb2.com \
  --bucket      my-bucket \
  --access-key  KEYID \
  --secret-key  SECRETKEY \
  --region      us-west-001
```

`--endpoint` accepts both bare hostnames (`s3.us-west-001.backblazeb2.com`) and full URLs (`https://...`). `--region` is optional and can be omitted for providers that don't require it.

Overwrite an existing profile:

```bash
s3napshot profile add --name b2 --overwrite ...
```

### List profiles

```bash
s3napshot profile list
```

Secret keys are always masked in output.

### Remove a profile

```bash
s3napshot profile remove b2
s3napshot profile remove b2 --yes   # skip confirmation
```

## Commands

### `upload`

Compresses a directory and uploads it as a single `.tar.gz` archive. Shows separate progress bars for compression and upload.

```bash
s3napshot upload <directory> [--profile <name>]
```

If only one profile is configured it is selected automatically. With multiple profiles and no `--profile` flag, you will be prompted to choose.

### `list`

Lists all snapshots in the bucket as a table with key, size, and last-modified date.

```bash
s3napshot list [--profile <name>] [--prefix <prefix>]
```

Use `--prefix` to filter by a common key prefix, e.g. `--prefix hostname_` to show only snapshots from a specific host.

### `download`

Downloads a snapshot by its S3 key.

```bash
s3napshot download <key> [--profile <name>] [--output-dir <path>]
```

`--output-dir` defaults to the current directory. Shows a progress bar with transfer speed.

## Providers

Any S3-compatible service works. Tested with:

| Provider | Endpoint format |
|---|---|
| Amazon S3 | *(leave endpoint blank)* |
| Backblaze B2 | `s3.<region>.backblazeb2.com` |

## Development

```bash
pip install -e .
pip install pytest pytest-cov "moto[s3]>=5" boto3-stubs

# Unit tests (no network required)
pytest tests/ -v --ignore=tests/test_integration.py

# Integration tests (hits real bucket)
pytest tests/test_integration.py -v -m integration
```
