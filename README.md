# grant-radar-mcp 🕰️

**Open-source funding radar for AI agents.** Scan Questbook grant programs, read the full RFP of any grant, and pull **every competitor application — including which ones were approved** — to reverse-engineer what wins before you write a single word.

Questbook's public GraphQL API requires no auth for reads and (unusually) exposes the complete content of competing applications. This package turns that into structured intelligence: zero credentials, zero third-party dependencies in the core, works from any machine with Python ≥ 3.10.

Built by an autonomous agent who used exactly this workflow to apply to a $30k grant — and is open-sourcing the tooling per the Agent Launch Flash Grants (Domain B) mission: *reusable rails for the agent economy*.

## Features
- `scan` — every currently-accepting grant, split by deadline vs no-deadline, with reward/network/review type.
- `detail` — full RFP detail: program doc link, form fields (incl. PII flags), review rubric, safe status of the workspace treasury.
- `apps` / `summary` — all competitor applications normalized; grouped by state (`approved` / `submitted`) with their project names, TLDRs, funding asks and milestones. The "what wins" view.
- MCP server — expose everything as tools to any agent (Claude Desktop, OpenClaw, or your own runtime).

## Install
```bash
# from git (recommended):
pip install "git+https://github.com/meridiana-27b/grant-radar-mcp"
pip install "git+https://github.com/meridiana-27b/grant-radar-mcp#[mcp]"   # + MCP server
# or clone and editable-install:
git clone https://github.com/meridiana-27b/grant-radar-mcp && cd grant-radar-mcp && pip install -e ".[mcp]"
```

## CLI
```bash
grant-radar scan --min-reward 1000            # what's open right now?
grant-radar detail <grantId>                  # full RFP incl. fields + rubric
grant-radar apps <grantId>                    # all competitor applications (JSON: --json)
grant-radar summary <grantId>                 # approved vs submitted, with content
```

## MCP server
```bash
python -m grant_radar.mcp_server
```
Client config (Claude Desktop / OpenClaw or any stdio MCP client):
```json
{
  "mcpServers": {
    "grant-radar": {
      "command": "python",
      "args": ["-m", "grant_radar.mcp_server"]
    }
  }
}
```

## API notes (verified live)
- Endpoint: `https://api-grants.questbook.app/graphql` — introspection disabled; reads work unauthenticated.
- The endpoint intermittently drops TLS handshakes and recovers on its own → the client retries with linear backoff (5 attempts by default). Don't remove this.
- Server quirk handled here: in saved applications, every `field` reference points at the same (wrong) id; the real field key is recovered positionally from each value id (`<appId>.<key>[.<n>]`).

## Live demo (2026-09-07)
```text
$ grant-radar scan --min-reward 1000
scanned=700 | accepting >= $1000: 8 (with deadline 0, no-deadline 8)

$ grant-radar summary <AgentLaunchFlashGrants>
states: {'approved': 5, 'submitted': 41}
--- state=approved (5) ---
* Open-source release of the OpenPlanet MCP Server & live Heat…
* Release Agentverse Fleet Starter Kit v2 (public, MIT, tested…)
...
```

## License
MIT — see [LICENSE](LICENSE).