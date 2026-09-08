"""grant-radar: funding radar for AI agents on Questbook grant programs.

Core engine - public GraphQL API client with retry/backoff (the Questbook
GraphQL endpoint suffers intermittent SSL handshake timeouts), plus the three
intelligence operations:

- scan_grants():        all currently-accepting grants, split by deadline
- grant_detail(grant):  full RFP detail incl. fields / rubric / program doc link
- applications(grant):  every competitor application with state + field answers

Zero credentials, zero third-party dependencies (Python stdlib only). The
Questbook public API requires no auth for reads and exposes - unusually - the
full content of competing applications, which makes competitive analysis
possible before you write a single word.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from typing import Any

API_URL = "https://api-grants.questbook.app/graphql"

GRANTS_QUERY = """query G($first: Int, $skip: Int) {
  grants(limit: $first, skip: $skip, sort: CREATEDATS_DESC) {
    _id title summary details link acceptingApplications payoutType reviewType
    deadlineS numberOfApplications createdAtS updatedAtS
    reward { committed token { label } }
    workspace { _id title supportedNetworks safe { chainId address } }
  }
}"""

DETAIL_QUERY = """query D($g: String!) {
  grants(filter: {_operators: {_id: {in: [$g]}}}, limit: 1) {
    _id title summary details link acceptingApplications payoutType reviewType
    deadlineS startDate numberOfApplications numberOfApplicationsSelected
    totalGrantFundingDisbursedUSD createdAtS updatedAtS
    reward { committed token { label } }
    workspace { _id title supportedNetworks safe { chainId address } }
    fields { _id title inputType isPii possibleValues }
    rubric { isPrivate items { title details maximumPoints } }
  }
}"""

APPS_QUERY = """query A($g: String!, $limit: Int) {
  grants(filter: {_operators: {_id: {in: [$g]}}}, limit: 1) {
    _id title numberOfApplications
    applications(limit: $limit, sort: CREATEDATS_ASC) {
      _id state createdAtS applicantId
      milestones { _id title }
      fields { field { _id title inputType } values { _id value answer } }
    }
  }
}"""

_ID_RE = re.compile(r"^[0-9a-fA-F]{16,}")


def gql_post(query: str, variables: dict | None = None, tries: int = 5, timeout: int = 60) -> dict:
    """POST a GraphQL query with retry + linear backoff.

    Retry policy matters here: api-grants.questbook.app intermittently drops the
    TLS handshake AND occasionally answers valid queries with HTTP 400 for no
    reproducible reason (observed 2026-09-07; identical request succeeded on
    retry). Both are treated as transient and retried.
    """
    import urllib.error

    variables = variables or {}
    last: Exception | None = None
    for i in range(tries):
        try:
            body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
            req = urllib.request.Request(
                API_URL, data=body, method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:400]
            except Exception:  # noqa: BLE001
                pass
            last = RuntimeError(f"HTTP {e.code}: {detail}")
            if "GRAPHQL_VALIDATION_FAILED" in detail or "not defined by operation" in detail:
                break  # permanent client-side error: retrying cannot help
        except Exception as e:  # noqa: BLE001 - network layer, retry everything
            last = e
        if i < tries - 1:
            time.sleep(3 * (i + 1))
    raise ConnectionError(f"GraphQL request failed after {tries} attempts: {last!r}")


def _grants_page(first: int, skip: int) -> list[dict]:
    d = gql_post(GRANTS_QUERY, {"first": first, "skip": skip})
    if d.get("errors"):
        raise RuntimeError(f"GraphQL errors: {json.dumps(d['errors'])[:300]}")
    return (d.get("data") or {}).get("grants") or []


def scan_grants(min_reward_usd: float = 1000.0, max_pages: int = 7, page_size: int = 100) -> dict:
    """Scan every grant on Questbook; return the currently-accepting ones with
    reward >= min_reward_usd, split into {with_deadline (sorted by deadline), no_deadline}."""
    now = time.time()
    all_grants: list[dict] = []
    for skip in range(0, max_pages * page_size + 1, page_size):
        page = _grants_page(page_size, skip)
        all_grants.extend(page)
        if len(page) < page_size:
            break

    def reward(g: dict) -> float:
        try:
            return float((g.get("reward") or {}).get("committed"))
        except (TypeError, ValueError):
            return 0.0

    with_deadline: list[dict] = []
    no_deadline: list[dict] = []
    for g in all_grants:
        if not g.get("acceptingApplications") or reward(g) < min_reward_usd:
            continue
        dl = g.get("deadlineS") or 0
        if dl and dl <= now:
            continue  # deadline passed: treat as closed even if the flag lags behind
        (with_deadline if dl else no_deadline).append(g)

    with_deadline.sort(key=lambda g: g["deadlineS"])
    return {"scanned": len(all_grants), "now": int(now),
            "with_deadline": with_deadline, "no_deadline": no_deadline}


def grant_detail(grant_id: str) -> dict | None:
    """Full detail for one grant (RFP fields, rubric, program doc link, safe status)."""
    d = gql_post(DETAIL_QUERY, {"g": grant_id})
    if d.get("errors"):
        raise RuntimeError(f"GraphQL errors: {json.dumps(d['errors'])[:300]}")
    grants = (d.get("data") or {}).get("grants") or []
    return grants[0] if grants else None


def _field_key(value_id: str) -> str | None:
    """Recover the real field key from a value id.

    Server quirk: every `field` reference in saved answers points at the same
    (wrong) id, but each VALUE id starts with `<applicationId>` (24-hex),
    followed by the real key and trailing numeric segments that vary between
    applications (`<appId>.<key>[.<idx>][.<version>]`). So: strip the appId,
    drop purely-numeric tail segments, keep the rest.
    """
    parts = value_id.split(".")
    if len(parts) < 2 or not re.fullmatch(r"[0-9a-fA-F]{24}", parts[0]):
        return None
    rest = list(parts[1:])
    while rest and re.fullmatch(r"\d+", rest[-1]):
        rest.pop()
    return ".".join(rest) if rest else None


def _answer_text(value: dict) -> str:
    """Pick the human-readable text out of {value, answer} (one holds an id)."""
    for k in ("value", "answer"):
        t = value.get(k)
        if t and not _ID_RE.match(str(t)):
            return str(t)
    return ""


def applications(grant_id: str, limit: int = 50) -> list[dict]:
    """All competitor applications for a grant, normalized.

    Each entry: {_id, state, createdAtS, applicantId, milestones:[title], fields:{key: text}}.
    The `state` field is the strategic gold: it tells you which competitors were
    approved/selected and what their accepted proposals looked like.
    """
    d = gql_post(APPS_QUERY, {"g": grant_id, "limit": limit})
    if d.get("errors"):
        raise RuntimeError(f"GraphQL errors: {json.dumps(d['errors'])[:300]}")
    g = ((d.get("data") or {}).get("grants") or [{}])[0]
    out = []
    for a in (g.get("applications") or []):
        fields: dict[str, str] = {}
        for f in a.get("fields") or []:
            for v in f.get("values") or []:
                key = _field_key(str(v.get("_id", "")))
                if key:
                    txt = _answer_text(v)
                    if txt:
                        fields[key] = (fields.get(key, "") + " | " + txt).strip(" |")
        out.append({
            "_id": a.get("_id"),
            "state": a.get("state"),
            "createdAtS": a.get("createdAtS"),
            "applicantId": a.get("applicantId"),
            "milestones": [m.get("title") for m in (a.get("milestones") or [])],
            "fields": fields,
        })
    return out


def competitive_summary(grant_id: str, limit: int = 50) -> dict:
    """Group applications by state with key fields - the 'what wins' view."""
    apps = applications(grant_id, limit=limit)
    from collections import Counter
    states = Counter(a["state"] for a in apps)
    grouped: dict[str, list[dict]] = {}
    for st in ("selected", "approved", "in_review", "submitted"):
        grp = [a for a in apps if a.get("state") == st]
        if grp:
            grouped[st] = [{
                "projectName": (a["fields"].get("projectName") or "")[:120],
                "tldr": (a["fields"].get("tldr") or "")[:300],
                "fundingAsk": (a["fields"].get("fundingAsk") or "")[:250],
                "milestones": [m[:80] for m in a["milestones"] if m],
            } for a in grp]
    return {"grantId": grant_id, "states": dict(states), "grouped": grouped}