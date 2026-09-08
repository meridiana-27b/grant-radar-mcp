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

mcp = FastMCP("grant-radar", instructions=(
    "Funding radar for AI agents on Questbook grant programs. Zero credentials required: "
    "scan currently-accepting grants, read full RFP detail (fields/rubric/program doc), and "
    "pull every competitor application with its state (approved/submitted) to analyze what wins."
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


def main() -> None:
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()