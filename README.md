# Low Line Finder

A single-page web app that ranks pick'em player props (PrizePicks, Underdog and similar) by how often each player has cleared the line in recent games. It flags lines that sit below a player's recent average.

## Features

- **Prop board** with filters for sport, stat, standard lines only, low lines only and minimum over probability
- **Bar chart on every card**: one bar per recent game (L5 / L10 / L15 / L20), with the opponent and date, a dashed line at the prop line, and green or red for over or under
- **Over probability** from a recency-weighted average, the game-to-game spread and the recent hit rate
- **Slip builder** with combined odds, break-even rate per pick and expected return, using payout multipliers you can edit
- **One game log per player fills every category**: Points, Rebounds, Assists, PRA and the other combos, 3-PT Made, Steals, Blocks, Turnovers, Fantasy Score and more

Everything runs in the browser. Your slate and game logs are saved in that browser's local storage.

## Use it

Open `index.html` in a browser, or publish it with GitHub Pages (Settings → Pages → Deploy from branch → `main` / root).

### 1. Import a slate

Click **Import slate** and paste either:

- **PrizePicks JSON**: open `https://api.prizepicks.com/projections?league_id=7&per_page=250` (NBA) in your browser, select all, copy and paste it in.
- **CSV**: `player,team,opp,sport,stat,line,games`, where `games` is optional recent results separated by spaces, oldest to newest.

### Catch new and moved lines

Every time you import or refresh the slate, the app compares it with the previous one:

- **New**: the line appeared since your last import (the tag stays for 2 hours)
- **▼ was 25.5**: the line dropped, which helps an over
- **▲ was 23.5**: the line was raised

Sort by **Newest or just moved**, or tick **New or moved (last 2 hrs)**, to see fresh lines first.

### Automatic PrizePicks lines

`fetch_prizepicks.py` pulls the current board (built-in Python modules only) and writes `prizepicks.json`. It keeps a history between runs, so lines carry their **New** and **was 24.5** tags even if you weren't watching when they changed.

```
python fetch_prizepicks.py                       # NBA, writes prizepicks.json
python fetch_prizepicks.py --leagues 7,9         # NBA and NFL
python fetch_prizepicks.py --list              # every league id PrizePicks has right now
```

Load the file with **Import slate → Load prizepicks.json**.

`.github/workflows/update-prizepicks.yml` runs it every 10 minutes from about 8 AM to midnight Eastern (GitHub sometimes starts scheduled runs a few minutes late) and saves `data/prizepicks.json`. The GitHub Pages site loads that file on its own and checks for a newer one every 2 minutes while it's open. You can also start a run from **Actions → Update PrizePicks lines → Run workflow**.

PrizePicks blocks many cloud servers and its terms restrict automated access. If the workflow fails with "blocked", the last good file stays in place; run the script from home or paste the feed instead.

**Check for new lines** loads the newest lines your GitHub workflow saved. Only if there are none does it try PrizePicks directly, which PrizePicks usually blocks. If it doesn't, paste the feed into **Import slate**, and the new/moved tracking works the same way. PrizePicks' terms restrict automated access, so keep auto-refresh intervals reasonable.

### 2. Add game logs (NBA)

Run the script on your computer. It uses only Python's built-in modules, so there's nothing to install.

```
python fetch_gamelogs_nba.py
```

It downloads this season's regular-season game logs for every NBA player from NBA.com and writes `gamelogs.json`. In the app, click **Load gamelogs.json** and choose that file.

Options:

```
python fetch_gamelogs_nba.py players.txt   # only the names in players.txt (one per line)
python fetch_gamelogs_nba.py --games 10    # keep fewer games per player
python fetch_gamelogs_nba.py --season 2026-27
```

### Automatic daily updates (GitHub Pages)

`.github/workflows/update-gamelogs.yml` runs `fetch_gamelogs_espn.py` every morning (NBA.com doesn't answer GitHub's servers, so the workflow builds the logs from ESPN box scores instead) at about 6:17 AM Eastern and saves the result to `data/gamelogs.json`. When the app is served from GitHub Pages, it loads that file by itself on every visit, and the banner shows when the logs were last updated.

- Run it any time from the **Actions** tab → **Update NBA game logs** → **Run workflow**.
- If a run fails, the previous day's file stays in place, and you can run either script on your own computer and use **Load gamelogs.json** instead.
- The PrizePicks workflow is turned off because PrizePicks blocks GitHub's servers. Paste the feed into **Import slate**, or run `fetch_prizepicks.py` at home and use **Load prizepicks.json**.
- GitHub turns off scheduled workflows in repositories with no activity for 60 days. If that happens, re-enable it in the Actions tab.

You can also paste a game log copied from Basketball-Reference (Share & Export → Get table as CSV), ESPN or NBA.com into **Add game logs**.

## Notes

- NBA.com's stats feed is unofficial and sometimes slows down or blocks requests, especially from VPNs. If the script fails, wait a few minutes and try again.
- The model doesn't know about injuries, minutes changes, matchups or line moves. Treat a high score as a reason to look closer, not a sure thing.
- For research and entertainment. Check that pick'em contests are legal where you live, and set a budget before you play. If gambling stops being fun, call or text 1-800-GAMBLER.
