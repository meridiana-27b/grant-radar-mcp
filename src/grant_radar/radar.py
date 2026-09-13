"""Multi-source radar + watch mode: one normalized opportunity list.

`core.py` is the Questbook intelligence engine (deep: competitor applications).
This module is the *breadth* layer: it runs several funding sources, normalizes
them to one row contract, dedupes by URL, and can diff against the previous
scan so a scheduled agent reacts to new money instead of re-reading a board.

Row contract (every source produces this):
    source, url, title, usd, currency, competition, deadline (ISO or None),
    next_step, plus source-specific extras.

Design rule: a source that fails contributes a `notes` entry, never an
exception. Agents schedule this; it must degrade, not die.
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Iterable

from . import core
from .sources import github_bounties


def _qb_rows(min_usd: float) -> tuple[list[dict], list[str]]:
    rows, notes = [], []
    try:
        scan = core.scan_grants(min_reward_usd=min_usd)
    except Exception as e:  # noqa: BLE001 - source isolation
        return [], [f"questbook: {e!r}"[:160]]
    for g in list(scan.get("with_deadline") or []) + list(scan.get("no_deadline") or []):
        rw = g.get("reward") or {}
        tok = ((rw.get("token") or {}).get("label")) or "USD"
        dl = g.get("deadlineS")
        rows.append({
            "source": "questbook",
            "url": f"https://www.questbook.app/c/{((g.get('workspace') or {}).get('_id')) or ''}/{g['_id']}",
            "id": g["_id"],
            "title": (g.get("title") or "").strip()[:140],
            "usd": float(rw.get("committed") or 0),
            "currency": tok,
            "competition": g.get("numberOfApplications") or 0,
            "deadline": (datetime.datetime.fromtimestamp(float(dl), datetime.timezone.utc).date().isoformat()
                         if dl else None),
            "payout": g.get("payoutType"),
            "review": g.get("reviewType"),
            "networks": (g.get("workspace") or {}).get("supportedNetworks") or [],
            "next_step": "grant-radar detail <id>  then  grant-radar summary <id> (read what wins)",
        })
    return rows, notes


def _dd_rows(min_usd: float) -> tuple[list[dict], list[str]]:
    """Daydreams TaskMarket: public, no gate, tiny tickets - useful as filler."""
    from .http import get_json
    j = get_json("https://market.daydreams.systems/api/tasks?limit=100")
    if not isinstance(j, dict) or "tasks" not in j:
        return [], [f"daydreams: {str(j)[:120]}"]
    rows = []
    for t in j.get("tasks") or []:
        if t.get("status") != "open" or not t.get("submissionWindowOpen"):
            continue
        try:
            usd = float(t.get("reward") or 0) / 1e6
        except (TypeError, ValueError):
            usd = 0.0
        if usd < min_usd:
            continue
        rows.append({
            "source": "daydreams",
            "url": f"https://market.daydreams.systems/tasks/{t.get('referenceCode')}",
            "id": t.get("referenceCode"),
            "title": (t.get("title") or t.get("referenceCode") or "")[:140],
            "usd": round(usd, 2),
            "currency": "USD",
            "competition": t.get("submissionCount") or 0,
            "deadline": str(t.get("expiryTime") or "")[:10] or None,
            "tags": (t.get("tags") or [])[:6],
            "next_step": "submit via the task page; check stake requirement first",
        })
    return rows, []


def scan_all(min_usd: float = 100.0, sources: Iterable[str] = ("questbook", "github", "daydreams"),
             verify_github: bool = True) -> dict:
    """Run every requested source and return one deduped, ranked opportunity list."""
    sources = list(sources)
    rows: list[dict] = []
    notes: list[str] = []
    farms: list[dict] = []

    if "questbook" in sources:
        r, n = _qb_rows(max(min_usd, 500.0))  # grant tickets below $500 are noise
        rows += r
        notes += n
    if "github" in sources:
        g = github_bounties.list_bounties(min_usd=min_usd, verify=verify_github)
        rows += g.get("bounties") or []
        farms = g.get("skipped_farms") or []
        notes += [f"github/{x}" for x in (g.get("notes") or [])]
    if "daydreams" in sources:
        r, n = _dd_rows(min_usd)
        rows += r
        notes += n

    seen, uniq = set(), []
    for row in rows:
        key = row.get("url")
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(row)

    for row in uniq:
        if "score" not in row:
            row["score"] = round(row["usd"] / (1 + (row.get("competition") or 0)), 1)
    uniq.sort(key=lambda r: -r.get("score", 0))

    return {
        "scanned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "min_usd": min_usd,
        "sources": sources,
        "total": len(uniq),
        "pool_usd": round(sum(r["usd"] for r in uniq), 2),
        "opportunities": uniq,
        "skipped_farms": farms,
        "notes": [n for n in notes if n],
    }


# --- watch mode -------------------------------------------------------------

def default_state_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".grant-radar", "watch-state.json")


def watch(min_usd: float = 100.0, sources: Iterable[str] = ("questbook", "github", "daydreams"),
          state_path: str | None = None, verify_github: bool = True) -> dict:
    """Diff this scan against the previous one; report only what is NEW.

    Idempotent by URL, so an agent can run it on every heartbeat and stay quiet
    until real new money appears. State is a plain JSON file (no daemon).
    """
    state_path = state_path or default_state_path()
    prev: dict = {}
    if os.path.exists(state_path):
        try:
            prev = json.load(open(state_path, encoding="utf-8"))
        except (OSError, ValueError):
            prev = {}
    prev_urls = set((prev.get("seen") or {}).keys())

    cur = scan_all(min_usd=min_usd, sources=sources, verify_github=verify_github)
    new = [r for r in cur["opportunities"] if r["url"] not in prev_urls]

    seen = dict(prev.get("seen") or {})
    for r in cur["opportunities"]:
        seen[r["url"]] = {"first_seen": seen.get(r["url"], {}).get("first_seen", cur["scanned_at"]),
                          "usd": r["usd"], "title": r["title"][:80], "source": r["source"]}

    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"updated": cur["scanned_at"], "min_usd": min_usd, "seen": seen}, fh, indent=1)
    os.replace(tmp, state_path)

    return {"new_count": len(new), "new": new, "total_now": cur["total"],
            "tracked": len(seen), "state_path": state_path,
            "skipped_farms": cur["skipped_farms"], "notes": cur["notes"]}
