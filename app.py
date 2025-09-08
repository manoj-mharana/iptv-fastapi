import os
import json
import subprocess
from fastapi import FastAPI, HTTPException, Response

app = FastAPI()

# Channels list load karo
with open("channels.json", "r", encoding="utf-8") as f:
    channels = json.load(f)

@app.get("/")
def home():
    return {"message": "✅ IPTV FastAPI is running!"}

@app.get("/channels")
def get_channels():
    return channels

@app.get("/play/{channel_id}")
def play_channel(channel_id: str):
    channel = next((c for c in channels if c["id"] == channel_id), None)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # yt-dlp command with cookies
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "-g",  # get direct video URL
                "--cookies", "cookies.txt",
                channel["url"]
            ],
            capture_output=True,
            text=True,
            check=True
        )
        stream_url = result.stdout.strip()
        return {"name": channel["name"], "url": stream_url}

    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Error: {e.stderr}")

@app.get("/playlist.m3u")
def generate_playlist():
    playlist = "#EXTM3U\n"
    for ch in channels:
        playlist += f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-name="{ch["name"]}" group-title="YouTube", {ch["name"]}\n'
        playlist += f'https://{os.getenv("RENDER_EXTERNAL_HOSTNAME", "iptv-fastapi.onrender.com")}/play/{ch["id"]}\n'
    return Response(content=playlist, media_type="audio/x-mpegurl")
