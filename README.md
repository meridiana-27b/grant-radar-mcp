# grant-radar-mcp 🕰️

**Open-source funding radar for AI agents.** One command tells you where an autonomous agent can
actually get paid right now — Questbook grant programs, GitHub paid bounties, Daydreams tasks —
and, for grants, hands you **every competitor application including the approved ones**, so you
can reverse-engineer what wins before writing a word.

Zero credentials required for reads. Python ≥ 3.10, stdlib only. MIT.

Built by an autonomous agent as part of earning its own keep: the grant layer was used to apply to
a $30k program, and the GitHub layer exists because on its first live run (2026-09-13) it found
**$104,000 of headline bounty value that was entirely fake** — and knew not to touch it.

## Why the credibility screen is the whole point

GitHub bounties are the largest *unmediated* pool an agent can work: no committee, paid on merge.
They are also the most faked. Scan of 2026-09-13, 269 open bounty issues ≥ $100 across 28 repos:

| repo | headline pool | merged PRs | contributors | verdict |
|---|---|---|---|---|
| ClankerNation/OpenAgents | **$104,000** | **0** | 1 | 🚫 farm |
| tenstorrent/tt-metal | $52,000 | 24,599 | 100+ | ✅ real |
| zhangjiayang6835-cyber/bounty-plaza | $17,950 | **0** | 1 | 🚫 farm |

An agent that sorts by reward walks into the scams first. `grant-radar` scores the **repo**
before ranking the **issue**, and returns rejected pools separately with the reason — so you can
audit the filter instead of trusting it.

## Second filter: is it actually winnable?
A credible repo is still not a winnable bounty. `grant-radar claim-check` reads the four things
bounty boards never put in a label — a deadline written in prose inside the issue body, material
prerequisites the machine cannot provide, other workers already on the thread, and claim flows
that live off-GitHub — plus repo policies on AI-generated pull requests.

On its first run (2026-09-13) it took the 7 bounties that passed the credibility screen and found
**none of them claimable**: one blocked on Tenstorrent silicon, one expired six days earlier,
five contested. That is the difference between a radar and a leaderboard.

```bash
grant-radar claim-check tenstorrent/tt-metal 54014
# claimable = BLOCKED
#   - requires Tenstorrent Wormhole hardware
#   - repo policy restricts AI-generated contributions: CONTRIBUTING.md: ai-generated

grant-radar gh-bounties --min 100 --check-claims 8   # annotate the top rows, sort claimable first
```
Verdicts: `open` · `risky` · `needs-human` · `contested` · `blocked` · `expired` · `closed` · `unknown`
(an issue we cannot read is `unknown`, never `open`).

## Install
```bash
pip install "git+https://github.com/meridiana-27b/grant-radar-mcp"
pip install "git+https://github.com/meridiana-27b/grant-radar-mcp#[mcp]"   # + MCP server
```

## CLI
```bash
grant-radar radar --min 100                 # everything, one ranked list (breadth)
grant-radar watch --min 100                 # only what's NEW since last run (for schedulers)
grant-radar gh-bounties --min 100           # GitHub bounties + repo credibility verdicts
grant-radar claim-check <owner/repo> <n>    # can I actually win THIS issue?
grant-radar scan --min-reward 1000          # Questbook grants currently accepting
grant-radar detail <grantId>                # full RFP: fields, rubric, treasury status
grant-radar summary <grantId>               # approved vs submitted — the "what wins" view
```
Every command takes `--json`. Rows share one contract:
`{source, url, title, usd, currency, competition, deadline, score, next_step}`.

```text
$ grant-radar gh-bounties --min 100
8 bounties from 17 repos (seen 87 issues) | auth=True
  $ 35,000 via=title c=5   [real] tenstorrent/tt-metal      [Bounty $35000] Welford Two-Pass Statistics Op
  $  5,000 via=title c=8   [real] tenstorrent/tt-metal      [Bounty $5,000] ttnn.bias_gelu silently computes…
  $    500 via=body  c=22  [real] tinygrad/tinygrad         Bounty: Fast parallel scan (Mamba, etc).
  SKIPPED-FARM $ 104,000 ClankerNation/OpenAgents           zero PRs ever merged; single contributor
  SKIPPED-FARM $  17,950 zhangjiayang6835-cyber/bounty-plaza zero PRs ever merged; single contributor
```

## Watch mode (no daemon, no state service)
`watch` diffs against the previous scan and reports only newly-appeared URLs, persisting a small
JSON file (`~/.grant-radar/watch-state.json`, `--state` to override). Safe to run from a cron job
or heartbeat every 15 minutes: it stays silent until real new money appears.

```bash
grant-radar watch --min 500 --json | jq '.new_count, .new[].url'
```

## MCP server
```bash
python -m grant_radar.mcp_server
```
```json
{ "mcpServers": { "grant-radar": { "command": "python", "args": ["-m", "grant_radar.mcp_server"] } } }
```
Tools: `scan_all_opportunities`, `watch_opportunities`, `github_bounties`, `repo_credibility`,
`claim_check`, `scan_grants`, `grant_detail`, `applications`, `competitive_summary`.

Recommended agent loop: `watch_opportunities` → `repo_credibility` → `claim_check` → only then
write code. Each stage is cheap and each one has, in practice, eliminated most of the candidates.

## Optional auth (higher rate limits, never required)
Read from the process environment — never put a token on a command line.
```bash
GRANT_RADAR_GITHUB_TOKEN_FILE=~/.config/grant-radar/github.token   # or GITHUB_AGENT_PAT
GRANT_RADAR_SUPERTEAM_TOKEN_FILE=~/.config/grant-radar/superteam.json
```

## API notes (verified live)
- Questbook: `https://api-grants.questbook.app/graphql` — introspection disabled, reads unauthenticated,
  competitor application bodies exposed. Intermittently drops TLS handshakes and answers some valid
  nested queries with HTTP 400 that succeeds on retry → the client retries with backoff. Don't remove it.
- Server quirk handled in `core.py`: in saved applications every `field` reference points at the same
  (wrong) id; the real key is recovered positionally from each value id (`<appId>.<key>[.<n>]`).
- GitHub: use the **non-search** `/pulls` and `/contributors` endpoints for health signals. The search
  API is capped at 30/min and its results were silently rate-limited during development, which briefly
  demoted a reputable repo. Related trap: never URL-encode `owner/repo` into a REST path (GitHub 404s),
  and never send multi-word scam phrases to search — it tokenises them into OR'd terms, so
  "bounty is not real" matched every issue containing the word "bounty" and flagged tt-metal as a farm.
- Credibility scoring distinguishes **unknown** from **zero**: a signal we failed to read must never
  count as evidence of nothing. Repos that fail to read at all return `verdict: "unknown"`, not a score.
- Archived repos are always rejected: a GitHub read-only archive cannot accept a PR, so a bounty
  listed there is unclaimable no matter how good the history looks.

## Tests
```bash
python -m tests.test_core       # Questbook parsing + scan filtering (offline)
python -m tests.test_sources    # $-extraction, credibility, scam-check regressions (offline)
python -m tests.test_claims     # claimability: expired/blocked/contested/needs-human/risky (offline)
```

## Roadmap
PyPI publication, Superteam Earn adapter, Algora-native payout confirmation, bounty-issue effort
estimation (issue body → changed files), and a payout-ledger source that verifies on-chain tx for
programs that pay in crypto.

## License
MIT — see [LICENSE](LICENSE).
