#!/usr/bin/env python3
"""
Pull the current PrizePicks board and save it as prizepicks.json for
Low Line Finder. Uses only Python's built-in modules.

The script keeps a history between runs: if the output file already exists,
each line keeps the time it was first seen, and lines that changed record
their previous value. The app shows these as "New" and "was 24.5" tags.

Run:
    python fetch_prizepicks.py                  # NBA
    python fetch_prizepicks.py --leagues 7,9    # NBA and NFL
    python fetch_prizepicks.py --out data/prizepicks.json
    python fetch_prizepicks.py --list           # show every league id PrizePicks has right now

Run with --list to see the current league ids (7 is NBA).

PrizePicks restricts automated access in its terms and blocks many cloud
servers and VPNs. If you get "blocked", run it from your home connection,
or paste the feed into the app by hand. Keep runs a few minutes apart.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = "https://api.prizepicks.com/projections?league_id={league}&per_page=250"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
    "Referer": "https://app.prizepicks.com/",
    "Origin": "https://app.prizepicks.com",
}
LEAGUES = {"7": "NBA", "9": "NFL", "8": "NHL", "2": "MLB", "15": "CFB", "20": "CBB", "82": "SOCCER"}


class Blocked(Exception):
    pass


def get(league, url=None):
    req = urllib.request.Request(url or URL.format(league=league), headers=HEADERS)
    err = "no response"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise Blocked(f"HTTP {e.code}")
            if e.code == 429 or e.code >= 500:
                err = f"HTTP {e.code}"
                time.sleep(15 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            time.sleep(10 * (attempt + 1))
            err = e
    sys.exit(f"PrizePicks didn't respond ({err}). The previous file was left unchanged.")


def parse(obj, league):
    players = {i["id"]: i.get("attributes") or {} for i in obj.get("included", []) if i.get("type") == "new_player"}
    out = []
    for d in obj.get("data", []):
        if d.get("type") != "projection":
            continue
        a, rel = d.get("attributes") or {}, d.get("relationships") or {}
        pid = ((rel.get("new_player") or {}).get("data") or {}).get("id")
        pl = players.get(pid, {})
        try:
            line = float(a.get("line_score"))
        except (TypeError, ValueError):
            continue
        out.append({
            "ppid": str(d.get("id")),
            "player": pl.get("display_name") or pl.get("name") or "Unknown player",
            "team": pl.get("team") or "",
            "opp": a.get("description") or "",
            "sport": pl.get("league") or LEAGUES.get(str(league), "Other"),
            "stat": a.get("stat_type") or "Stat",
            "line": line,
            "tier": a.get("odds_type") or "standard",
            "start": a.get("start_time") or "",
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leagues", default="7", help="comma-separated league ids (default 7 = NBA)")
    ap.add_argument("--out", default="prizepicks.json")
    ap.add_argument("--list", action="store_true", help="print PrizePicks' current league ids and exit")
    a = ap.parse_args()

    if a.list:
        try:
            obj = get(None, "https://api.prizepicks.com/leagues")
        except Blocked as e:
            sys.exit(f"PrizePicks blocked the request ({e}). Try from your home internet.")
        rows = []
        for d in obj.get("data", []):
            at = d.get("attributes") or {}
            rows.append((str(d.get("id")), at.get("name") or "", at.get("projections_count"), at.get("active")))
        rows.sort(key=lambda r: (-(r[2] or 0), r[1]))
        print(f"{'ID':>5}  {'LEAGUE':<28} LINES NOW")
        for i, name, n, active in rows:
            if active is False and not n:
                continue
            print(f"{i:>5}  {name:<28} {n if n is not None else ''}")
        print("\nUse the IDs with --leagues, e.g.  --leagues 7,9")
        return

    now = int(time.time() * 1000)
    prev = {}
    if os.path.exists(a.out):
        try:
            with open(a.out, encoding="utf-8") as f:
                prev = {p["ppid"]: p for p in json.load(f).get("props", [])}
        except (ValueError, KeyError):
            prev = {}
    first_run = not prev

    props = []
    for i, league in enumerate(x.strip() for x in a.leagues.split(",") if x.strip()):
        if i:
            time.sleep(3)
        print(f"Getting {LEAGUES.get(league, 'league ' + league)} lines from PrizePicks...")
        try:
            got = parse(get(league), league)
        except Blocked as e:
            sys.exit(f"PrizePicks blocked the request ({e}). This is common from cloud servers and VPNs. "
                     "Try from your home internet, or paste the feed into the app instead. "
                     "The previous file was left unchanged.")
        print(f"  {len(got)} lines")
        props.extend(got)

    if not props:
        sys.exit("PrizePicks returned no lines (the board may be empty right now). The previous file was left unchanged.")

    new_n = moved = 0
    for p in props:
        old = prev.get(p["ppid"])
        if old:
            p["firstSeen"] = old.get("firstSeen", 0)
            if old.get("line") != p["line"]:
                p["prevLine"], p["movedAt"] = old.get("line"), now
                moved += 1
            else:
                if old.get("prevLine") is not None:
                    p["prevLine"], p["movedAt"] = old["prevLine"], old.get("movedAt", 0)
        else:
            p["firstSeen"] = 0 if first_run else now
            new_n += 0 if first_run else 1

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"source": "prizepicks", "pulled": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "pulledMs": now, "props": props}, f, separators=(",", ":"))
    print(f"\nSaved {len(props)} lines to {a.out}." + ("" if first_run else f" {new_n} new, {moved} moved since last run."))


if __name__ == "__main__":
    main()
