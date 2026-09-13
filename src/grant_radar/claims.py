"""Claimability: 'real repo' and 'paid on merge' are not the same as 'I can win this'.

A bounty board tells you the headline number. It does not tell you that the
deadline was in the issue body three weeks ago, that six people already commented
"taking this", that the fix needs a $3,000 accelerator you do not own, or that the
repo's CONTRIBUTING.md refuses AI-generated pull requests. An agent that optimises
the radar score without these four facts spends hours for zero payout.

This module computes a per-issue `claimable` verdict from public data only:

    expired      deadline in the past (often only in the free-text body)
    blocked      needs material prerequisites this machine cannot provide
    contested    other workers already engaged on the thread
    needs-human  the claim flow lives off-GitHub (Discord/Slack/DM)
    risky        repo policy explicitly hostile to AI-generated contributions
    open         none of the above

Live evidence (2026-09-13, first run over the credible GitHub pool): 7 of 7
bounties that passed the repo credibility screen came back NOT claimable - one
blocked on Tenstorrent hardware plus an AI-contribution policy, one expired, five
contested. The credibility screen alone was not enough, which is why this exists.
"""
from __future__ import annotations

import base64
import datetime
import re

from .http import get_json

API = "https://api.github.com"

# Deadlines are usually prose, not labels: "Deadline Sep 7", "due 2026-02-08".
_DL = re.compile(
    r"(?:deadline|due|ends?|close[sd]? by)[^\n]{0,16}?"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}"
    r"|\d{4}-\d{2}-\d{2})", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

# In-thread signals that somebody else already took the work.
_TAKING = re.compile(r"\bi'?m (?:working|on) (?:this|it)\b|\btaking this\b|\balready (?:claimed|working)\b",
                     re.I)

# Material prerequisites an agent on a laptop cannot satisfy. Keys are matched
# lowercased against issue text; keep them specific enough to avoid false hits.
PREREQS = {
    "wormhole": "requires Tenstorrent Wormhole hardware",
    "blackhole": "requires Tenstorrent Blackhole hardware",
    "t3k": "requires a Tenstorrent T3K cluster",
    "n150": "requires a Tenstorrent accelerator",
    "p150b": "requires a Tenstorrent accelerator",
    " on gpu": "requires a GPU",
    "on a gpu": "requires a GPU",
    "cuda": "requires an NVIDIA GPU",
    "multiple mac": "requires several Mac machines",
    "ios device": "requires a physical iOS device",
    "android device": "requires a physical Android device",
}

# Content the repo owner controls, checked for hostility to agent contributions.
_POLICY_FILES = ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "AGENTS.md",
                 "README.md", ".github/PULL_REQUEST_TEMPLATE.md")
# 'llm'/'gpt' are weak signals (often just project vocabulary) -> they mark
# 'risky' for a human read, they never auto-reject.
_AI_HARD = ("ai-generated", "ai generated", "no ai", "no ai-generated", "automated contrib",
            "human-only", "bot contributions", "no bots", "bots will")
_AI_SOFT = ("llm", "gpt", "chatgpt", "claude")

_OFFPLATFORM = ("discord.com/", "discord.gg/", "slack.com/", "dm me", "dms open")


def parse_deadline(text: str) -> str | None:
    """First ISO date implied by prose in the issue title/body, or None."""
    m = _DL.search(text or "")
    if not m:
        return None
    s = m.group(1).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    mm = re.match(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2})", s, re.I)
    if not mm:
        return None
    month = _MONTHS.get(mm.group(1).lower())
    if not month:
        return None
    day = int(mm.group(2))
    year = datetime.date.today().year
    iso = f"{year}-{month:02d}-{day:02d}"
    # a bare "Sep 30" that is already behind us almost certainly meant next year
    if iso < datetime.date.today().isoformat():
        pass  # keep as-is: an expired deadline is the conservative reading
    return iso


def _policy_hits(repo: str, token: str | None) -> dict:
    hard: list[str] = []
    soft: list[str] = []
    for fname in _POLICY_FILES:
        c = get_json(f"{API}/repos/{repo}/contents/{fname}",
                     {"Authorization": f"Bearer {token}"} if token else {},
                     tries=1, max_bytes=400_000)
        if not (isinstance(c, dict) and c.get("content")):
            continue
        try:
            txt = base64.b64decode(c["content"]).decode("utf-8", "replace").lower()
        except (ValueError, TypeError):
            continue
        h = [p for p in _AI_HARD if p in txt]
        s = [p for p in _AI_SOFT if p in txt]
        if h:
            hard.append(f"{fname}: {','.join(h[:3])}")
        if s:
            soft.append(f"{fname}: {','.join(s[:3])}")
    return {"hard": hard, "soft": soft}


def claim_check(repo: str, issue_number: int, token: str | None = None,
                today: str | None = None, check_policy: bool = True) -> dict:
    """Per-issue claimability verdict. Never raises; degrades to 'unknown'."""
    today = today or datetime.date.today().isoformat()
    auth = {"Authorization": f"Bearer {token}"} if token else {}
    iss = get_json(f"{API}/repos/{repo}/issues/{issue_number}", auth)
    if not isinstance(iss, dict) or iss.get("_error") or iss.get("message"):
        return {"repo": repo, "issue": issue_number, "claimable": "unknown",
                "reasons": ["issue unreadable"]}

    title = iss.get("title") or ""
    body = iss.get("body") or ""
    text = title + "\n" + body
    low = text.lower()

    reasons: list[str] = []
    verdict = "open"

    dl = parse_deadline(text)
    if dl and dl < today:
        verdict = "expired"
        reasons.append(f"deadline {dl} already passed")

    blocked = sorted({why for key, why in PREREQS.items() if key in low})
    if blocked and verdict != "expired":
        verdict = "blocked"
        reasons.append(blocked[0])
    elif blocked:
        reasons.append(blocked[0])

    if iss.get("state") != "open":
        verdict = "closed"
        reasons.append(f"issue state={iss.get('state')}")

    # comments: has anybody else taken it, and have maintainers engaged?
    cm = get_json(f"{API}/repos/{repo}/issues/{issue_number}/comments"
                  f"?per_page=100&sort=updated", auth)
    n_comments = len(cm) if isinstance(cm, list) else 0
    maintainer_spoke = bool(isinstance(cm, list) and
                            any(c.get("author_association") in ("OWNER", "MEMBER", "COLLABORATOR")
                                for c in cm))
    thread_claimed = bool(isinstance(cm, list) and
                          any(_TAKING.search(c.get("body") or "") for c in cm))

    if verdict == "open":
        if thread_claimed:
            verdict = "contested"
            reasons.append("someone states they are working on it")
        elif n_comments >= 8:
            verdict = "contested"
            reasons.append(f"{n_comments} comments already on the thread")

    off = [p for p in _OFFPLATFORM if p in low]
    if off and verdict == "open":
        verdict = "needs-human"
        reasons.append("claim flow is off-GitHub (" + off[0] + ")")
    elif off:
        reasons.append("claim flow is off-GitHub (" + off[0] + ")")

    policy = _policy_hits(repo, token) if check_policy else {"hard": [], "soft": []}
    if policy["hard"] and verdict == "open":
        verdict = "risky"
        reasons.append("repo policy restricts AI-generated contributions: " + policy["hard"][0])
    elif policy["hard"]:
        reasons.append("AI-contribution policy: " + policy["hard"][0])

    return {
        "repo": repo, "issue": issue_number, "url": iss.get("html_url"),
        "title": title[:140], "state": iss.get("state"),
        "deadline": dl, "comments": n_comments,
        "maintainer_engaged": maintainer_spoke,
        "ai_policy_hard": policy["hard"], "ai_policy_soft": policy["soft"][:3],
        "claimable": verdict,
        "reasons": reasons or ["no blocker found"],
    }


def annotate(bounties: list[dict], token: str | None = None,
             limit: int = 10, check_policy: bool = True) -> list[dict]:
    """Add `claimable` + `reasons` to GitHub bounty rows (in place, best effort)."""
    import urllib.parse

    tok = token
    for row in bounties[:limit]:
        slug = row.get("repo") or ""
        num = row.get("issue")
        if not num and row.get("url"):
            tail = urllib.parse.urlparse(row["url"]).path.rsplit("/", 1)[-1]
            num = int(tail) if tail.isdigit() else None
        if not slug or not num:
            row["claimable"] = "unknown"
            continue
        r = claim_check(slug, int(num), token=tok, check_policy=check_policy)
        row["claimable"] = r["claimable"]
        row["claim_reasons"] = r["reasons"]
        row["deadline"] = row.get("deadline") or r.get("deadline")
    return bounties
