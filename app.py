import json
import subprocess
from fastapi import FastAPI, Response

app = FastAPI()

# Channels list load (YouTube live URLs store here)
with open("channels.json", "r", encoding="utf-8") as f:
    CHANNELS = json.load(f)

def get_stream_url(youtube_url: str):
    """Run yt-dlp to fetch fresh .m3u8 URL"""
    try:
        result = subprocess.check_output(
            ["yt-dlp", "-g", youtube_url],
            stderr=subprocess.STDOUT
        )
        return result.decode("utf-8").strip()
    except subprocess.CalledProcessError as e:
        print("yt-dlp error:", e.output.decode())
        return None

@app.get("/")
def root():
    return {"status": "ok", "channels": len(CHANNELS)}

@app.get("/status")
def status():
    return {"status": "running", "channels": [ch["name"] for ch in CHANNELS]}

@app.get("/playlist.m3u")
def playlist():
    lines = ["#EXTM3U"]

    for ch in CHANNELS:
        stream_url = get_stream_url(ch["url"])
        if stream_url:
            lines.append(f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-name="{ch["name"]}",{ch["name"]}')
            lines.append(stream_url)
        else:
            lines.append(f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-name="{ch["name"]}",{ch["name"]}')
            lines.append("")

    content = "\n".join(lines)
    return Response(content, media_type="application/x-mpegURL")
