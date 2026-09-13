"""Offline tests for the claimability layer (no network).

The claimability layer exists because a *credible repo* is not the same as a
*winnable bounty*. These cases encode the four failure modes measured live on
2026-09-13, when 7 of 7 bounties that passed the repo credibility screen turned
out to be unwinnable by an agent.

Run:  python -m tests.test_claims
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from grant_radar.claims import claim_check, parse_deadline


def test_parse_deadline_iso_and_prose() -> None:
    assert parse_deadline("due 2026-02-08") == "2026-02-08"
    assert parse_deadline("Deadline Sep 7: content bounty") == "2026-09-07"
    assert parse_deadline("deadline December 31") == "2026-12-31"
    assert parse_deadline("no timing info here") is None
    assert parse_deadline("") is None


def test_expired_when_deadline_passed() -> None:
    issue = {"title": "Deadline Sep 7: ticket content bounty", "body": "", "state": "open",
             "html_url": "https://github.com/Uuriko/dasha-desk/issues/162"}
    calls = {"n": 0}

    def fake(url, headers=None, **kw):
        calls["n"] += 1
        if "/comments" in url:
            return []
        return issue

    import grant_radar.claims as C
    orig = C.get_json
    C.get_json = fake
    try:
        r = claim_check("Uuriko/dasha-desk", 162, today="2026-09-13", check_policy=False)
    finally:
        C.get_json = orig
    assert r["claimable"] == "expired", r
    assert r["deadline"] == "2026-09-07"


def test_blocked_on_missing_hardware() -> None:
    # observed: tenstorrent/tt-metal#54016 ($35k) - fix needs Wormhole/Blackhole silicon
    issue = {"title": "[Bounty $35000] Welford Two-Pass Statistics Optimisation",
             "body": "Measured on Wormhole n150 and Blackhole p150b hardware.",
             "state": "open", "html_url": "x"}
    import grant_radar.claims as C
    orig = C.get_json
    C.get_json = lambda u, headers=None, **k: ([] if "/comments" in u else issue)
    try:
        r = claim_check("tenstorrent/tt-metal", 54016, today="2026-09-13", check_policy=False)
    finally:
        C.get_json = orig
    assert r["claimable"] == "blocked", r
    assert "Tenstorrent" in " ".join(r["reasons"])


def test_contested_when_thread_taken() -> None:
    issue = {"title": "Bounty: fast parallel scan", "body": "", "state": "open", "html_url": "x"}
    comments = [{"author_association": "NONE", "body": "I'm working on this"},
                {"author_association": "NONE", "body": "+1"}] * 6
    import grant_radar.claims as C
    orig = C.get_json
    C.get_json = lambda u, headers=None, **k: (comments if "/comments" in u else issue)
    try:
        r = claim_check("tinygrad/tinygrad", 3039, today="2026-09-13", check_policy=False)
    finally:
        C.get_json = orig
    assert r["claimable"] == "contested", r


def test_needs_human_when_claim_is_off_github() -> None:
    issue = {"title": "pipeline bounty", "state": "open", "html_url": "x",
             "body": "Claim by commenting below. Tracked in Discord: "
                     "https://discord.com/channels/123/456"}
    import grant_radar.claims as C
    orig = C.get_json
    C.get_json = lambda u, headers=None, **k: ([] if "/comments" in u else issue)
    try:
        r = claim_check("copperheadhq/copperhead", 66, today="2026-09-13", check_policy=False)
    finally:
        C.get_json = orig
    assert r["claimable"] == "needs-human", r


def test_risky_on_hard_ai_policy() -> None:
    import base64
    issue = {"title": "Bounty $200 fix", "body": "", "state": "open", "html_url": "x"}
    readme = base64.b64encode(b"We do not accept AI-generated pull requests.").decode()

    def fake(url, headers=None, **k):
        if "/comments" in url:
            return []
        if url.endswith("CONTRIBUTING.md"):
            return {"content": readme}
        if "/issues/" in url:
            return issue
        return {"message": "Not Found"}

    import grant_radar.claims as C
    orig = C.get_json
    C.get_json = fake
    try:
        r = claim_check("some/repo", 1, today="2026-09-13", check_policy=True)
    finally:
        C.get_json = orig
    assert r["claimable"] == "risky", r
    assert r["ai_policy_hard"]


def test_open_when_clean() -> None:
    issue = {"title": "Bounty $400: add CSV export", "body": "Straightforward.", "state": "open",
             "html_url": "x"}
    import grant_radar.claims as C
    orig = C.get_json
    C.get_json = lambda u, headers=None, **k: ([] if "/comments" in u else issue)
    try:
        r = claim_check("some/repo", 9, today="2026-09-13", check_policy=False)
    finally:
        C.get_json = orig
    assert r["claimable"] == "open", r


def test_unreadable_is_unknown_not_open() -> None:
    import grant_radar.claims as C
    orig = C.get_json
    C.get_json = lambda *a, **k: {"message": "Not Found"}
    try:
        r = claim_check("nope/nope", 1)
    finally:
        C.get_json = orig
    assert r["claimable"] == "unknown", r


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
