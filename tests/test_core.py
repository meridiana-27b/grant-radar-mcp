"""Offline tests for grant-radar core parsing logic (no network needed).

Run:  python -m tests.test_core
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from grant_radar.core import _answer_text, _field_key


def test_field_key() -> None:
    # standard: <appId24>.<key>.<idx>
    assert _field_key("6a20f23ef9f18823352d3b39.applicantName.0") == "applicantName"
    assert _field_key("6a20f23ef9f18823352d3b39.customField0-Domain.0") == "customField0-Domain"
    # with trailing version segment (observed in live data)
    assert _field_key("6a232414f9f18823352d3b39.applicantAddress.0.1782564945") == "applicantAddress"
    # no trailing index
    assert _field_key("6a20f23ef9f18823352d3b39.projectName") == "projectName"
    # non-conforming ids yield None (no crash)
    assert _field_key("weird-id") is None
    assert _field_key("") is None


def test_answer_text() -> None:
    # value holds the text, answer holds an id reference
    v = {"value": "Aakash Goswami", "answer": "6a20f23ef9f1882335279.applicantName"}
    assert _answer_text(v) == "Aakash Goswami"
    # reversed: answer holds the text
    v = {"value": None, "answer": "$2,000 for compute + hosting"}
    assert _answer_text(v) == "$2,000 for compute + hosting"
    # both id-like -> empty
    v = {"value": "6a20f23ef9f18823352d3b39", "answer": "deadbeefcafedeadbeef"}
    assert _answer_text(v) == ""
    assert _answer_text({}) == ""


def test_scan_filtering(monkeypatched_grants=None) -> None:
    """Exercise the filter logic of scan_grants against a fake page (no network)."""
    import grant_radar.core as core

    now = core.time.time()
    future_dl = int(now + 86400 * 10)
    past_dl = int(now - 86400)
    fake_pages = [
        {
            "_id": "g1", "title": "Future DL", "acceptingApplications": True, "deadlineS": future_dl,
            "reward": {"committed": 5000, "token": {"label": "USD"}},
        },
        {
            "_id": "g2", "title": "No deadline small", "acceptingApplications": True, "deadlineS": None,
            "reward": {"committed": 999, "token": {"label": "USD"}},   # below default min
        },
        {
            "_id": "g3", "title": "No deadline big", "acceptingApplications": True, "deadlineS": None,
            "reward": {"committed": 20000, "token": {"label": "USDC"}},
        },
        {
            "_id": "g4", "title": "Closed", "acceptingApplications": False, "deadlineS": future_dl,
            "reward": {"committed": 99999, "token": {"label": "USD"}},
        },
        {
            "_id": "g5", "title": "Past deadline (closed by time)", "acceptingApplications": True, "deadlineS": past_dl,
            "reward": {"committed": 99999, "token": {"label": "USD"}},
        },
    ]

    calls = {}

    def fake_page(first, skip):
        calls["skip"] = skip
        if skip == 0:
            return list(fake_pages)
        return []

    orig = core._grants_page
    core._grants_page = fake_page
    try:
        r = core.scan_grants(min_reward_usd=1000.0, max_pages=2)
    finally:
        core._grants_page = orig

    assert r["scanned"] == 5
    assert [g["_id"] for g in r["with_deadline"]] == ["g1"], "only future-deadline accepting grant qualifies"
    assert [g["_id"] for g in r["no_deadline"]] == ["g3"], "below-min and closed/past-dl grants filtered out"


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