import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
import yt_dlp

app = FastAPI()

# Channels.json load karo
with open("channels.json", "r", encoding="utf-8") as f:
    channels = json.load(f)


def get_stream_url(youtube_url: str):
    """
    YouTube se direct stream URL nikalta hai (cookies ke sath).
    Render me YT_COOKIES env variable set hona chahiye.
    """
    cookies_file = "cookies.txt"

    # Agar env me cookies available hain to ek baar file me likh do
    if os.getenv("YT_COOKIES"):
        with open(cookies_file, "w", encoding="utf-8") as f:
            f.write(os.getenv("YT_COOKIES"))

    ydl_opts = {
        "format": "best",
        "quiet": True,
        "cookies": cookies_file if os.getenv("YT_COOKIES") else None,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        return info["url"]


@app.get("/")
def home():
    return {"message": "✅ IPTV API is running! Use /channels to see list."}


@app.get("/channels")
def get_channels():
    """Sabhi channels ka list dega"""
    return channels


@app.get("/play/{channel_id}")
def play_channel(channel_id: str):
    """Channel ka direct playable stream URL return karega"""
    channel = next((c for c in channels if c["id"] == channel_id), None)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    url = channel["url"]

    # Agar YouTube link hai to cookies ke sath stream nikaalo
    if "youtube.com" in url or "youtu.be" in url:
        try:
            url = get_stream_url(url)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching YouTube stream: {str(e)}")

    return RedirectResponse(url)
