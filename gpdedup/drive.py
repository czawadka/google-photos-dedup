"""Minimal Google Drive v3 client for range-reading Takeout archives.

Auth is an OAuth Bearer access token (e.g. from https://developers.google.com/oauthplayground
with the ``drive.readonly`` scope) — a clean alternative to scraped browser
cookies. The media endpoint (``files.get?alt=media``) supports HTTP Range and
returns 206, so HttpRangeReader can read each archive's central-directory tail
without downloading the file.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/drive/v3/files"

# Default query: Takeout zip parts that aren't trashed.
TAKEOUT_QUERY = "name contains 'takeout' and trashed = false"


def resolve_token(cli_value: str | None) -> str:
    """Prefer an explicit value, else the DRIVE_TOKEN env var (keeps it out of
    shell history)."""
    token = cli_value or os.environ.get("DRIVE_TOKEN")
    if not token:
        raise SystemExit(
            "No access token. Pass --token or set DRIVE_TOKEN. Get one at "
            "https://developers.google.com/oauthplayground (scope: drive.readonly)."
        )
    return token


def _get_json(url: str, token: str):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def list_files(token: str, q: str = TAKEOUT_QUERY, page_size: int = 100) -> list[dict]:
    """Return Drive file metadata dicts: id, name, size, mimeType, modifiedTime."""
    files: list[dict] = []
    page_token = None
    while True:
        params = {
            "q": q,
            "fields": "nextPageToken,files(id,name,size,mimeType,modifiedTime)",
            "pageSize": str(page_size),
            "orderBy": "name",
        }
        if page_token:
            params["pageToken"] = page_token
        data = _get_json(f"{API}?{urllib.parse.urlencode(params)}", token)
        files.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return files


def media_url(file_id: str) -> str:
    """The Range-capable download URL for a Drive file's bytes."""
    return f"{API}/{urllib.parse.quote(file_id)}?alt=media"


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
