"""Storage path helpers for local development and Vercel.

The bundled SQLite and TinyMongo JSON files remain the seed data. Vercel's
application filesystem is read-only, so on Vercel we copy those files to /tmp
and run the app against the writable copies. This preserves the existing DB
and JSON format without requiring a database migration.

Important: /tmp is ephemeral on Vercel. It is suitable for making the existing
file-backed app run without filesystem errors, but it is not durable shared
storage between function instances. For durable multi-user writes, a remote
persistent database/storage service is eventually required.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SOURCE_DB_PATH = BASE_DIR / "tradeverse.db"
SOURCE_TINYDB_DIR = BASE_DIR / "tinydb_storage"

IS_VERCEL = (
    os.getenv("VERCEL", "").lower() in ("1", "true")
    or bool(os.getenv("VERCEL_ENV"))
    or bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
    or bool(os.getenv("LAMBDA_TASK_ROOT"))
    or "/var/task" in str(BASE_DIR)
)

# Allow a custom writable directory for other hosts. Locally the original
# files are used directly so the existing development behavior is unchanged.
_configured_dir = os.getenv("TRADEVERSE_RUNTIME_DATA_DIR", "").strip()
if _configured_dir:
    RUNTIME_DIR = Path(_configured_dir).expanduser().resolve()
elif IS_VERCEL:
    RUNTIME_DIR = Path("/tmp/tradeverse")
else:
    RUNTIME_DIR = BASE_DIR


def _copy_seed_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)


def prepare_storage() -> tuple[Path, Path]:
    """Return writable SQLite and TinyMongo paths, creating Vercel copies."""
    if RUNTIME_DIR == BASE_DIR:
        return SOURCE_DB_PATH, SOURCE_TINYDB_DIR

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    runtime_db = RUNTIME_DIR / "tradeverse.db"
    if SOURCE_DB_PATH.exists():
        _copy_seed_file(SOURCE_DB_PATH, runtime_db)

    runtime_tinydb = RUNTIME_DIR / "tinydb_storage"
    runtime_tinydb.mkdir(parents=True, exist_ok=True)

    # Copy the database JSON, but not the old TinyMongo lock file. The lock is
    # runtime state and must be created by the current process/environment.
    source_json = SOURCE_TINYDB_DIR / "tradeverse.json"
    runtime_json = runtime_tinydb / "tradeverse.json"
    if source_json.exists():
        _copy_seed_file(source_json, runtime_json)

    return runtime_db, runtime_tinydb
