import os
import json
import time
import threading
import subprocess
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Response

# ---------- Settings ----------
CHANNELS_FILE = "channels.json"
CACHE_FILE = "cache.json"
COOKIES_ENV = "YT_COOKIES"
COOKIES_PATH = "/tmp/youtube_cookies.txt"

# हर कितने मिनट में fresh links निकालें (env से बदल सकते हो)
UPDATE_INTERVAL_MIN = int(os.getenv("UPDATE_INTERVAL_MIN", "20"))   # default: 20 min

# एक channel resolve करते समय max seconds
YT_DLP_TIMEOUT = int(os.getenv("YT_DLP_TIMEOUT", "45"))             # default: 45s
# --------------------------------

app = FastAPI()
_update_lock = threading.Lock()
_last_update_started_at = None
_last_update_finished_at = None


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


def _save_cache(cache_dict):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache_dict, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)


def _ensure_cookies_file():
    """Write cookies from env to a temp file (safe for public repos)."""
    cookies = os.getenv(COOKIES_ENV, "").strip()
    if cookies:
        try:
            with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                f.write(cookies)
            return True
        except Exception as e:
            print("⚠️ Failed writing cookies:", e)
    return False


def _yt_dlp_get_stream(url: str) -> str | None:
    """Return direct stream URL (first line of yt-dlp -g output), or None on failure."""
    cmd = ["yt-dlp", "-g", "-f", "best", url]
    if os.path.exists(COOKIES_PATH):
        cmd = ["yt-dlp", "-g", "-f", "best", "--cookies", COOKIES_PATH, url]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=YT_DLP_TIMEOUT,
            check=True
        )
        out = (proc.stdout or "").strip().splitlines()
        # Many times yt-dlp prints one line (HLS). If multiple, pick the first non-empty.
        for line in out:
            s = line.strip()
            if s:
                return s
    except subprocess.TimeoutExpired:
        print(f"⏱️ yt-dlp timeout for: {url}")
    except subprocess.CalledProcessError as e:
        print(f"❌ yt-dlp error for: {url} -> {e.stderr.strip() if e.stderr else e}")
    except Exception as e:
        print(f"❌ yt-dlp unexpected error for: {url} -> {e}")
    return None


def _update_once():
    global _last_update_started_at, _last_update_finished_at
    # Prevent overlapping runs
    if not _update_lock.acquire(blocking=False):
        return

    try:
        _last_update_started_at = _utc_now_iso()
        print(f"🔄 Update started at: {_last_update_started_at}")

        _ensure_cookies_file()
        channels = _load_channels()
        cache = _load_cache()

        for ch in channels:
            ch_id = ch["id"]
            name = ch.get("name", ch_id)
            src_url = ch["url"]
            print(f"▶ Resolving: {name}")

            stream = _yt_dlp_get_stream(src_url)
            entry = cache.get(ch_id, {})
            entry.update({
                "id": ch_id,
                "name": name,
                "source_url": src_url,
                "updated_at": _utc_now_iso(),
            })

            if stream:
                entry["stream_url"] = stream
                entry["ok"] = True
                entry["error"] = None
                print(f"✅ {name} resolved")
            else:
                # keep previous stream if exists, but mark stale
                prev = entry.get("stream_url")
                entry["ok"] = bool(prev)
                entry["error"] = "resolve_failed"
                print(f"⚠️ {name} failed; keeping previous: {bool(prev)}")

            cache[ch_id] = entry
            # Save incrementally so partial progress isn't lost
            _save_cache(cache)

        _last_update_finished_at = _utc_now_iso()
        print(f"✅ Update finished at: {_last_update_finished_at}")
    finally:
        _update_lock.release()


def _scheduler_loop():
    # Small initial delay so the app becomes responsive quickly
    time.sleep(5)
    while True:
        try:
            _update_once()
        except Exception as e:
            print("❌ Update cycle crashed:", e)
        time.sleep(max(60, UPDATE_INTERVAL_MIN * 60))


# Start background updater thread
threading.Thread(target=_scheduler_loop, daemon=True).start()


@app.get("/")
def home():
    return {
        "message": "✅ IPTV server running",
        "endpoints": {
            "playlist": "/playlist.m3u",
            "status": "/status"
        },
        "update_interval_min": UPDATE_INTERVAL_MIN
    }


@app.get("/status")
def status():
    channels = _load_channels()
    cache = _load_cache()
    resolved = [c for c in cache.values() if c.get("ok") and c.get("stream_url")]
    unresolved = [c for c in channels if c["id"] not in cache or not cache.get(c["id"], {}).get("stream_url")]

    return {
        "total_channels": len(channels),
        "resolved_count": len(resolved),
        "unresolved_ids": [c["id"] for c in unresolved],
        "last_update_started_at": _last_update_started_at,
        "last_update_finished_at": _last_update_finished_at,
        "next_update_after_min": UPDATE_INTERVAL_MIN
    }


@app.get("/playlist.m3u")
def playlist(all: int = 0):
    """
    Default: sirf resolved (cached) direct stream URLs include honge.
    /playlist.m3u?all=1 -> unresolved channels bhi show karega (unke YouTube page URL ke sath).
    """
    channels = _load_channels()
    cache = _load_cache()

    lines = ["#EXTM3U"]
    resolved_n = 0
    skipped_n = 0

    for ch in channels:
        ch_id = ch["id"]
        name = ch.get("name", ch_id)

        cached = cache.get(ch_id) or {}
        stream = cached.get("stream_url")

        if stream:
            lines.append(f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{name}" group-title="YouTube", {name}')
            lines.append(stream)
            resolved_n += 1
        else:
            if all:
                # include original page url (most IPTV players won't play it, but user asked to include all)
                lines.append(f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{name}" group-title="YouTube (unresolved)", {name} (unresolved)')
                lines.append(ch["url"])
            else:
                # skip unresolved to avoid broken channels
                skipped_n += 1

    # helpful comments at the end
    lines.append(f"# Resolved: {resolved_n} | Skipped (unresolved): {skipped_n}")
    m3u = "\n".join(lines) + "\n"
    return Response(content=m3u, media_type="audio/x-mpegurl")
