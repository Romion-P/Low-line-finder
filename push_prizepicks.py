#!/usr/bin/env python3
"""
Run fetch_prizepicks.py on your own computer and upload the result to your
GitHub repo, so your Low Line Finder site gets fresh lines. Meant to be run
every 10 minutes by Windows Task Scheduler. Uses only Python's built-in modules.

Setup (once):
  1. Put this file and fetch_prizepicks.py in the same folder.
  2. Make a GitHub token: github.com/settings/personal-access-tokens/new
     - Repository access: Only select repositories -> your Low-line-finder repo
     - Permissions: Contents -> Read and write
  3. Save the token in a file named github_token.txt in the same folder
     (nothing else in the file). Never upload or share that file.
  4. Test it:   python push_prizepicks.py
  5. Schedule it (see README.md).

Each run writes a short note to push_log.txt in the same folder.

Options
  --repo Romion-P/Low-line-finder
  --leagues 7          PrizePicks league ids (run fetch_prizepicks.py --list)
"""
import argparse
import base64
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, "prizepicks.json")
LOG = os.path.join(HERE, "push_log.txt")
REMOTE_PATH = "data/prizepicks.json"


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M}  {msg}"
    print(line)
    try:
        old = open(LOG, encoding="utf-8").read().splitlines()[-300:] if os.path.exists(LOG) else []
        with open(LOG, "w", encoding="utf-8") as f:
            f.write("\n".join(old + [line]) + "\n")
    except OSError:
        pass


def token():
    p = os.path.join(HERE, "github_token.txt")
    t = open(p, encoding="utf-8-sig").read().strip() if os.path.exists(p) else ""
    if not t:
        t = os.environ.get("LLF_GITHUB_TOKEN", "").strip()
    if not t:
        log("No GitHub token. Put it in github_token.txt next to this script.")
        sys.exit(1)
    return t


def gh(method, url, tok, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None, headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "low-line-finder-uploader",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == "GET":
            return None
        detail = e.read().decode("utf-8", "replace")[:200]
        if e.code in (401, 403):
            log(f"GitHub refused the token (HTTP {e.code}). Check that it hasn't expired and has "
                f"Contents: Read and write on this repo. {detail}")
        else:
            log(f"GitHub upload failed (HTTP {e.code}): {detail}")
        sys.exit(1)
    except urllib.error.URLError as e:
        log(f"Couldn't reach GitHub ({e.reason}). Will try again next run.")
        sys.exit(1)


def lines_only(obj):
    """The part of the file that matters for deciding whether to upload."""
    return sorted((p.get("ppid"), p.get("line"), p.get("tier")) for p in (obj or {}).get("props", []))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="Romion-P/Low-line-finder")
    ap.add_argument("--leagues", default="7")
    a = ap.parse_args()
    os.chdir(HERE)

    # 1. Pull the lines from your own connection.
    r = subprocess.run([sys.executable, os.path.join(HERE, "fetch_prizepicks.py"),
                        "--leagues", a.leagues, "--out", LOCAL],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        log("PrizePicks: " + (r.stderr or r.stdout).strip().splitlines()[-1])
        sys.exit(1)
    with open(LOCAL, encoding="utf-8") as f:
        new = json.load(f)

    # 2. Upload only if lines changed, so the site isn't rebuilt for nothing.
    tok = token()
    api = f"https://api.github.com/repos/{a.repo}/contents/{REMOTE_PATH}"
    cur = gh("GET", api + "?ref=main", tok)
    sha = cur.get("sha") if cur else None
    if cur and cur.get("content"):
        try:
            if lines_only(json.loads(base64.b64decode(cur["content"]))) == lines_only(new):
                log(f"No line changes ({len(new['props'])} lines). Nothing uploaded.")
                return
        except ValueError:
            pass
    body = {"message": f"Update PrizePicks lines {dt.datetime.now():%Y-%m-%d %H:%M}",
            "content": base64.b64encode(json.dumps(new, separators=(",", ":")).encode()).decode(),
            "branch": "main"}
    if sha:
        body["sha"] = sha
    gh("PUT", api, tok, body)
    log(f"Uploaded {len(new['props'])} lines to {a.repo}.")


if __name__ == "__main__":
    main()
