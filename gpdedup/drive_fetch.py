"""Pooled, single-GET fetch of a stored ZIP entry's head from Google Drive.

The date pass needs only the first ~64 KB (EXIF/APP1) of each candidate JPEG.
Going through stdlib ``zipfile`` over an ``HttpRangeReader`` costs ~2 round-trips
per file and a fresh TCP+TLS handshake each time. Instead we:

- open each part's central directory **once** (elsewhere) to learn every
  candidate's local-header offset, then
- fetch each head with a **single** range GET starting at that offset, over a
  **pooled, keep-alive ``requests.Session``** — so handshakes amortize and the
  fetches parallelize cleanly (each is independent; no shared zip state).

We parse the 30-byte local file header to find where the entry's data starts,
then recover the head: for ``STORED`` entries the bytes are the file as-is; for
``DEFLATE`` entries (what Google Takeout actually uses) we raw-inflate just the
first ~64 KB. JPEG deflates roughly 1:1, so fetching ~64 KB of compressed input
yields ~64 KB decompressed — enough to reach the EXIF/APP1 segment at the front.
"""

from __future__ import annotations

import zlib

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .drive import media_url

HEAD = 64 * 1024
EXTRA_PAD = 4096            # cover the local extra field (usually < 100 B)
DEFLATE_MARGIN = 16 * 1024  # extra compressed input so inflate reaches HEAD bytes
_LOCAL_SIG = b"PK\x03\x04"
_STORED, _DEFLATED = 0, 8


class AuthError(Exception):
    """Fatal: token expired / no access (401, or a non-rate-limit 403)."""


class RateLimited(Exception):
    """Throttled (429 / rate-limit 403). Back off and retry."""

    def __init__(self, retry_after: float = 0.0):
        super().__init__(f"rate limited (retry_after={retry_after})")
        self.retry_after = retry_after


class TransientError(Exception):
    """Network blip / 5xx / ignored Range — retry a few times."""


def make_session(token: str, max_workers: int = 20) -> requests.Session:
    """A keep-alive Session whose connection pool matches the worker count.

    urllib3 ``Retry`` handles connection errors and 5xx (backoff honoring
    Retry-After); 429/403 are intentionally **not** retried here so the caller's
    adaptive limiter can see throttling and reduce concurrency."""
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token}"
    retry = Retry(total=4, connect=4, read=4, backoff_factor=0.5,
                  status_forcelist=(500, 502, 503, 504),
                  allowed_methods=("GET",), respect_retry_after_header=True,
                  raise_on_status=False)
    adapter = HTTPAdapter(pool_connections=max_workers,
                          pool_maxsize=max_workers, max_retries=retry)
    s.mount("https://", adapter)
    return s


def head_from_blob(blob: bytes, head: int = HEAD):
    """Recover an entry's first `head` (decompressed) bytes from a blob that
    starts at its local file header. Handles STORED (slice) and DEFLATE (raw
    inflate, bounded to `head`); returns None for other methods or a non-header
    blob. A truncated DEFLATE input is fine — inflate just stops early, and the
    EXIF/APP1 we need sits at the very front of the JPEG."""
    if len(blob) < 30 or blob[:4] != _LOCAL_SIG:
        return None
    method = int.from_bytes(blob[8:10], "little")
    name_len = int.from_bytes(blob[26:28], "little")
    extra_len = int.from_bytes(blob[28:30], "little")
    data = blob[30 + name_len + extra_len:]
    if method == _STORED:
        return data[:head]
    if method == _DEFLATED:
        try:
            return zlib.decompressobj(-zlib.MAX_WBITS).decompress(data, head)
        except zlib.error:
            return None
    return None


def _read_bounded(resp, n: int) -> bytes:
    out = bytearray()
    while len(out) < n:
        chunk = resp.raw.read(n - len(out))
        if not chunk:
            break
        out += chunk
    return bytes(out)


def _retry_after(resp) -> float:
    val = resp.headers.get("Retry-After", "")
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _is_rate_limit_403(resp) -> bool:
    body = (resp.text or "").lower()
    return any(k in body for k in ("ratelimit", "userratelimit", "quota"))


def fetch_head(session: requests.Session, file_id: str, header_offset: int,
               name_len: int, head: int = HEAD, timeout: float = 30.0):
    """Fetch one stored entry's EXIF head in a single range GET.

    Returns (head_bytes | None, bytes_downloaded). Raises AuthError (fatal),
    RateLimited (back off + retry), or TransientError (retry)."""
    blob_len = 30 + name_len + EXTRA_PAD + head + DEFLATE_MARGIN
    end = header_offset + blob_len - 1
    try:
        resp = session.get(media_url(file_id),
                           headers={"Range": f"bytes={header_offset}-{end}"},
                           timeout=timeout, stream=True)
    except requests.RequestException as exc:
        raise TransientError(str(exc)) from exc
    try:
        code = resp.status_code
        if code == 206:
            blob = _read_bounded(resp, blob_len)
            return head_from_blob(blob, head), len(blob)
        if code == 200:                       # server ignored Range — don't pull 2 GB
            raise TransientError("server ignored Range (200)")
        if code == 401:
            raise AuthError("401 Unauthorized — token expired?")
        if code == 429:
            raise RateLimited(_retry_after(resp))
        if code == 403:
            if _is_rate_limit_403(resp):
                raise RateLimited(_retry_after(resp))
            raise AuthError(f"403 Forbidden — {resp.text[:200]}")
        raise TransientError(f"unexpected status {code}")
    finally:
        resp.close()
