#!/usr/bin/env python3
"""
Build NBA game logs from ESPN box scores and save them as gamelogs.json for
Low Line Finder. Uses only Python's built-in modules.

This is the version the GitHub workflow uses, because NBA.com doesn't answer
requests from GitHub's servers. On your own computer either script works.

The first run reads every regular-season game so far (a few hundred requests,
about 2-4 minutes). Later runs only fetch games that aren't in the file yet.

Run:
    python fetch_gamelogs_espn.py --out data/gamelogs.json

Options
  --since 2026-10-20   first date to read (defaults to Oct 20 of this season)
  --games 30           games to keep per player
  --out gamelogs.json
"""
import argparse
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}
# ESPN box-score column -> our field. "FG", "3PT" and "FT" are "made-attempted".
COLS = {"MIN": "MIN", "PTS": "PTS", "REB": "REB", "AST": "AST", "STL": "STL", "BLK": "BLK",
        "TO": "TOV", "OREB": "OREB", "DREB": "DREB"}
SPLIT = {"FG": ("FGM", "FGA"), "3PT": ("FG3M", "FG3A"), "FT": ("FTM", "FTA")}


def norm(name):
    s = unicodedata.normalize("NFD", name or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def get(path):
    err = "no response"
    for attempt in range(4):
        try:
            req = urllib.request.Request(BASE + path, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = f"HTTP {e.code}"
        except Exception as e:  # timeouts, resets
            err = type(e).__name__
        time.sleep(5 * (attempt + 1))
    sys.exit(f"ESPN didn't respond ({err}). The previous file was left unchanged.")


def num(v):
    try:
        return float(v) if "." in str(v) else int(v)
    except (TypeError, ValueError):
        return None


def parse_box(summary, date):
    """Return [(player_name, game_dict)] for everyone who played."""
    out = []
    comps = ((summary.get("header") or {}).get("competitions") or [{}])[0].get("competitors") or []
    side = {}
    for c in comps:
        t = c.get("team") or {}
        side[str(t.get("id"))] = (c.get("homeAway"), t.get("abbreviation", "?"))
    for team in (summary.get("boxscore") or {}).get("players") or []:
        tid = str((team.get("team") or {}).get("id"))
        home_away, _ = side.get(tid, ("", "?"))
        opp = next((abbr for k, (ha, abbr) in side.items() if k != tid), "?")
        opp_txt = ("vs " if home_away == "home" else "@") + opp
        for block in team.get("statistics") or []:
            cols = block.get("labels") or block.get("names") or []
            for a in block.get("athletes") or []:
                stats = a.get("stats") or []
                if a.get("didNotPlay") or not stats or len(stats) != len(cols):
                    continue
                g = {"date": date, "opp": opp_txt}
                for col, val in zip(cols, stats):
                    col = str(col).upper()
                    if col in COLS:
                        g[COLS[col]] = num(val)
                    elif col in SPLIT:
                        m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", str(val))
                        if m:
                            g[SPLIT[col][0]], g[SPLIT[col][1]] = int(m.group(1)), int(m.group(2))
                if not g.get("MIN") or g.get("PTS") is None:
                    continue
                name = (a.get("athlete") or {}).get("displayName")
                if name:
                    out.append((name, g))
    return out


def main():
    today = dt.date.today()
    season = today.year if today.month >= 8 else today.year - 1
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default=f"{season}-10-20")
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--out", default="gamelogs.json")
    a = ap.parse_args()

    players, done = {}, set()
    if os.path.exists(a.out):
        try:
            with open(a.out, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("source") == "espn":
                done = set(old.get("espnEvents", []))
                for p in old.get("gamelogs", []):
                    players[norm(p["player"])] = p
        except (ValueError, KeyError):
            pass

    start = dt.date.fromisoformat(a.since)
    end = today  # include today; unfinished games are skipped and picked up next run
    print(f"Checking ESPN for games from {start} to {end}...")
    new_games = 0
    day = start
    while day <= end:
        sb = get(f"/scoreboard?dates={day:%Y%m%d}") or {}
        for ev in sb.get("events", []):
            eid = str(ev.get("id"))
            stype = ((ev.get("season") or {}).get("type"))
            completed = (((ev.get("status") or {}).get("type") or {}).get("completed"))
            if eid in done or not completed or stype not in (2, "2"):
                continue  # already have it, not final yet, or not regular season
            summary = get(f"/summary?event={eid}")
            if not summary:
                continue
            for name, g in parse_box(summary, day.isoformat()):
                p = players.setdefault(norm(name), {"player": name, "games": []})
                p["games"] = [x for x in p["games"] if x.get("date") != g["date"]] + [g]
            done.add(eid)
            new_games += 1
            time.sleep(0.25)
        day += dt.timedelta(days=1)
        time.sleep(0.25)

    out = []
    for p in players.values():
        p["games"].sort(key=lambda x: x["date"])
        p["games"] = p["games"][-a.games:]
        out.append(p)
    out.sort(key=lambda p: p["player"])

    if not out:
        sys.exit("No games found. ESPN may have changed its format; the previous file was left unchanged.")

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"source": "espn", "pulled": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                   "espnEvents": sorted(done), "gamelogs": out}, f, separators=(",", ":"))
    print(f"Added {new_games} new games. Saved {len(out)} players to {a.out}.")


if __name__ == "__main__":
    main()
