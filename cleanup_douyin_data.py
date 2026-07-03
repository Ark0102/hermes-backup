#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Cleanup douyin data folders older than 3 days from D:\采集数据\抖音\
Log to C:\Users\Ark\bin\cleanup.log
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(r"D:\采集数据\抖音")
LOG_FILE = Path(r"C:\Users\Ark\bin\cleanup.log")
RETENTION_DAYS = 3


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_dir_age_days(dirpath: Path) -> float:
    stat = dirpath.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime)
    return (datetime.now() - mtime).total_seconds() / 86400


def main():
    if not BASE_DIR.exists():
        log(f"directory not found: {BASE_DIR}")
        return

    threshold = datetime.now() - timedelta(days=RETENTION_DAYS)
    removed = []

    for entry in sorted(BASE_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in ("frames",):
            continue
        mtime = datetime.fromtimestamp(entry.stat().st_mtime)
        if mtime < threshold:
            try:
                size_mb = sum(
                    f.stat().st_size for f in entry.rglob("*") if f.is_file()
                ) / (1024 * 1024)
                log(f"删除: {entry.name} ({size_mb:.1f}MB, 修改于 {mtime:%Y-%m-%d})")
                # remove entire directory
                for sub in entry.rglob("*"):
                    if sub.is_file() or sub.is_symlink():
                        sub.unlink()
                    elif sub.is_dir():
                        sub.rmdir()
                entry.rmdir()
                removed.append(entry.name)
            except Exception as e:
                log(f"删除失败 {entry.name}: {e}")

    log(f"完成: 共删除 {len(removed)} 个过期文件夹 (>{RETENTION_DAYS}天)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"cleanup error: {e}")
        sys.exit(1)
