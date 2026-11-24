#!/usr/bin/env python3
"""
Pull sportsbook player-prop lines (DraftKings, FanDuel, BetMGM and the other
books on your SportsGameOdds plan) and save them as sportsbook.json for
Low Line Finder. Uses only Python's built-in modules.

Needs a SportsGameOdds API key in the SGO_API_KEY environment variable.
On GitHub it comes from the repo secret of the same name.

The free plan allows 2,500 events a month. Each run only asks for games
starting in the next --hours hours, so one NBA run uses about 5-15 events.

Run:
    python fetch_sportsbook.py --leagues NBA --out data/sportsbook.json

Options
  --leagues NBA        comma-separated: NBA, NFL, NHL, MLB, NCAAB, NCAAF
  --hours 30           only games starting within this many hours
  --out sportsbook.json
"""
import argparse
import datetime as dt
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.sportsgameodds.com/v2/events"


def get(params, key):
    url = BASE + "?" + urllib.parse.urlencode(dict(params, apiKey=key))  # docs show both the header and this parameter
    req = urllib.request.Request(url, headers={"x-api-key": key, "Accept": "application/json",
                                               "Accept-Encoding": "gzip", "User-Agent": "low-line-finder"})
    err = "no response"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            if e.code in (401, 403):
                sys.exit(f"SportsGameOdds refused the API key (HTTP {e.code}). Check the SGO_API_KEY secret. {detail}")
            if e.code == 429:
                sys.exit(f"SportsGameOdds says you're over your plan's limit (HTTP 429). {detail} "
                         "The previous file was left unchanged.")
            err = f"HTTP {e.code} {detail}"
        except Exception as e:
            err = type(e).__name__
        time.sleep(10 * (attempt + 1))
    sys.exit(f"SportsGameOdds didn't respond ({err}). The previous file was left unchanged.")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leagues", default="NBA")
    ap.add_argument("--hours", type=float, default=30)
    ap.add_argument("--out", default="sportsbook.json")
    a = ap.parse_args()
    key = os.environ.get("SGO_API_KEY", "").strip()
    if not key:
        sys.exit("No API key. Set SGO_API_KEY (on GitHub: Settings -> Secrets and variables -> Actions).")

    now = dt.datetime.now(dt.timezone.utc)
    params = {"leagueID": a.leagues.upper(), "oddsAvailable": "true", "type": "match", "limit": 50,
              "startsAfter": (now - dt.timedelta(hours=3)).isoformat(timespec="seconds").replace("+00:00", "Z"),
              "startsBefore": (now + dt.timedelta(hours=a.hours)).isoformat(timespec="seconds").replace("+00:00", "Z")}

    events, cursor = [], None
    while True:
        p = dict(params, **({"cursor": cursor} if cursor else {}))
        res = get(p, key)
        if res.get("success") is False:
            sys.exit(f"SportsGameOdds error: {res.get('error')}. The previous file was left unchanged.")
        events.extend(res.get("data") or [])
        cursor = res.get("nextCursor")
        if not cursor:
            break
        time.sleep(7)  # stay under the free plan's 10 requests a minute

    props, books_seen = [], {}
    for ev in events:
        players = ev.get("players") or {}
        teams = ev.get("teams") or {}
        team_abbr = {}
        for side in ("home", "away"):
            t = teams.get(side) or {}
            team_abbr[t.get("teamID")] = ((t.get("names") or {}).get("short") or "")
        start = (ev.get("status") or {}).get("startsAt", "")
        for odd in (ev.get("odds") or {}).values():
            if odd.get("betTypeID") != "ou" or odd.get("sideID") != "over" or odd.get("periodID") != "game":
                continue
            pl = players.get(odd.get("statEntityID"))
            if not pl:
                continue  # team or game totals, not a player prop
            books = {}
            for bid, b in (odd.get("byBookmaker") or {}).items():
                line = num(b.get("overUnder"))
                if b.get("available") is False or line is None:
                    continue
                books[bid] = {"line": line, "odds": b.get("odds")}
                books_seen[bid] = books_seen.get(bid, 0) + 1
            if not books:
                continue
            props.append({
                "player": pl.get("name") or f"{pl.get('firstName', '')} {pl.get('lastName', '')}".strip(),
                "team": team_abbr.get(pl.get("teamID"), ""),
                "league": ev.get("leagueID", ""),
                "statID": odd.get("statID"),
                "start": start,
                "consensus": num(odd.get("bookOverUnder")),
                "fair": num(odd.get("fairOverUnder")),
                "books": books,
            })

    if not props:
        sys.exit(f"No player props found for {a.leagues} in the next {a.hours:g} hours "
                 f"({len(events)} games). The previous file was left unchanged.")

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"source": "sportsgameodds", "pulled": now.isoformat(timespec="minutes"),
                   "pulledMs": int(now.timestamp() * 1000), "events": len(events),
                   "books": sorted(books_seen, key=lambda b: -books_seen[b]), "props": props},
                  f, separators=(",", ":"))
    print(f"Saved {len(props)} player lines from {len(books_seen)} books across {len(events)} games to {a.out}. "
          f"(That used {len(events)} of your monthly events.)")


if __name__ == "__main__":
    main()
