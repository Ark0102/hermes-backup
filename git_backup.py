#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Git auto-backup: stage .py files in C:\Users\Ark\bin\, commit, push to GitHub.
"""
import subprocess
import sys
from pathlib import Path
from datetime import datetime

BIN_DIR = Path(r"C:\Users\Ark\bin")
LOG_FILE = BIN_DIR / "backup.log"


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, cwd=None, check=False):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, check=False)
    if r.returncode != 0:
        out = (r.stdout or r.stderr).strip()
        if check:
            raise RuntimeError(f"command failed: {cmd}\n{out[-500:]}")
    return r


def main():
    log("=== git backup start ===")

    # add everything (gitignore filters out __pycache__, *.pyc, backup.log)
    run("git add -A", cwd=BIN_DIR)

    # check staged changes
    diff = run("git diff --cached --name-only", cwd=BIN_DIR)
    if not diff.stdout.strip():
        log("no changes, skip commit")
        return

    msg = f"backup {datetime.now():%Y-%m-%d %H:%M}"
    commit = run(f'git commit -m "{msg}"', cwd=BIN_DIR)
    if commit.returncode != 0:
        out = (commit.stdout or commit.stderr).strip()
        if "nothing to commit" in out.lower():
            log("nothing to commit")
            return
        log(f"commit failed: {out[-200:]}")
        return

    log(f"committed: {msg}")

    # push to GitHub
    push = run("git push", cwd=BIN_DIR, check=False)
    if push.returncode == 0:
        log("git push ok")
    else:
        out = (push.stdout or push.stderr).strip()
        log(f"git push failed: {out[-300:]}")

    log("=== backup done ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"backup error: {e}")
        sys.exit(1)
