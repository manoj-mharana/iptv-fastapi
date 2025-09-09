import os
import json
import time
import threading
import subprocess
from datetime import datetime, timezone
from fastapi import FastAPI, Response

# ---------- CONFIG ----------
CHANNELS_FILE = "channels.json"
CACHE_FILE = "cache.json"
COOKIES_ENV = "YT_COOKIES"                 # Render env var name where you'll paste cookies.txt content
COOKIES_PATH = "/tmp/youtube_cookies.txt"  # runtime file path we will write cookies to
UPDATE_INTERVAL_MIN = int(os.getenv("UPDATE_INTERVAL_MIN", "15"))  # default 15 minutes
YT_DLP_TIMEOUT = int(os.getenv("YT_DLP_TIMEOUT", "30"))            # seconds per yt-dlp call
# ----------------------------

app = FastAPI()
_lock = threading.Lock()
_last_update_started = None
_last_update_finished = None

def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def _load_channels():
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_cache(cache):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)

def _write_cookies_file():
    """Write cookies from environment variable into a file. Return True if file exists+written."""
    cookies = os.getenv(COOKIES_ENV, "")
    if not cookies:
        print("⚠️ No YT_COOKIES env var found or empty.")
        return False
    try:
        # Ensure parent dir exists (we use /tmp so should exist)
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write(cookies)
        size = os.path.getsize(COOKIES_PATH)
        print(f"✅ Wrote cookies to {COOKIES_PATH} ({size} bytes)")
        return True
    except Exception as e:
        print("⚠️ Failed to write cookies file:", e)
        return False

def _yt_dlp_get_stream(url: str):
    """
    Return first direct stream URL (string) or None on failure.
    Uses cookies file if present.
    """
    cmd = ["yt-dlp", "-g", "-f", "best", url]
    if os.path.exists(COOKIES_PATH):
        cmd = ["yt-dlp", "--cookies", COOKIES_PATH, "-g", "-f", "best", url]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=YT_DLP_TIMEOUT,
            check=False
        )
        out = (proc.stdout or "").strip().splitlines()
        for line in out:
            s = line.strip()
            if s:
                return s
        # if no stdout, log stderr
        if proc.stderr:
            print("yt-dlp stderr:", proc.stderr.strip()[:800])
    except subprocess.TimeoutExpired:
        print(f"⏱️ yt-dlp timeout for: {url}")
    except Exception as e:
        print("❌ yt-dlp unexpected error:", e)
    return None

def _update_once():
    """One full run: resolve each channel sequentially and save cache incrementally."""
    global _last_update_started, _last_update_finished
    if not _lock.acquire(blocking=False):
        # already running
        return
    try:
        _last_update_started = _utc_now_iso()
        print("🔄 Update started at", _last_update_started)
        # ensure cookies file exists (if env provided)
        cookies_ok = _write_cookies_file()
        channels = _load_channels()
        cache = _load_cache()

        for ch in channels:
            ch_id = ch.get("id")
            name = ch.get("name", ch_id)
            src = ch.get("url")
            print(f"▶ Resolving: {name} -> {src}")
            stream = _yt_dlp_get_stream(src)
            entry = cache.get(ch_id, {})
            entry.setdefault("id", ch_id)
            entry.setdefault("name", name)
            entry["source_url"] = src
            entry["updated_at"] = _utc_now_iso()
            if stream:
                entry["stream_url"] = stream
                entry["ok"] = True
                entry["error"] = None
                print(f"✅ Resolved: {name}")
            else:
                # keep previous stream if present, else mark unresolved
                prev = entry.get("stream_url")
                entry["ok"] = bool(prev)
                entry["error"] = "resolve_failed" if not prev else "stale_kept"
                print(f"⚠️ {name} resolve failed; previous kept: {bool(prev)}")
            cache[ch_id] = entry
            # persist incrementally so progress isn't lost
            _save_cache(cache)
        _last_update_finished = _utc_now_iso()
        print("✅ Update finished at", _last_update_finished)
    finally:
        _lock.release()

def _scheduler_loop():
    # small delay then run forever
    time.sleep(2)
    while True:
        try:
            _update_once()
        except Exception as e:
            print("❌ Update cycle crashed:", e)
        time.sleep(max(60, UPDATE_INTERVAL_MIN * 60))

# start background thread
threading.Thread(target=_scheduler_loop, daemon=True).start()

@app.get("/")
def home():
    return {"message": "IPTV FastAPI running", "playlist": "/playlist.m3u", "status": "/status"}

@app.get("/status")
def status():
    channels = _load_channels()
    cache = _load_cache()
    resolved = [c for c in cache.values() if c.get("ok") and c.get("stream_url")]
    unresolved = [c["id"] for c in channels if c["id"] not in cache or not cache.get(c["id"], {}).get("stream_url")]
    cookies_present = bool(os.getenv(COOKIES_ENV, "").strip()) and os.path.exists(COOKIES_PATH)
    cookies_size = os.path.getsize(COOKIES_PATH) if os.path.exists(COOKIES_PATH) else 0
    return {
        "total_channels": len(channels),
        "resolved_count": len(resolved),
        "unresolved_ids": unresolved,
        "last_update_started_at": _last_update_started,
        "last_update_finished_at": _last_update_finished,
        "cookies_env_provided": bool(os.getenv(COOKIES_ENV, "").strip()),
        "cookies_file_present": cookies_present,
        "cookies_file_size_bytes": cookies_size,
        "update_interval_min": UPDATE_INTERVAL_MIN
    }

@app.get("/playlist.m3u")
def playlist(all: int = 0):
    """
    Serve M3U playlist built from cached resolved stream URLs.
    ?all=1 will include unresolved channels using their original URL (may not play).
    """
    channels = _load_channels()
    cache = _load_cache()
    lines = ["#EXTM3U"]
    for ch in channels:
        ch_id = ch["id"]
        name = ch.get("name", ch_id)
        cached = cache.get(ch_id, {})
        stream = cached.get("stream_url")
        if stream:
            lines.append(f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{name}" group-title="YouTube", {name}')
            lines.append(stream)
        else:
            if all:
                lines.append(f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{name}" group-title="YouTube (unresolved)", {name}')
                lines.append(ch.get("url"))
            else:
                # skip unresolved
                pass
    lines.append(f"# Resolved: {len([c for c in cache.values() if c.get('ok')])}")
    content = "\n".join(lines) + "\n"
    return Response(content=content, media_type="audio/x-mpegurl")
