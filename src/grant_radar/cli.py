"""Command-line interface for grant-radar.

Examples:
    grant-radar scan --min-reward 1000
    grant-radar detail <grantId>
    grant-radar apps <grantId> --limit 50
    grant-radar summary <grantId>     # what-wins competitive view
"""
from __future__ import annotations

import argparse
import json
import sys
import time

# Windows consoles default to cp1252 and crash on unicode from grant text.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - non-reconfigurable stream
        pass

from . import __version__
from .core import applications, competitive_summary, grant_detail, scan_grants


def _ts(s) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(float(s)))
    except (TypeError, ValueError):
        return "?"


def _reward(g: dict) -> str:
    r = g.get("reward") or {}
    tok = ((r.get("token") or {}).get("label")) or "?"
    try:
        amt = float(r.get("committed"))
        amt = f"{amt:.0f}"
    except (TypeError, ValueError):
        amt = str(r.get("committed"))
    return f"${amt} {tok}"


def _print_grant(tag: str, g: dict) -> None:
    ws = (g.get("workspace") or {}).get("title") or "?"
    nets = ",".join((g.get("workspace") or {}).get("supportedNetworks") or []) or "-"
    dl = _ts(g.get("deadlineS")) if g.get("deadlineS") else "no-dl"
    print(f"{tag} {g['title'][:70]:<72} | {_reward(g):<14} | apps={str(g.get('numberOfApplications')):<4} | "
          f"{ws[:28]:<28} | nets={nets:<9} | dl={dl:<10} | payout={g.get('payoutType')} review={g.get('reviewType')}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="grant-radar", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"grant-radar {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="list accepting grants")
    s.add_argument("--min-reward", type=float, default=1000.0)
    s.add_argument("--max-pages", type=int, default=7)
    s.add_argument("--json", action="store_true", help="raw JSON out")

    d = sub.add_parser("detail", help="full detail for one grant")
    d.add_argument("grant_id")
    d.add_argument("--json", action="store_true")

    a = sub.add_parser("apps", help="all competitor applications")
    a.add_argument("grant_id")
    a.add_argument("--limit", type=int, default=50)
    a.add_argument("--json", action="store_true")

    c = sub.add_parser("summary", help="competitive what-wins view (grouped by state)")
    c.add_argument("grant_id")
    c.add_argument("--limit", type=int, default=50)
    c.add_argument("--json", action="store_true")

    args = p.parse_args(argv)

    try:
        if args.cmd == "scan":
            r = scan_grants(min_reward_usd=args.min_reward, max_pages=args.max_pages)
            if args.json:
                print(json.dumps(r, indent=1))
            else:
                print(f"scanned={r['scanned']} | accepting >= ${args.min_reward:.0f}: "
                      f"{len(r['with_deadline']) + len(r['no_deadline'])} "
                      f"(with deadline {len(r['with_deadline'])}, no-deadline {len(r['no_deadline'])})")
                for g in r["with_deadline"]:
                    _print_grant("[DL]", g)
                for g in r["no_deadline"]:
                    _print_grant("   ", g)
        elif args.cmd == "detail":
            g = grant_detail(args.grant_id)
            if not g:
                print("grant not found", file=sys.stderr)
                return 2
            if args.json:
                print(json.dumps(g, indent=1))
            else:
                print(f"title     : {g.get('title')}")
                print(f"accepting : {g.get('acceptingApplications')} | apps={g.get('numberOfApplications')} "
                      f"| selected={g.get('numberOfApplicationsSelected')} | disbursed=${g.get('totalGrantFundingDisbursedUSD')}")
                print(f"reward    : {_reward(g)} | payout={g.get('payoutType')} review={g.get('reviewType')} "
                      f"| deadlineS={g.get('deadlineS')}")
                ws = g.get("workspace") or {}
                safe = ws.get("safe")
                print(f"workspace : {ws.get('title')} | nets={','.join(ws.get('supportedNetworks') or [])} | "
                      f"safe={'%s@chain_%s' % (safe.get('address'), safe.get('chainId')) if safe else 'NOT SET'}")
                if g.get("link"):
                    print(f"program doc: {g['link']}")
                summ = (g.get("summary") or "").strip()
                det = (g.get("details") or "").strip()
                if summ:
                    print(f"\n--- summary ---\n{summ[:1200]}")
                if det:
                    print(f"\n--- details ---\n{det[:2500]}")
                rubric = g.get("rubric") or {}
                for it in rubric.get("items") or []:
                    print(f"  rubric: {it.get('title')} (max {it.get('maximumPoints')}) - {(it.get('details') or '')[:120]}")
                print("\nfields:")
                for f in g.get("fields") or []:
                    pii = " [PII]" if f.get("isPii") else ""
                    print(f"  - {f.get('title')} ({f.get('inputType')}){pii}")
        elif args.cmd == "apps":
            apps_ = applications(args.grant_id, limit=args.limit)
            if args.json:
                print(json.dumps(apps_, indent=1))
            else:
                from collections import Counter
                print(f"{len(apps_)} applications | states={dict(Counter(a['state'] for a in apps_))}")
                for a in apps_:
                    pn = (a["fields"].get("projectName") or "?")[:80]
                    print(f"* [{str(a['state']):<9}] {pn}")
        elif args.cmd == "summary":
            r = competitive_summary(args.grant_id, limit=args.limit)
            if args.json:
                print(json.dumps(r, indent=1))
            else:
                print(f"states: {r['states']}")
                for st, grp in r["grouped"].items():
                    print(f"\n--- state={st} ({len(grp)}) ---")
                    for x in grp:
                        print("* " + (x["projectName"] or "?"))
                        if x["tldr"]:
                            print("   TLDR : " + x["tldr"].replace("\n", " "))
                        if x["fundingAsk"]:
                            print("   ASK  : " + x["fundingAsk"].replace("\n", " ")[:200])
                        for m in x["milestones"]:
                            print("   MST  : " + m)
    except Exception as e:  # noqa: BLE001 - CLI boundary
        print(f"error: {e!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())