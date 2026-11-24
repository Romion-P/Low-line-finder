#!/usr/bin/env python3
"""
Build game logs from ESPN box scores and save them for Low Line Finder.
Works for NBA, college basketball, NFL, college football, NHL and MLB.
Uses only Python's built-in modules.

This is the version the GitHub workflow uses, because NBA.com doesn't answer
requests from GitHub's servers.

The first run for a sport reads every game of the season so far, which can
take several minutes (college basketball has the most games). Later runs
only fetch games that aren't in the file yet.

Run:
    python fetch_gamelogs_espn.py --sport nba --out data/gamelogs.json
    python fetch_gamelogs_espn.py --sport nfl --out data/gamelogs_nfl.json

Sports: nba, cbb (men's college basketball), nfl, cfb (college football), nhl, mlb

Options
  --since 2026-10-20   first date to read (defaults to the start of this season)
  --games 30           games to keep per player
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}

# path on ESPN, extra scoreboard query (all Division I / FBS games), season start month-day, games kept per player
SPORTS = {
    "nba": ("basketball/nba", "", "10-20", 30),
    "cbb": ("basketball/mens-college-basketball", "&groups=50&limit=500", "11-01", 20),
    "nfl": ("football/nfl", "", "09-01", 20),
    "cfb": ("football/college-football", "&groups=80&limit=300", "08-20", 15),
    "nhl": ("hockey/nhl", "", "10-01", 30),
    "mlb": ("baseball/mlb", "", "03-15", 30),
}

# Basketball box-score column -> our field. "FG", "3PT" and "FT" are "made-attempted".
COLS = {"MIN": "MIN", "PTS": "PTS", "REB": "REB", "AST": "AST", "STL": "STL", "BLK": "BLK",
        "TO": "TOV", "OREB": "OREB", "DREB": "DREB"}
SPLIT = {"FG": ("FGM", "FGA"), "3PT": ("FG3M", "FG3A"), "FT": ("FTM", "FTA")}


def norm(name):
    s = unicodedata.normalize("NFD", name or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def get(base, path):
    err = "no response"
    for attempt in range(4):
        try:
            req = urllib.request.Request(base + path, headers=HEADERS)
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
    s = str(v).strip()
    m = re.match(r"^(\d+):(\d\d)$", s)  # time on ice "18:32" -> minutes
    if m:
        return round(int(m.group(1)) + int(m.group(2)) / 60, 2)
    try:
        return float(s) if "." in s else int(s)
    except (TypeError, ValueError):
        return None


def sides(summary):
    comps = ((summary.get("header") or {}).get("competitions") or [{}])[0].get("competitors") or []
    side = {}
    for c in comps:
        t = c.get("team") or {}
        side[str(t.get("id"))] = (c.get("homeAway"), t.get("abbreviation", "?"))
    return side


def opp_of(side, tid):
    home_away, _ = side.get(tid, ("", "?"))
    opp = next((abbr for k, (ha, abbr) in side.items() if k != tid), "?")
    return ("vs " if home_away == "home" else "@") + opp, side.get(tid, ("", "?"))[1]


def parse_basketball(summary, date):
    """[(name, team, game)] using NBA-style fields (PTS, REB, AST...)."""
    out, side = [], sides(summary)
    for team in (summary.get("boxscore") or {}).get("players") or []:
        tid = str((team.get("team") or {}).get("id"))
        opp_txt, abbr = opp_of(side, tid)
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
                    out.append((name, abbr, g))
    return out


def parse_generic(summary, date, prefix):
    """[(name, team, game)] keeping every stat ESPN reports, keyed by ESPN's own names.
    Football and baseball keys get the block name in front (passing.passingYards,
    pitching.strikeouts), since the same key can appear in more than one block."""
    out, side = [], sides(summary)
    for team in (summary.get("boxscore") or {}).get("players") or []:
        tid = str((team.get("team") or {}).get("id"))
        opp_txt, abbr = opp_of(side, tid)
        games = {}
        for block in team.get("statistics") or []:
            bname = block.get("name") or block.get("type") or "stats"
            keys = block.get("keys") or block.get("names") or block.get("labels") or []
            for a in block.get("athletes") or []:
                stats = a.get("stats") or []
                ath = a.get("athlete") or {}
                if a.get("didNotPlay") or not stats or len(stats) != len(keys) or not ath.get("displayName"):
                    continue
                aid = str(ath.get("id") or ath.get("displayName"))
                g = games.setdefault(aid, (ath.get("displayName"), {"date": date, "opp": opp_txt}))[1]
                for key, val in zip(keys, stats):
                    pre = (bname + ".") if prefix else ""
                    sval = str(val).strip()
                    parts_k = re.split(r"[/-]", key) if re.search(r"[/-]", key) else None
                    parts_v = re.split(r"(?<=\d)[/-](?=-?\d)", sval) if parts_k else None
                    if parts_k and parts_v and len(parts_k) == len(parts_v):
                        for k2, v2 in zip(parts_k, parts_v):
                            n = num(v2)
                            if n is not None:
                                g[pre + k2] = n
                    else:
                        n = num(sval)
                        if n is not None:
                            g[pre + key] = n
        for name, g in games.values():
            if len(g) > 2:
                out.append((name, abbr, g))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sport", default="nba", choices=sorted(SPORTS))
    ap.add_argument("--since", default=None)
    ap.add_argument("--games", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    path, extra, start_md, keep = SPORTS[a.sport]
    base = f"https://site.api.espn.com/apis/site/v2/sports/{path}"
    keep = a.games or keep
    out_path = a.out or ("gamelogs.json" if a.sport == "nba" else f"gamelogs_{a.sport}.json")
    today = dt.date.today()
    season = today.year if today.month >= int(start_md[:2]) else today.year - 1
    since = a.since or f"{season}-{start_md}"

    players, done = {}, set()
    if os.path.exists(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("source") == "espn" and old.get("sport", "nba") == a.sport:
                done = set(old.get("espnEvents", []))
                for p in old.get("gamelogs", []):
                    players[norm(p["player"]) + "|" + p.get("team", "")] = p
        except (ValueError, KeyError):
            pass

    start = dt.date.fromisoformat(since)
    print(f"Checking ESPN {a.sport.upper()} games from {start} to {today}...")
    new_games, day = 0, start
    while day <= today:
        sb = get(base, f"/scoreboard?dates={day:%Y%m%d}{extra}") or {}
        for ev in sb.get("events", []):
            eid = str(ev.get("id"))
            stype = str((ev.get("season") or {}).get("type"))
            completed = (((ev.get("status") or {}).get("type") or {}).get("completed"))
            if eid in done or not completed or stype not in ("2", "3"):
                continue  # already have it, not final yet, or preseason
            summary = get(base, f"/summary?event={eid}")
            if not summary:
                continue
            if a.sport in ("nba", "cbb"):
                rows = parse_basketball(summary, day.isoformat())
            else:
                rows = parse_generic(summary, day.isoformat(), prefix=a.sport in ("nfl", "cfb", "mlb"))
            for name, team, g in rows:
                k = norm(name) + "|" + team
                if k not in players and norm(name) + "|" in players:  # entry from before teams were saved
                    players[k] = players.pop(norm(name) + "|")
                    players[k]["team"] = team
                p = players.setdefault(k, {"player": name, "team": team, "games": []})
                p["games"] = [x for x in p["games"] if x.get("date") != g["date"]] + [g]
            done.add(eid)
            new_games += 1
            time.sleep(0.2)
        day += dt.timedelta(days=1)
        time.sleep(0.2)

    out = []
    for p in players.values():
        p["games"].sort(key=lambda x: x["date"])
        p["games"] = p["games"][-keep:]
        out.append(p)
    out.sort(key=lambda p: p["player"])

    if not out:
        sys.exit(f"No {a.sport.upper()} games found since {since} (the season may not have started). "
                 "The previous file was left unchanged.")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"source": "espn", "sport": a.sport,
                   "pulled": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                   "espnEvents": sorted(done), "gamelogs": out}, f, separators=(",", ":"))
    print(f"Added {new_games} new games. Saved {len(out)} players to {out_path}.")


if __name__ == "__main__":
    main()
