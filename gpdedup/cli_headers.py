"""Build a request-headers dict from cURL-style CLI flags.

Accepts repeated ``-H/--header "Name: value"`` and ``-b/--cookie "k=v; k2=v2"``
flags (as collected by argparse ``action="append"``) and returns a plain dict.
Multiple ``-b`` values are joined into a single ``Cookie`` header and merged with
any ``Cookie`` supplied via ``-H``.
"""

from __future__ import annotations


def build_headers(header_args: list[str], cookie_args: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for h in header_args:
        name, sep, value = h.partition(":")
        if sep:
            headers[name.strip()] = value.strip()
    if cookie_args:
        cookie = "; ".join(c.strip() for c in cookie_args if c.strip())
        existing = headers.get("Cookie")
        headers["Cookie"] = f"{existing}; {cookie}" if existing else cookie
    return headers
