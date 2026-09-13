"""grant-radar-mcp: open-source funding radar for AI agents.

Two layers:
  core   - Questbook grant intelligence (accepting grants, RFP detail, and the
           full text of competitor applications with their state).
  radar  - multi-source breadth (GitHub paid bounties with repo credibility
           verdicts, Daydreams tasks) + diff-based watch mode for schedulers.
"""
from .claims import claim_check
from .core import applications, competitive_summary, grant_detail, scan_grants
from .radar import scan_all, watch
from .sources.github_bounties import list_bounties, repo_health

__version__ = "0.2.0"
__all__ = [
    "scan_grants", "grant_detail", "applications", "competitive_summary",
    "scan_all", "watch", "list_bounties", "repo_health", "claim_check", "__version__",
]
