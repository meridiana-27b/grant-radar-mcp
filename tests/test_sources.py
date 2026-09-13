"""Offline tests for the GitHub bounty source (no network).

Covers the two pieces that decide whether the radar is useful or dangerous:
dollar extraction (headline numbers drive ranking) and repo credibility
verdicts (which keep an agent out of scam bounty farms).

Run:  python -m tests.test_sources
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from grant_radar.sources.github_bounties import extract_usd, issue_usd, verdict


def test_extract_usd_basic() -> None:
    assert extract_usd("[Bounty $35000] Optimise atan2") == 35000
    assert extract_usd("[ Bounty $5k ] Fix rpc.ts") == 5000
    assert extract_usd("$1,250 for a fix") == 1250
    # only the $ figure counts: 100 RTC is a token amount, its dollar value is $10
    assert extract_usd("Reward: 100 RTC (~$10 at reference rate)") == 10
    assert extract_usd("no money here") == 0
    assert extract_usd("") == 0
    assert extract_usd(None) == 0


def test_extract_usd_caps_nonsense() -> None:
    # a typo'd or baited huge number must not dominate a ranking
    assert extract_usd("$999999999") == 0
    assert extract_usd("$2.5k") == 2500


def test_issue_usd_prefers_label_then_title_then_body() -> None:
    it = {"labels": [{"name": "bounty"}], "title": "[Bounty $7500] legacy removal", "body": ""}
    assert issue_usd(it) == (7500, "title")
    it = {"labels": [{"name": "$500"}], "title": "Fix thing", "body": "we pay $900"}
    assert issue_usd(it) == (500, "label")
    it = {"labels": [], "title": "Fix thing", "body": "bounty of $300 when merged"}
    assert issue_usd(it) == (300, "body")
    it = {"labels": [], "title": "Fix thing", "body": "nothing"}
    assert issue_usd(it) == (0, "-")


def test_verdict_real_repo() -> None:
    # observed 2026-09-13: tenstorrent/tt-metal
    h = {"merged_prs": 24599, "contributors": 100, "stars": 1669, "created": "2023-02-13",
         "closed_bounty_issues": 237, "scam_signals": 0, "archived": False}
    assert verdict(h) == "real"


def test_verdict_farm_never_merged() -> None:
    # observed 2026-09-13: ClankerNation/OpenAgents ($104k headline pool)
    h = {"merged_prs": 0, "contributors": 1, "stars": 13, "created": "2026-05-16",
         "closed_bounty_issues": 4, "scam_signals": 0, "archived": False}
    assert verdict(h) == "farm"


def test_verdict_scam_language_wins_immediately() -> None:
    h = {"merged_prs": 500, "contributors": 60, "stars": 900, "created": "2021-01-01",
         "closed_bounty_issues": 20, "scam_signals": 2, "archived": False}
    assert verdict(h) == "farm"


def test_verdict_archived_is_always_farm() -> None:
    # GitHub archives are read-only: no PR can merge, so a bounty there is unclaimable
    h = {"merged_prs": 400, "contributors": 40, "stars": 300, "created": "2020-01-01",
         "closed_bounty_issues": 5, "scam_signals": 0, "archived": True}
    assert verdict(h) == "farm"
    assert verdict({"error": "404"}) == "unknown"
    assert verdict({}) == "farm"


def test_scam_check_is_literal_and_owner_scoped(monkeypatch_get_json=None) -> None:
    """Regression for the 2026-09-13 false positive.

    GitHub's search API tokenises multi-word queries into OR'd terms, so searching a
    repo for "bounty is not real" matches any issue merely containing "bounty" - that
    flagged tenstorrent/tt-metal (24,599 merged PRs) and tinygrad as farms. The check
    must be a LITERAL substring test over owner-controlled files and issue titles.
    """
    import base64
    import grant_radar.sources.github_bounties as gh

    calls: list[str] = []

    def fake_get(url, headers=None, tries=3, timeout=30, max_bytes=2_000_000):
        calls.append(url)
        if url.endswith("/contents/README.md"):
            body = base64.b64encode(b"Real project. Bounties paid on merge via Algora.").decode()
            return {"content": body}
        return {"message": "Not Found"}

    orig = gh.get_json
    gh.get_json = fake_get
    try:
        # healthy README, innocent titles -> clean
        clean = gh._scam_signals("some/real-repo", None, ["[Bounty $7500] remove legacy sqrt"])
        assert clean["count"] == 0, clean
        # the scam repo's own wording, in ITS README -> caught
        def fake_farm(url, headers=None, tries=3, timeout=30, max_bytes=2_000_000):
            calls.append(url)
            if url.endswith("/contents/README.md"):
                body = base64.b64encode(
                    b"Note: bounties are symbolic and we are not financially able to pay.").decode()
                return {"content": body}
            return {"message": "Not Found"}

        gh.get_json = fake_farm
        farm = gh._scam_signals("farm/repo", None, [])
        assert farm["count"] >= 1 and "bounties are symbolic" in " ".join(farm["evidence"]), farm
        # issue title wording -> caught too
        gh.get_json = fake_get
        titled = gh._scam_signals("some/real-repo", None, ["WARNING: bounties are symbolic"])
        assert titled["count"] >= 1, titled
    finally:
        gh.get_json = orig

    # and no search-API query was ever issued from the scam check
    assert not any("/search/issues" in u for u in calls), "scam check must not use the search API"


def test_verdict_unknown_signal_is_not_zero() -> None:
    """Regression for the 2026-09-13 'maybe' bug: a rate-limited search returns
    merged_prs=None, and treating that as 'merges nothing' demoted a real repo.
    Unknown must be neutral; positive evidence from any source still earns credit.
    """
    h = {"merged_prs": None,                    # search route rate-limited
         "merged_of_last_100_closed_prs": 61,   # non-search /pulls route proved merges
         "contributors": 100, "stars": 1669, "created": "2023-02-13",
         "closed_bounty_issues": 237, "scam_signals": 0, "archived": False}
    assert verdict(h) == "real"
    # and with every optional signal unreadable, we stay cautious rather than generous
    blind = {"merged_prs": None, "contributors": None, "stars": None,
             "created": "2023-02-13", "archived": False}
    assert verdict(blind) == "farm", "no positive evidence at all -> never claim 'real'"


def test_repo_health_offline_shape() -> None:
    """repo_health must degrade to verdict=unknown on an unreadable repo, never raise."""
    import grant_radar.sources.github_bounties as gh

    orig = gh.get_json
    gh.get_json = lambda *a, **k: {"message": "Not Found"}
    try:
        h = gh.repo_health("nope/nope")
    finally:
        gh.get_json = orig
    assert h["verdict"] == "unknown" and h.get("error")


def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {e!r}")
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
