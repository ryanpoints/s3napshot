# Tests

## Overview

The test suite is split into two categories:

| Category | Files | Requires network? | Run by default? |
|---|---|---|---|
| Unit | `test_archive.py`, `test_config.py`, `test_cli.py` | No | Yes |
| Integration | `test_integration.py` | Yes (real S3 bucket) | No |

## Running the tests

```bash
# Unit tests only (fast, no credentials needed)
pytest tests/ -v --ignore=tests/test_integration.py

# Integration tests only (hits a real S3-compatible bucket)
pytest tests/test_integration.py -v -m integration

# Everything
pytest tests/ -v -m integration
```

---

## Credentials setup (integration tests only)

Integration tests read credentials from `tests/credentials.py`, which is gitignored and must be created locally before running them.

1. Copy the example file:

   ```bash
   cp tests/credentials.example.py tests/credentials.py
   ```

2. Fill in your values:

   ```python
   ENDPOINT = "https://s3.us-west-001.backblazeb2.com"  # bare hostname also accepted
   BUCKET   = "your-bucket-name"
   ACCESS_KEY_ID     = "your-access-key-id"
   SECRET_ACCESS_KEY = "your-secret-access-key"
   REGION   = "us-west-001"  # leave "" if your provider doesn't require it
   ```

`credentials.py` is listed in `.gitignore` and will never be committed. `credentials.example.py` is the safe placeholder that lives in version control.

---

## Test files

### `test_archive.py`

Tests `services/archive.py` — archive naming and `.tar.gz` creation. No mocking; uses `tmp_path` for real filesystem operations.

| Test | What it verifies |
|---|---|
| `test_make_archive_name_format` | Archive name follows `<hostname>_<dirname>_<YYYY-MM-DDTHH-MM-SS>.tar.gz` exactly |
| `test_make_archive_name_uses_basename` | Only the final path component of the directory is used, not the full path |
| `test_make_archive_name_default_timestamp` | Omitting `timestamp` still produces a valid, correctly suffixed name |
| `test_make_archive_name_includes_hostname` | Omitting `hostname` defaults to `socket.gethostname()` |
| `test_create_archive_round_trip` | Created archive is a valid `.tar.gz` containing all source files, including nested ones |
| `test_create_archive_progress_callback` | `progress_callback` is called once per file; byte counts sum to the total source size |
| `test_create_archive_missing_source` | Raises `FileNotFoundError` when the source path does not exist |
| `test_create_archive_not_a_directory` | Raises `NotADirectoryError` when the source path is a file |
| `test_create_archive_excludes_symlinked_dirs` | Symlinks to directories are skipped; their contents do not appear in the archive |

---

### `test_config.py`

Tests `services/config.py` — encrypted profile storage and in-memory profile management. Fernet keys are injected directly; the OS keyring is never touched.

| Test | What it verifies |
|---|---|
| `test_get_fernet_with_explicit_key` | `get_fernet(key)` returns a working `Fernet` instance that can round-trip encrypt/decrypt |
| `test_save_and_load_round_trip` | All profile fields survive a `save_profiles` → `load_profiles` cycle unchanged |
| `test_encrypted_file_does_not_contain_plaintext_secrets` | The on-disk file contains no plaintext credentials |
| `test_load_profiles_missing_file` | Returns an empty dict when the profiles file does not exist |
| `test_load_profiles_wrong_key` | Raises `ValueError` when decrypting with a different key than was used to encrypt |
| `test_add_profile_success` | `add_profile` inserts a new profile into the dict |
| `test_add_profile_duplicate_raises` | `add_profile` raises `ValueError` when the profile name already exists |
| `test_add_profile_overwrite_succeeds` | `add_profile(..., overwrite=True)` replaces an existing profile without error |
| `test_remove_profile_success` | `remove_profile` deletes the named profile from the dict |
| `test_remove_profile_unknown_raises` | `remove_profile` raises `KeyError` for a name that does not exist |
| `test_save_profiles_creates_parent_dirs` | `save_profiles` creates missing parent directories automatically |
| `test_profile_safe_display_masks_secrets` | `safe_display()` masks `secret_access_key` entirely and truncates `access_key_id` |

---

### `test_cli.py`

Tests `cli/commands.py` end-to-end using Typer's `CliRunner`. S3 calls are intercepted by [moto](https://docs.getmoto.org/) (`@mock_aws`) — no real network traffic. Config paths and the Fernet key are patched to temporary locations so the real `~/.config/s3napshot/` directory is never touched.

#### `TestProfileAdd`

| Test | What it verifies |
|---|---|
| `test_add_with_flags` | All flags accepted; profile is persisted and loadable afterward |
| `test_add_duplicate_fails` | Exit code 1 when adding a profile name that already exists |
| `test_add_with_overwrite` | `--overwrite` replaces an existing profile successfully |
| `test_add_invalid_name` | Exit code 1 for names containing spaces or special characters |
| `test_add_with_prompts` | Interactive prompts are accepted when no flags are provided |

#### `TestProfileList`

| Test | What it verifies |
|---|---|
| `test_list_empty` | Prints a friendly message when no profiles are configured |
| `test_list_masks_secrets` | Secret access key does not appear in output; masked value does |

#### `TestProfileRemove`

| Test | What it verifies |
|---|---|
| `test_remove_existing` | Removes a profile and confirms with output message |
| `test_remove_nonexistent` | Exit code 1 when the named profile does not exist |

#### `TestUpload`

| Test | What it verifies |
|---|---|
| `test_upload_success` | Archive is created, uploaded, and the `s3://` URI is printed |
| `test_upload_missing_dir` | Exit code 1 when the source directory does not exist |
| `test_upload_no_profiles` | Exit code 1 when no profiles are configured |
| `test_upload_unknown_profile` | Exit code 1 when `--profile` names a profile that doesn't exist |

#### `TestList`

| Test | What it verifies |
|---|---|
| `test_list_shows_objects` | Uploaded object keys appear in the output table |
| `test_list_empty_bucket` | Prints a friendly message when the bucket contains no objects |

#### `TestDownload`

| Test | What it verifies |
|---|---|
| `test_download_success` | File is downloaded to the output directory at the expected path |
| `test_download_key_not_found` | Exit code 1 when the key does not exist in the bucket |
| `test_download_missing_output_dir` | Exit code 1 when `--output-dir` does not exist |

---

### `test_integration.py`

Tests the full upload/list/download pipeline against a real S3-compatible bucket. All tests are marked `@pytest.mark.integration` and are excluded from the default test run.

Each test uses a unique UUID-based key under the `pytest/` prefix and cleans up after itself via an `autouse` fixture, so leftover objects in the bucket are avoided even on failure.

| Test | What it verifies |
|---|---|
| `test_upload_and_list` | Uploading an archive and then listing the bucket returns that key |
| `test_upload_progress_callback` | The progress callback receives non-zero byte counts during upload |
| `test_download_round_trip` | A file uploaded and then downloaded is non-empty and written to the expected path |
| `test_download_progress_callback` | The progress callback receives non-zero byte counts during download |
| `test_list_with_prefix_filter` | `prefix` filtering returns matching keys and excludes non-matching ones |
| `test_upload_error_bad_bucket` | Uploading to a non-existent bucket raises `UploadError` |
