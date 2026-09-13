"""Shared stdlib HTTP helper for the source adapters (no third-party deps).

Adapters need plain JSON GET with retry + backoff and optional bearer auth.
Retry is not decoration: several funding endpoints (Questbook GraphQL, the
GitHub search API, Superteam) intermittently drop TLS handshakes or answer a
valid request with a 5xx, and recover on the next attempt.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "grant-radar/0.2 (open-source funding radar for AI agents)"


def bearer_from(env_var: str, path_env: str, default_path: str = "") -> str | None:
    """Bearer token from an env var, else from a JSON/key file pointed at by env.

    Never logs or echoes the value. Returns None when unauthenticated, which
    every adapter treats as "use the public endpoint / lower rate limit".
    """
    tok = (os.environ.get(env_var) or "").strip()
    if tok:
        return tok
    path = (os.environ.get(path_env) or default_path).strip()
    if not path or not os.path.exists(path):
        return None
    try:
        raw = open(path, encoding="utf-8-sig").read().strip()
    except OSError:
        return None
    if raw.startswith("{"):
        try:
            j = json.loads(raw)
            for k in ("apiKey", "api_key", "token", "key"):
                if isinstance(j.get(k), str) and j[k].strip():
                    return j[k].strip()
        except ValueError:
            return None
        return None
    return raw or None


def get_json(url: str, headers: dict | None = None, tries: int = 4,
             timeout: int = 30, max_bytes: int = 2_000_000) -> dict | list:
    """GET and parse JSON with linear backoff. Returns {"_error": "..."} on failure."""
    hdr = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        hdr.update(headers)
    last: Exception | None = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            resp = urllib.request.urlopen(req, timeout=timeout)
            try:
                raw = resp.read(max_bytes)
            finally:
                resp.close()
            return json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = e
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            if e.code in (403, 429) and "rate limit" in body.lower() and i < tries - 1:
                # secondary rate limit: waiting is the only correct response
                time.sleep(12 * (i + 1))
                continue
            if e.code in (401, 403, 404):
                break  # auth/permission/not-found: retrying cannot help
        except Exception as e:  # noqa: BLE001 - network layer
            last = e
        if i < tries - 1:
            time.sleep(2 * (i + 1))
    return {"_error": f"{type(last).__name__}: {last}"[:200]}


def q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def money(raw) -> float:
    """Best-effort numeric coercion for reward fields that arrive as str/int/None."""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0
