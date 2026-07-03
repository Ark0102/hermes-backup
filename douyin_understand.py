#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音视频理解工具（本地版）

两种用法：
  1. 自动提取（推荐）：直接传抖音链接
     python douyin_understand.py "https://v.douyin.com/xxxxx/"

  2. 手动模式：传真实 mp4 地址（向后兼容）
     python douyin_understand.py --video-url "真实地址" --title "标题" --aweme-id "id" --author "作者"

前置条件：
- Edge 以 --remote-debugging-port=9222 启动（双击桌面"启动Edge调试.bat"）
- Edge 已登录抖音账号
- ffmpeg 在 PATH 中
- faster-whisper-small 模型可加载

输出：D:\采集数据\抖音\{标题}_{aweme_id}\
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

from faster_whisper import WhisperModel

# ==================== 配置 ====================
WHISPER_MODEL_SIZE = "Systran/faster-whisper-small"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
SHORT_VIDEO_LIMIT = 180
SHORT_VIDEO_FRAMES = 8
LONG_VIDEO_MAX_FRAMES = 30
OUTPUT_BASE = Path(r"D:\采集数据\抖音")


# ==================== 工具 ====================
def run(cmd, check=True):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)


# ==================== 步骤1: 提取真实视频地址 ====================
async def extract_douyin_info(video_url: str) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("playwright 未安装，请运行: pip install playwright")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()

        print(f"[1/4] 打开抖音页面...", flush=True)
        await page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        title = await page.title()
        print(f"       页面标题: {title}", flush=True)

        real_url = ""
        aweme_id = ""
        author = ""

        async def handle_response(response):
            nonlocal real_url, aweme_id, author
            if "aweme/v1/web/aweme/detail" in response.url and not real_url:
                try:
                    body = await response.json()
                    aweme = body.get("aweme_detail", {})
                    video_info = aweme.get("video", {})
                    play_addr = video_info.get("play_addr", {})
                    url_list = play_addr.get("url_list", [])
                    if url_list:
                        real_url = url_list[0]
                    aweme_id = str(aweme.get("aweme_id", ""))
                    author = aweme.get("author", {}).get("nickname", "")
                    desc = aweme.get("desc", "")
                    if desc:
                        title = desc[:50]
                except Exception:
                    pass

        page.on("response", handle_response)
        await page.wait_for_timeout(5000)

        if not real_url:
            print("       从响应未直接抓到，尝试页面 script...", flush=True)
            scripts = await page.query_selector_all("script")
            for script in scripts:
                try:
                    content = await script.inner_text()
                    if "play_addr" in content:
                        match = re.search(r'"url_list":\["([^"]+)"', content)
                        if match:
                            real_url = match.group(1)
                            break
                except Exception:
                    continue

        if not real_url:
            print("       刷新页面重试...", flush=True)
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

        if not real_url:
            raise RuntimeError("未能提取到真实视频地址，请确认 Edge 已登录抖音")

        result = {
            "real_url": real_url,
            "aweme_id": aweme_id,
            "title": title,
            "author": author,
            "source_url": video_url,
        }
        print(f"       提取成功: title={title}, aweme_id={aweme_id}", flush=True)
        return result


# ==================== 步骤2: 下载视频 ====================
def download_video(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    script = out_path.parent / "_dl.py"
    script.write_text(
        f"import requests\n"
        f'url = r"""{url}"""\n'
        f"out = r'''{out_path}'''\n"
        f"r = requests.get(url, stream=True, timeout=120)\n"
        f"r.raise_for_status()\n"
        f"with open(out, 'wb') as f:\n"
        f"    for chunk in r.iter_content(1024*1024):\n"
        f"        f.write(chunk)\n",
        encoding="utf-8"
    )
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"下载失败: {r.stderr[-500:]}")
    if not out_path.exists() or out_path.stat().st_size < 1024:
        raise RuntimeError(f"下载完成但文件无效: {out_path}")
    print(f"[2/4] 视频已下载: {out_path.stat().st_size/1024/1024:.1f}MB", flush=True)
    return out_path


# ==================== 步骤3+4: 转写 + 自适应抽帧 ====================
def process_video(video_path: str, outdir: Path) -> tuple:
    print(f"[3/4] 处理视频...", flush=True)

    # 提取音频
    audio_path = outdir / "audio.wav"
    run(f'ffmpeg -i "{video_path}" -vn -ar 16000 -ac 1 -c:a pcm_s16le "{audio_path}" -y -loglevel error')
    print(f"       音频: {audio_path.stat().st_size/1024:.0f}KB", flush=True)

    # 转写
    print("       转写中...", flush=True)
    model = WhisperModel(WHISPER_MODEL_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200)
    )
    result_segments = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segments
    ]
    transcription = {
        "language": info.language,
        "duration": round(info.duration, 2),
        "model": WHISPER_MODEL_SIZE,
        "segments": result_segments
    }
    print(f"       转写完成: {len(result_segments)}段, 时长{info.duration:.1f}s", flush=True)

    # 自适应抽帧
    duration = transcription["duration"]
    if duration < SHORT_VIDEO_LIMIT:
        frame_count = SHORT_VIDEO_FRAMES
        times = [round(2 + (duration - 1 - 2) / SHORT_VIDEO_FRAMES * i, 2) for i in range(SHORT_VIDEO_FRAMES)]
    else:
        frame_count = min(LONG_VIDEO_MAX_FRAMES, max(SHORT_VIDEO_FRAMES, len(result_segments)))
        step = max(1, len(result_segments) // frame_count)
        times = []
        for idx in range(0, len(result_segments), step):
            if len(times) >= LONG_VIDEO_MAX_FRAMES:
                break
            seg = result_segments[idx]
            times.append(round((seg["start"] + seg["end"]) / 2, 2))

    print(f"[4/4] 抽帧: {len(times)}张 (时长{duration:.0f}s {'短视' if duration < 180 else '长视'})", flush=True)

    frames_dir = outdir / "frames"
    frames_dir.mkdir(exist_ok=True)
    frames = []
    for i, t in enumerate(times):
        frame_path = frames_dir / f"frame_{i:03d}.jpg"
        run(f'ffmpeg -ss {t:.2f} -i "{video_path}" -vframes 1 -q:v 2 -vf "scale=640:-1" "{frame_path}" -y -loglevel error', check=False)
        if frame_path.exists():
            frames.append({"time": t, "path": str(frame_path)})

    print(f"       实际抽到 {len(frames)} 帧", flush=True)
    return transcription, frames


# ==================== 主流程 ====================
def understand_douyin(video_url: str, title: str = "", aweme_id: str = "", author: str = ""):
    t0 = datetime.now()

    # 判断是抖音网页链接还是真实 mp4 地址
    is_douyin_link = "douyin.com" in video_url or "v.douyin.com" in video_url

    if is_douyin_link:
        print("检测到抖音链接，自动提取真实地址...", flush=True)
        info = asyncio.run(extract_douyin_info(video_url))
        real_url = info["real_url"]
        title = info["title"]
        aweme_id = info["aweme_id"]
        author = info.get("author", "")
        source_url = info["source_url"]
    else:
        print("直接下载模式...", flush=True)
        real_url = video_url
        source_url = ""

    safe_title = re.sub(r'[\\/:*?"<>|]', '_', title or 'untitled')
    folder_name = f"{safe_title}_{aweme_id}"
    outdir = OUTPUT_BASE / folder_name
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"\n输出目录: {outdir}\n", flush=True)

    video_path = outdir / "original.mp4"
    if not video_path.exists() or video_path.stat().st_size < 1024:
        download_video(real_url, video_path)
    else:
        print(f"[2/4] 视频已存在: {video_path}", flush=True)

    transcription, frames = process_video(str(video_path), outdir)

    result = {
        "source_url": source_url or video_url,
        "aweme_id": aweme_id,
        "title": title,
        "author": author,
        "video_path": str(video_path),
        "frames_dir": str(outdir / "frames"),
        "frames": frames,
        "audio_path": str(outdir / "audio.wav"),
        "transcription": transcription,
        "created_at": datetime.now().isoformat(),
    }

    result_path = outdir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    dt = (datetime.now() - t0).total_seconds()
    print(f"\n{'='*50}", flush=True)
    print(f"DONE! 耗时 {dt:.0f}s", flush=True)
    print(f"目录: {outdir}", flush=True)
    print(f"帧数: {len(frames)}", flush=True)
    print(f"字幕: {len(transcription['segments'])}段", flush=True)
    print(f"{'='*50}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抖音视频理解（本地版）")
    parser.add_argument("url", nargs="?", default="", help="抖音链接 或 真实视频地址")
    parser.add_argument("--video-url", default="", help="真实视频地址（手动模式）")
    parser.add_argument("--title", default="", help="视频标题（手动模式）")
    parser.add_argument("--aweme-id", default="", help="抖音 aweme_id（手动模式）")
    parser.add_argument("--author", default="", help="作者（手动模式）")
    args = parser.parse_args()

    target_url = args.url or args.video_url
    if not target_url:
        parser.print_help()
        sys.exit(1)

    if args.video_url:
        # 手动模式
        if not args.title or not args.aweme_id:
            print("手动模式需要 --title 和 --aweme-id", flush=True)
            sys.exit(1)
        understand_douyin(args.video_url, args.title, args.aweme_id, args.author)
    else:
        # 自动模式
        understand_douyin(target_url)
