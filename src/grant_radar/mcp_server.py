"""MCP (Model Context Protocol) server exposing grant-radar as agent tools.

Run over stdio:
    python -m grant_radar.mcp_server

Wire into any MCP client, e.g. Claude Desktop / OpenClaw config:
    {
      "mcpServers": {
        "grant-radar": {
          "command": "python",
          "args": ["-m", "grant_radar.mcp_server"]
        }
      }
    }

Requires the optional dependency:  pip install grant-radar-mcp[mcp]
"""
from __future__ import annotations

import json

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:  # pragma: no cover - optional extra missing
    raise SystemExit(
        "The 'mcp' package is required to run the MCP server. "
        "Install it with: pip install 'grant-radar-mcp[mcp]'"
    ) from e

from . import __version__
import grant_radar.core as core  # module ref: tool function names shadow the imported ones
from grant_radar import radar as _radar
from grant_radar.sources import github_bounties as _gh

mcp = FastMCP("grant-radar", instructions=(
    "Funding radar for AI agents. Zero credentials required for reads. Two layers: "
    "(1) Questbook grant intelligence - scan accepting grants, read full RFP detail "
    "(fields/rubric/program doc), pull every competitor application with its state "
    "(approved/submitted) to analyze what wins; (2) multi-source breadth - GitHub paid "
    "bounties (with repo credibility verdicts that filter out scam bounty-farms), Daydreams "
    "tasks, plus a diff-based watch mode for scheduled agents."
))


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


@mcp.tool()
def scan_grants(min_reward_usd: float = 1000.0, max_pages: int = 7) -> str:
    """Scan Questbook for grant programs currently accepting applications.

    Returns JSON with every qualifying grant (reward >= min_reward_usd), split into
    `with_deadline` (sorted by deadline, soonest first) and `no_deadline`. Each entry has
    _id, title, reward {committed, token.label}, workspace, supportedNetworks, payoutType,
    reviewType, numberOfApplications and deadlineS.
    """
    return _j(core.scan_grants(min_reward_usd=min_reward_usd, max_pages=max_pages))


@mcp.tool()
def grant_detail(grant_id: str) -> str:
    """Full detail for one Questbook grant by its _id.

    Includes summary/details text, program doc link (often a Google Doc with the RFP),
    reward + token, payoutType/reviewType, deadlineS, workspace safe status, every form
    field (title/inputType/isPii) and any review rubric items. Essential before applying.
    """
    g = core.grant_detail(grant_id=grant_id)
    if not g:
        return json.dumps({"error": f"grant {grant_id} not found"})
    return _j(g)


@mcp.tool()
def applications(grant_id: str, limit: int = 50) -> str:
    """Every competitor application for a grant, normalized.

    Returns JSON list; each entry has state (approved/selected/submitted/...), applicantId,
    createdAtS, milestone titles and a fields map {fieldKey: answerText}. The `state` field
    reveals which competitors were approved - the key to competitive analysis.
    """
    return _j(core.applications(grant_id=grant_id, limit=limit))


@mcp.tool()
def competitive_summary(grant_id: str, limit: int = 50) -> str:
    """The 'what wins' view for a grant: applications grouped by state with their
    projectName / tldr / fundingAsk / milestone titles. Use this to reverse-engineer the
    profile of approved proposals before writing your own application.
    """
    return _j(core.competitive_summary(grant_id=grant_id, limit=limit))


@mcp.tool()
def scan_all_opportunities(min_usd: float = 100.0,
                           sources: str = "questbook,github,daydreams",
                           verify_github: bool = True) -> str:
    """Multi-source funding scan returning one normalized, ranked opportunity list.

    Sources: 'questbook' (grant programs, tickets usually >= $500), 'github' (paid OSS
    bounties - no committee, paid on merge), 'daydreams' (small tasks). Returns rows with
    {source,url,title,usd,currency,competition,deadline,next_step,score} plus a
    `skipped_farms` list of repos rejected as fake bounty boards. Set verify_github=False
    only if you accept the risk of ranking scam pools - the check is the value.
    """
    srcs = [s.strip() for s in sources.split(",") if s.strip()]
    return _j(_radar.scan_all(min_usd=min_usd, sources=srcs, verify_github=verify_github))


@mcp.tool()
def watch_opportunities(min_usd: float = 100.0,
                        sources: str = "questbook,github,daydreams") -> str:
    """Diff against the previous scan and report ONLY newly-appeared opportunities.

    Idempotent by URL and stateless between calls except for a small JSON state file, so an
    agent can call this on every heartbeat/cron and stay silent until real new money shows
    up. Returns {new_count,new,total_now,tracked,skipped_farms}.
    """
    srcs = [s.strip() for s in sources.split(",") if s.strip()]
    return _j(_radar.watch(min_usd=min_usd, sources=srcs))


@mcp.tool()
def github_bounties(min_usd: float = 100.0, max_repos: int = 12, verify: bool = True) -> str:
    """Open paid bounties on GitHub (Algora 'Bounty' label, label:bounty, 'bounty' in title).

    Each repo gets a credibility verdict from public signals (merged PRs, contributors,
    stars, repo age, payout history, self-declared scam language) and pools failing the
    screen are returned separately in `skipped_farms` with the reason. This matters: on
    2026-09-13 the two largest headline bounty pools on GitHub ($104k and $18k) were both
    farms with zero merged PRs. Optional auth via GITHUB_AGENT_PAT raises rate limits.
    """
    return _j(_gh.list_bounties(min_usd=min_usd, max_repos=max_repos, verify=verify))


@mcp.tool()
def repo_credibility(repo: str) -> str:
    """Is a GitHub repo actually paying for bounties? Public-health check on one repo.

    Returns merged-PR count, contributor count, stars, age, owner type, closed bounty
    issues, scam-language signals and a verdict: 'real' | 'maybe' | 'farm' | 'unknown'.
    Run this before spending hours on any bounty issue.
    """
    return _j(_gh.repo_health(repo))


def main() -> None:
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()