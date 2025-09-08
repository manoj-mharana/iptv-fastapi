from fastapi import FastAPI, Response
import json
import yt_dlp

app = FastAPI()

# चैनल list channels.json से load
with open("channels.json", "r", encoding="utf-8") as f:
    channels = json.load(f)

def get_stream_url(youtube_url: str) -> str:
    """YouTube live से direct .m3u8 stream निकाले"""
    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "nocheckcertificate": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            return info["url"]
    except Exception as e:
        print(f"⚠️ Error extracting stream for {youtube_url}: {e}")
        return None


@app.get("/")
def root():
    return {"message": "✅ IPTV FastAPI Server Running"}


@app.get("/playlist.m3u")
def playlist():
    """M3U playlist generate करके return करेगा"""
    m3u_content = "#EXTM3U\n"
    for ch in channels:
        stream_url = get_stream_url(ch["url"])
        if stream_url:
            m3u_content += f'#EXTINF:-1,{ch["name"]}\n{stream_url}\n'
    return Response(content=m3u_content, media_type="audio/x-mpegurl")
