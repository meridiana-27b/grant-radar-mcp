"""Clustly hosted entry for grant-radar.

Contract (clustly.ai/llms.txt): the platform shim imports this module and calls
the module-level `handler(job)` once per job. `job["input"]` is ALWAYS
{criteria, inputs}. The return value IS the deliverable (markdown). To fail, we
raise — never return an {error} dict.

Two modes:
  analyze — competitive intel for one grant id (id from inputs, else parsed out
            of the buyer's brief): RFP essentials + every competitor application
            grouped by state, approved ones first.
  scan    — every currently-accepting Questbook grant over a reward floor.

Zero credentials: the Questbook public GraphQL API needs no auth. Core is
stdlib-only, imported from ./src (bundled).
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from grant_radar import core  # noqa: E402

_HEX24 = re.compile(r"\b[0-9a-fA-F]{24}\b")


def _fmt_usd(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "?"


def _deadline(ts) -> str:
    if not ts:
        return "no deadline"
    import datetime
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d")


def _render_scan(res: dict, min_reward: float) -> str:
    wd, nd = res["with_deadline"], res["no_deadline"]
    lines = [
        "# Grant radar — live scan",
        "",
        f"Scanned **{res['scanned']}** grants on Questbook; "
        f"**{len(wd) + len(nd)}** accepting with reward >= {_fmt_usd(min_reward)}.",
        "",
    ]
    for title, group in (("Closing soon (deadline)", wd), ("Open-ended (no deadline)", nd)):
        if not group:
            continue
        lines.append(f"## {title}")
        lines.append("")
        for g in group:
            reward = (g.get("reward") or {})
            tok = ((reward.get("token") or {}).get("label")) or "?"
            ws = (g.get("workspace") or {}).get("title") or "?"
            lines.append(
                f"- **{g.get('title')}** — {_fmt_usd(reward.get('committed'))} {tok} · "
                f"{ws} · {_deadline(g.get('deadlineS'))} · "
                f"{g.get('numberOfApplications', 0)} application(s) · id `{g.get('_id')}`"
            )
            summary = (g.get("summary") or "").strip()
            if summary:
                lines.append(f"  - {summary[:220]}")
        lines.append("")
    if not wd and not nd:
        lines.append("_Nothing accepting at this reward floor right now._")
    lines.append("")
    lines.append("_Source: Questbook public API (api-grants.questbook.app), read-only, fetched at job time._")
    return "\n".join(lines)


def _render_analyze(detail: dict | None, summary: dict, grant_id: str) -> str:
    lines = [f"# Competitive brief — grant `{grant_id}`", ""]
    if detail:
        reward = (detail.get("reward") or {})
        tok = ((reward.get("token") or {}).get("label")) or "?"
        lines += [
            f"**{detail.get('title')}** — {_fmt_usd(reward.get('committed'))} {tok} · "
            f"{(detail.get('workspace') or {}).get('title') or '?'} · "
            f"{'accepting applications' if detail.get('acceptingApplications') else 'NOT accepting'} · "
            f"{detail.get('numberOfApplications', 0)} application(s)",
            "",
        ]
        details_txt = (detail.get("details") or "").strip()
        if details_txt:
            lines += ["## RFP (excerpt)", "", details_txt[:1500], ""]
    lines.append("## Applications by state")
    states = summary.get("states") or {}
    if not states:
        lines.append("")
        lines.append("_No applications visible for this grant id (check the id)._")
    grouped = summary.get("grouped") or {}
    for st in ("selected", "approved", "in_review", "submitted"):
        grp = grouped.get(st)
        if not grp:
            continue
        lines += ["", f"### {st} ({states.get(st, len(grp))})", ""]
        for a in grp[:15]:
            ask = a.get("fundingAsk") or "ask: n/a"
            lines.append(f"- **{a.get('projectName') or '(unnamed)'}** — {ask[:160]}")
            if a.get("tldr"):
                lines.append(f"  - {a['tldr'][:280]}")
            for m in (a.get("milestones") or [])[:4]:
                lines.append(f"  - milestone: {m}")
    lines += ["", "_How to win: read the approved entries (if any) and position your proposal "
              "against their actual wording — this data is public but rarely read._"]
    return "\n".join(lines)


def handler(job):
    inp = (job or {}).get("input") or {}
    criteria = (inp.get("criteria") or "").strip()
    inputs = inp.get("inputs") or {}

    mode = (inputs.get("mode") or "").strip().lower()
    if mode not in ("analyze", "scan"):
        # infer from the brief: a 24-hex grant id anywhere -> analyze, else scan
        mode = "analyze" if _HEX24.search(criteria) else "scan"

    if mode == "scan":
        floor = 1000.0
        res = core.scan_grants(min_reward_usd=floor)
        return _render_scan(res, floor)

    grant_id = (inputs.get("grant_id") or "").strip()
    if not grant_id:
        m = _HEX24.search(criteria)
        if m:
            grant_id = m.group(0)
    if not grant_id:
        raise ValueError(
            "analyze mode needs a grant id. Paste the 24-char grant id from "
            "questbook.app into the brief (or the Grant id field).")

    detail = core.grant_detail(grant_id)
    summary = core.competitive_summary(grant_id)
    if detail is None and not (summary.get("states") or {}):
        raise ValueError(f"no grant found for id {grant_id!r} on Questbook")
    return _render_analyze(detail, summary, grant_id)
