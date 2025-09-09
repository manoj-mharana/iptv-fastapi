from fastapi import FastAPI, Response
import subprocess, json, os, time

app = FastAPI()

CHANNELS_FILE = "channels.json"
COOKIES_FILE = "cookies.txt"
CACHE = {}
LAST_UPDATE = 0
UPDATE_INTERVAL = 20 * 60  # 20 minutes

def load_channels():
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def resolve_channel(url):
    try:
        result = subprocess.run(
            ["yt-dlp", "--cookies", COOKIES_FILE,
             "--geo-bypass", "--no-warnings",
             "--get-url", url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"⏱️ Timeout for {url}")
    return None

def update_cache():
    global CACHE, LAST_UPDATE
    channels = load_channels()
    new_cache = {}
    for ch in channels:
        print(f"▶ Resolving: {ch['name']}")
        stream_url = resolve_channel(ch["url"])
        if stream_url:
            new_cache[ch["id"]] = {"name": ch["name"], "url": stream_url}
            print(f"✅ {ch['name']} resolved")
        else:
            if ch["id"] in CACHE:
                new_cache[ch["id"]] = CACHE[ch["id"]]
                print(f"⚠️ {ch['name']} failed; keeping previous")
            else:
                print(f"❌ {ch['name']} failed, no cache")
    CACHE = new_cache
    LAST_UPDATE = time.time()

@app.on_event("startup")
def startup_event():
    update_cache()

@app.get("/")
def root():
    return {"message": "IPTV FastAPI is running!"}

@app.get("/playlist.m3u")
def playlist():
    if time.time() - LAST_UPDATE > UPDATE_INTERVAL:
        update_cache()
    m3u = "#EXTM3U\n"
    for ch_id, ch in CACHE.items():
        m3u += f"#EXTINF:-1,{ch['name']}\n{ch['url']}\n"
    return Response(content=m3u, media_type="audio/x-mpegurl")

@app.get("/status")
def status():
    return {
        "total_channels": len(load_channels()),
        "resolved_count": len(CACHE),
        "channels": list(CACHE.keys()),
        "last_update": LAST_UPDATE
    }
