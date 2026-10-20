"""
cloud_sync.py
-------------
Automatic persistence layer for Vercel Serverless deployments using Vercel Blob.
Because Vercel Lambda containers have ephemeral filesystems (/tmp is wiped on restart),
this module automatically syncs SQLite (tradeverse.db) and TinyDB (tradeverse.json)
to and from the project's persistent Vercel Blob storage.

When running locally without BLOB_READ_WRITE_TOKEN, all operations gracefully no-op
and use local disk directly.
"""

from __future__ import annotations

import os
import time
import requests
from pathlib import Path
from storage_paths import RUNTIME_DIR, SOURCE_DB_PATH, SOURCE_TINYDB_DIR

BLOB_API_BASE = "https://blob.vercel-storage.com"
_last_download_time = 0.0


def get_blob_token() -> str:
    return os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()


def is_cloud_enabled() -> bool:
    return bool(get_blob_token())


def download_from_cloud(force: bool = False) -> bool:
    """Downloads tradeverse.db and tradeverse.json from Vercel Blob into RUNTIME_DIR if available."""
    global _last_download_time
    token = get_blob_token()
    if not token:
        return False

    # Debounce downloads within 5 seconds unless forced
    now = time.time()
    if not force and (now - _last_download_time < 5.0):
        return False

    headers = {"authorization": f"Bearer {token}"}
    try:
        resp = requests.get(BLOB_API_BASE, headers=headers, timeout=5)
        if resp.status_code != 200:
            print(f"[CLOUD SYNC] List blobs failed ({resp.status_code}): {resp.text[:100]}")
            return False

        blobs = resp.json().get("blobs", [])
        blob_map = {b.get("pathname"): b.get("url") for b in blobs if b.get("pathname")}

        downloaded_any = False

        # 1. Sync SQLite DB
        db_url = blob_map.get("tradeverse.db")
        if db_url:
            r_db = requests.get(db_url, headers=headers, timeout=5)
            if r_db.status_code == 200 and len(r_db.content) > 1000:
                target_db = RUNTIME_DIR / "tradeverse.db"
                target_db.parent.mkdir(parents=True, exist_ok=True)
                with open(target_db, "wb") as f:
                    f.write(r_db.content)
                downloaded_any = True
                print(f"[CLOUD SYNC] Successfully restored tradeverse.db ({len(r_db.content)} bytes) from Vercel Blob")

        # 2. Sync TinyDB JSON
        json_url = blob_map.get("tradeverse.json")
        if json_url:
            r_json = requests.get(json_url, headers=headers, timeout=5)
            if r_json.status_code == 200 and len(r_json.content) > 10:
                target_json = RUNTIME_DIR / "tinydb_storage" / "tradeverse.json"
                target_json.parent.mkdir(parents=True, exist_ok=True)
                with open(target_json, "wb") as f:
                    f.write(r_json.content)
                downloaded_any = True
                print(f"[CLOUD SYNC] Successfully restored tradeverse.json ({len(r_json.content)} bytes) from Vercel Blob")

        _last_download_time = time.time()
        return downloaded_any
    except Exception as e:
        print(f"[CLOUD SYNC] Warning: Failed to download from Vercel Blob: {e}")
        return False


def upload_to_cloud(files: list[str] | None = None) -> bool:
    """Uploads specified files (or all DB files) to Vercel Blob for durable multi-instance persistence."""
    token = get_blob_token()
    if not token:
        return False

    if files is None:
        files = ["tradeverse.db", "tradeverse.json"]

    headers = {
        "authorization": f"Bearer {token}",
        "x-vercel-blob-access": "private",
        "x-allow-overwrite": "true",
        "x-add-random-suffix": "false",
    }

    success = True
    for fname in files:
        if fname == "tradeverse.db":
            path = RUNTIME_DIR / "tradeverse.db"
        elif fname == "tradeverse.json":
            path = RUNTIME_DIR / "tinydb_storage" / "tradeverse.json"
        else:
            path = Path(fname)

        if not path.exists():
            continue

        try:
            with open(path, "rb") as f:
                data = f.read()

            upload_url = f"{BLOB_API_BASE}/{fname}"
            resp = requests.put(upload_url, headers=headers, data=data, timeout=8)
            if resp.status_code in (200, 201):
                print(f"[CLOUD SYNC] Uploaded {fname} ({len(data)} bytes) to Vercel Blob successfully")
            else:
                print(f"[CLOUD SYNC] Failed to upload {fname} ({resp.status_code}): {resp.text[:150]}")
                success = False
        except Exception as e:
            print(f"[CLOUD SYNC] Error uploading {fname} to Vercel Blob: {e}")
            success = False

    return success
