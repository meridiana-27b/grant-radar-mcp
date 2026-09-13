"""GitHub bounty source - open issues labelled/worded as paid bounties.

This is the source that separates a working funding pipeline from a naive one.
GitHub bounty issues are the largest *unmediated* pool an agent can work: no
grant committee, payout on merge. They are also the most-faked. Live scan
2026-09-13: 269 open bounty issues >= $100 across 28 repos, of which the two
biggest pools by headline value were both scams:

  ClankerNation/OpenAgents          $104,000 headline, 23 issues
    -> 1 contributor, 0 PRs ever merged, repo created 2026-05,
       plus an issue titled "WARNING to AI Agents: Bounties are symbolic"
  zhangjiayang6835-cyber/bounty-plaza $18,000 headline, 10 issues
    -> 1 contributor, 0 PRs merged, 202 closed issues titled "[Bounty] [Bounty] ..."

Meanwhile the credible pool (tenstorrent/tt-metal: $52k across 6 issues, 24,599
merged PRs, 100+ contributors, org-owned, pushed the same day) sits lower on a
list sorted by headline value. A reward-sorted agent walks straight into the
farms first. So this adapter scores the *repo* before ranking the *issue*.

Credibility signals used (all public, no auth needed, auth raises rate limits):
  merged PR count, contributor count, stars, repo age, org vs user owner,
  issue count vs merged-PR ratio, bounty issues closed (evidence of payout flow).
"""
from __future__ import annotations

import datetime
import re

from ..http import bearer_from, get_json, money, q

API = "https://api.github.com"

# GitHub search queries that find real paid bounties. The 💎 Bounty label is the
# Algora convention (the dominant bounty router in OSS); `label:bounty` catches
# native programs; `bounty in:title` catches programs with custom labelling.
QUERIES = (
    ('label:"💎 Bounty" state:open type:issue', "algora"),
    ("label:bounty state:open type:issue", "label"),
    ("bounty in:title state:open type:issue", "title"),
)

_AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([km]?)", re.I)
# "$3 paid", "reward: 100 RTC (~$10 ...)" - we only ever take the first $ figure
# and sanity-cap it, so typos like "$1000000000" cannot dominate a ranking.
MAX_USD = 5_000_000


def extract_usd(text: str) -> float:
    """First dollar amount in a title/label/body, magnitude-capped. 0 if none.

    Suffixes k/m are honoured ("$5k", "$35m"), commas stripped. Returns 0 for
    text without a $ figure so callers can fall through title -> label -> body.
    """
    if not text:
        return 0.0
    m = _AMOUNT.search(text)
    if not m:
        return 0.0
    v = money(m.group(1).replace(",", ""))
    suf = (m.group(2) or "").lower()
    if suf == "k":
        v *= 1_000
    elif suf == "m":
        v *= 1_000_000
    return v if 0 < v <= MAX_USD else 0.0


def issue_usd(item: dict) -> tuple[float, str]:
    """Reward for one issue, preferring the least-embellished source."""
    for lab in (item.get("labels") or []):
        v = extract_usd(lab.get("name") or "")
        if v:
            return v, "label"
    v = extract_usd(item.get("title") or "")
    if v:
        return v, "title"
    v = extract_usd((item.get("body") or "")[:800])
    return (v, "body") if v else (0.0, "-")


# --- repo credibility -------------------------------------------------------

# Self-declared scam language, matched as a LITERAL substring only, and only in
# content the repo owner controls or in bounty issue titles. Do NOT send these to
# the GitHub search API: it tokenises multi-word queries into OR'd terms, so
# "bounty is not real" matches every issue containing the word "bounty" - which
# wrongly flagged tenstorrent/tt-metal (24,599 merged PRs) and tinygrad on
# 2026-09-13. Literal matching is both cheaper and correct.
_SCAM_PATTERNS = (
    "bounties are symbolic",
    "bounties are not real",
    "bounty is symbolic",
    "no real payments",
    "not financially able to pay",
    "simulated bount",
    "fake bount",
)
_OWNER_FILES = ("README.md", "CONTRIBUTING.md", "BOUNTY.md", "bounties.md", "BOUNTIES.md")


def _scam_signals(repo: str, token: str | None, titles: list[str]) -> dict:
    """Literal scam-language check: owner-controlled files + bounty issue titles."""
    import base64

    hits: list[str] = []
    for fname in _OWNER_FILES:
        # NB: do NOT url-encode `owner/repo` into the path - GitHub REST 404s on
        # `owner%2Frepo`. Repo slugs from the API are already URL-safe.
        meta = get_json(f"{API}/repos/{repo}/contents/{fname}", _auth(token), tries=1, max_bytes=400_000)
        if isinstance(meta, dict) and meta.get("content"):
            try:
                txt = base64.b64decode(meta["content"]).decode("utf-8", "replace").lower()
            except (ValueError, TypeError):
                continue
            for p in _SCAM_PATTERNS:
                if p in txt:
                    hits.append(f"{fname}: {p}")
    for t in titles:
        low = (t or "").lower()
        for p in _SCAM_PATTERNS:
            if p in low:
                hits.append(f"issue title: {p}")
    return {"count": len(hits), "evidence": hits[:4]}


def repo_health(repo: str, token: str | None = None, check_scam: bool = True,
                sample_titles: list[str] | None = None) -> dict:
    """Public health signals for a repo hosting bounties. Never raises."""
    h: dict = {"repo": repo}
    meta = get_json(f"{API}/repos/{repo}", _auth(token))
    # A failed read must NOT degrade into fabricated zeros: on 2026-09-13 a 404 here
    # (from url-encoding owner/repo into the path) left stars=0/created="" and the
    # scorer read those as real evidence, demoting a reputable repo to 'maybe'.
    if not isinstance(meta, dict) or meta.get("_error") or meta.get("message"):
        h["error"] = str(meta.get("_error") or meta.get("message") or "repo unreadable")[:120]
        h["verdict"] = "unknown"
        return h
    h.update({
        "stars": meta.get("stargazers_count") or 0,
        "forks": meta.get("forks_count") or 0,
        "open_issues": meta.get("open_issues_count") or 0,
        "language": meta.get("language"),
        "created": str(meta.get("created_at") or "")[:10],
        "pushed": str(meta.get("pushed_at") or "")[:10],
        "owner_type": (meta.get("owner") or {}).get("type"),
        "archived": bool(meta.get("archived")),
    })
    contr = get_json(f"{API}/repos/{repo}/contributors?per_page=100", _auth(token))
    # None (unknown) on failure, never a fake 0 - 'farm' hinges on this signal
    h["contributors"] = len(contr) if isinstance(contr, list) else None

    # Merged-PR evidence, primary source: the NON-search /pulls endpoint (core rate
    # limit, not the 30/min search limit). Counting merged_at among the last closed PRs
    # proves maintainers actually merge; the search total is only a bonus. On
    # 2026-09-13 the search route was rate-limited mid-scan and tt-metal (24,599 merged
    # PRs) came back as None, which a naive scorer read as "merges nothing" and demoted
    # to 'maybe'. Unknown must never be scored as zero.
    recent = get_json(f"{API}/repos/{repo}/pulls?state=closed&sort=updated"
                      f"&direction=desc&per_page=100", _auth(token))
    if isinstance(recent, list):
        h["merged_of_last_100_closed_prs"] = sum(1 for p in recent if p.get("merged_at"))
        h["recent_pr_activity"] = True
    else:
        h["recent_pr_activity"] = False

    merged = get_json(f"{API}/search/issues?q=" + q(f"repo:{repo} is:pr is:merged") + "&per_page=1",
                      _auth(token))
    h["merged_prs"] = merged.get("total_count") if isinstance(merged, dict) else None

    closed_b = get_json(f"{API}/search/issues?q=" + q(f"repo:{repo} is:issue is:closed bounty") + "&per_page=1",
                        _auth(token))
    h["closed_bounty_issues"] = closed_b.get("total_count") if isinstance(closed_b, dict) else None

    if check_scam:
        scam = _scam_signals(repo, token, sample_titles or [])
        h["scam_signals"] = scam["count"]
        if scam["evidence"]:
            h["scam_evidence"] = scam["evidence"]
    h["verdict"] = verdict(h)
    return h


def verdict(h: dict) -> str:
    """farm | maybe | real | unknown - conservative: unknown until proven.

    Two rules learned the hard way on 2026-09-13:
    1. Archived repos are rejected outright - GitHub read-only archives cannot accept
       PRs, so any bounty listed there is unclaimable however healthy the history.
    2. A signal we failed to read (None: rate-limited, endpoint hiccup) is NOT a zero.
       Only *known* zeros penalise. Positive evidence from any available source still
       earns full credit, so a rate-limited scan degrades to 'maybe' instead of
       silently demoting a genuinely reputable repo.
    """
    if h.get("error"):
        return "unknown"
    if h.get("archived"):
        return "farm"
    if h.get("scam_signals"):
        return "farm"

    merged_known = h.get("merged_prs") is not None
    merged = h.get("merged_prs") or 0
    # non-search fallback: how many of the last closed PRs were actually merged
    of100 = h.get("merged_of_last_100_closed_prs")
    merge_evidence = max(merged, (of100 or 0) * 5) if (merged_known or of100) else None

    contrib = h.get("contributors")
    stars = h.get("stars")

    score = 0
    if merge_evidence is None:
        pass                                   # unknown: neutral
    elif merge_evidence >= 50:
        score += 3
    elif merge_evidence >= 5:
        score += 1
    else:
        score -= 3                             # known to merge nothing

    if contrib is None:
        pass
    elif contrib >= 20:
        score += 3
    elif contrib >= 3:
        score += 1

    if stars is not None and stars >= 100:
        score += 2
    if str(h.get("created") or "9999")[:4] <= "2024":
        score += 1
    if (h.get("closed_bounty_issues") or 0) >= 1:
        score += 1

    # 'real' requires positive merge proof from a source we actually read
    if not merge_evidence:
        return "maybe" if score >= 2 else "farm"
    return "real" if score >= 5 else ("maybe" if score >= 2 else "farm")


def _auth(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


# --- listing ----------------------------------------------------------------

def list_bounties(min_usd: float = 100.0, per_query: int = 100,
                  max_repos: int = 12, verify: bool = True,
                  sleep: float = 2.6, check_claims: int = 0) -> dict:
    """Scan GitHub for open paid bounties and rank by reward-per-competition
    *within* repos that pass a credibility screen.

    verify=True runs repo_health per repo (the expensive part, ~6 requests each).
    Unauthenticated GitHub search is capped ~10/min, so sleep is caller-visible.
    """
    token = bearer_from("GITHUB_AGENT_PAT", "GRANT_RADAR_GITHUB_TOKEN_FILE")
    if token:
        sleep = min(sleep, 1.2)

    issues: dict[str, dict] = {}
    notes = []
    for query, src in QUERIES:
        res = get_json(f"{API}/search/issues?q={q(query)}&sort=updated&order=desc&per_page={per_query}",
                       _auth(token))
        if isinstance(res, dict) and res.get("_error"):
            notes.append(f"{src}: {res['_error'][:90]}")
        items = res.get("items") if isinstance(res, dict) else None
        for it in items or []:
            url = it.get("html_url")
            if not url or url in issues:
                continue
            usd, via = issue_usd(it)
            if usd < min_usd:
                continue
            issues[url] = {
                "source": "github",
                "channel": src,
                "url": url,
                "repo": (it.get("repository_url") or "").replace(API + "/repos/", ""),
                "title": (it.get("title") or "").strip()[:140],
                "usd": usd,
                "usd_via": via,
                "currency": "USD",
                "competition": it.get("comments") or 0,
                "created": str(it.get("created_at") or "")[:10],
                "updated": str(it.get("updated_at") or "")[:10],
                "labels": [l.get("name") for l in (it.get("labels") or [])][:8],
                "issue": int(url.rsplit("/", 1)[-1]) if url.rsplit("/", 1)[-1].isdigit() else None,
                "next_step": "read the issue, comment to claim, submit a PR; paid on merge",
            }

    by_repo: dict[str, list[dict]] = {}
    for row in issues.values():
        by_repo.setdefault(row["repo"], []).append(row)

    ranked: list[dict] = []
    skipped: list[dict] = []
    order = sorted(by_repo.items(), key=lambda kv: -sum(r["usd"] for r in kv[1]))
    for repo, rows in order[:max_repos]:
        titles = [r["title"] for r in rows]
        health = (repo_health(repo, token, sample_titles=titles) if verify
                  else {"repo": repo, "verdict": "unverified"})
        rows.sort(key=lambda r: -r["usd"])
        pool = sum(r["usd"] for r in rows)
        if verify and health.get("verdict") == "farm":
            skipped.append({"repo": repo, "headline_pool_usd": pool, "issues": len(rows),
                            "why": _why_farm(health)})
            continue
        for r in rows:
            r["repo_verdict"] = health.get("verdict")
            r["repo_signals"] = {k: health.get(k) for k in
                                 ("merged_prs", "contributors", "stars", "pushed", "owner_type")
                                 if health.get(k) is not None}
            denom = 1 + r["competition"]
            r["score"] = round(r["usd"] / denom * (1.0 if r["repo_verdict"] == "real" else 0.4), 1)
            ranked.append(r)

    ranked.sort(key=lambda r: -r["score"])

    if check_claims:
        # Second filter: a real repo is still not a winnable bounty. Cheap enough
        # to run on the top rows only (see claims.py for what it catches).
        from ..claims import annotate
        annotate(ranked, token=token, limit=check_claims)
        ranked.sort(key=lambda r: (RANK_ORDER.get(r.get("claimable"), 1), -r["score"]))

    return {
        "source": "github",
        "scanned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "authenticated": bool(token),
        "issues_seen": len(issues),
        "repos_seen": len(by_repo),
        "returned": len(ranked),
        "bounties": ranked,
        "skipped_farms": skipped,
        "notes": notes,
        "hint": "headline pool size is NOT trust; the skipped_farms list is the point. "
                "And 'real repo' is NOT 'claimable' - run check_claims on the top rows.",
    }


# claimable -> sort priority (lower first)
RANK_ORDER = {"open": 0, "unknown": 1, "needs-human": 2, "risky": 3,
              "contested": 4, "blocked": 5, "expired": 6, "closed": 7}


def _why_farm(h: dict) -> str:
    bits = []
    if h.get("archived"):
        bits.append("repo archived (read-only: PRs cannot be merged, bounty unclaimable)")
    if h.get("scam_signals"):
        ev = h.get("scam_evidence") or []
        bits.append("self-declared symbolic/fake bounty language" +
                    (f" ({ev[0]})" if ev else ""))
    if not (h.get("merged_prs") or 0):
        bits.append("zero PRs ever merged")
    if (h.get("contributors") or 0) <= 1:
        bits.append("single contributor")
    return "; ".join(bits) or "failed credibility score"
