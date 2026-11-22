#!/usr/bin/env python3
"""
Pull this season's NBA game logs from NBA.com and save them as
gamelogs.json for Low Line Finder. Uses only Python's built-in modules.

One request gets every player's games for the season, so a full slate
takes a few seconds. No API key or signup needed.

Run:
    python fetch_gamelogs_nba.py                 # every NBA player
    python fetch_gamelogs_nba.py players.txt     # only the names in players.txt

Then in Low Line Finder, click "Load gamelogs.json" and pick the file.

Options
  --games 20        recent games to keep per player
  --season 2026-27  NBA season (defaults to the current one)
  --out gamelogs.json
"""
import argparse
import datetime as dt
import json
import re
import sys
import gzip
import time
import unicodedata
import urllib.parse
import urllib.request

URL = "https://stats.nba.com/stats/leaguegamelog"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive",
}


def norm(name):
    s = unicodedata.normalize("NFD", name or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def current_season():
    t = dt.date.today()
    start = t.year if t.month >= 9 else t.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def fetch(season, season_type):
    """Every player's game log for one season type, as a list of dicts."""
    params = {"Counter": 0, "Direction": "DESC", "LeagueID": "00", "PlayerOrTeam": "P",
              "Season": season, "SeasonType": season_type, "Sorter": "DATE", "DateFrom": "", "DateTo": ""}
    url = URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            res = json.loads(body.decode("utf-8"))
            rs = res["resultSets"][0]
            return [dict(zip(rs["headers"], row)) for row in rs["rowSet"]]
        except Exception as e:  # NBA.com is slow or throttling
            pause = 10 * (attempt + 1)
            print(f"  NBA.com didn't answer ({type(e).__name__}); waiting {pause}s and trying again...")
            time.sleep(pause)
    sys.exit("NBA.com didn't respond after several tries. Wait a few minutes and run it again, "
             "or try from a different network (NBA.com blocks some VPNs and cloud servers).")


def opponent(matchup):
    # "ATL @ ORL" -> "@ORL",  "ATL vs. ORL" -> "vs ORL"
    m = re.match(r"\s*\w+\s+(@|vs\.?)\s+(\w+)", matchup or "")
    if not m:
        return ""
    return ("@" if m.group(1) == "@" else "vs ") + m.group(2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("players", nargs="?", help="optional text file, one player name per line")
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--season", default=current_season())
    ap.add_argument("--out", default="gamelogs.json")
    a = ap.parse_args()

    wanted = None
    if a.players:
        with open(a.players, encoding="utf-8-sig") as f:
            wanted = {norm(l.strip()): l.strip() for l in f if l.strip() and " + " not in l}
        if not wanted:
            sys.exit(f"{a.players} has no player names in it.")

    print(f"Getting {a.season} game logs from NBA.com...")
    rows = fetch(a.season, "Regular Season")
    print(f"  {len(rows)} player-games found")

    by = {}
    for r in rows:
        if not r.get("MIN"):  # did not play
            continue
        key = norm(r.get("PLAYER_NAME"))
        if wanted is not None and key not in wanted:
            continue
        p = by.setdefault(key, {"player": (wanted or {}).get(key) or r.get("PLAYER_NAME"), "games": []})
        p["games"].append({
            "date": str(r.get("GAME_DATE", ""))[:10],
            "opp": opponent(r.get("MATCHUP")),
            "MIN": r.get("MIN"),
            "PTS": r.get("PTS"), "REB": r.get("REB"), "AST": r.get("AST"),
            "STL": r.get("STL"), "BLK": r.get("BLK"), "TOV": r.get("TOV"),
            "FGM": r.get("FGM"), "FGA": r.get("FGA"),
            "FG3M": r.get("FG3M"), "FG3A": r.get("FG3A"),
            "FTM": r.get("FTM"), "FTA": r.get("FTA"),
            "OREB": r.get("OREB"), "DREB": r.get("DREB"),
        })

    out = []
    for p in by.values():
        p["games"].sort(key=lambda g: g["date"])
        p["games"] = p["games"][-a.games:]
        out.append(p)
    out.sort(key=lambda p: p["player"])

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"source": "nba.com", "season": a.season,
                   "pulled": dt.datetime.now().isoformat(timespec="minutes"), "gamelogs": out},
                  f, separators=(",", ":"))

    print(f"\nSaved {len(out)} players to {a.out}.")
    if wanted is not None:
        missing = sorted(n for k, n in wanted.items() if k not in by)
        if missing:
            print(f"No games found for {len(missing)} names (check spelling, or they haven't played): "
                  + ", ".join(missing))


if __name__ == "__main__":
    main()
