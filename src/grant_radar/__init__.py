"""grant-radar-mcp: open-source funding radar for AI agents on Questbook."""
from .core import applications, competitive_summary, grant_detail, scan_grants

__version__ = "0.1.0"
__all__ = ["scan_grants", "grant_detail", "applications", "competitive_summary", "__version__"]