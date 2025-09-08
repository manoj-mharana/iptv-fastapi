from fastapi import FastAPI, Response
import subprocess
import json
import os

app = FastAPI()

# channels.json se channel list load karega
with open("channels.json", "r", encoding="utf-8") as f:
    CHANNELS = json.load(f)

def generate_m3u():
    lines = ["#EXTM3U"]
    for name, url in CHANNELS.items():
        try:
            # YouTube se direct stream URL nikalna
            result = subprocess.run(
                ["yt-dlp", "-g", url],
                capture_output=True,
                text=True,
                timeout=30
            )
            stream_url = result.stdout.strip().split("\n")[-1]
            if stream_url.startswith("http"):
                lines.append(f'#EXTINF:-1 tvg-logo="", {name}')
                lines.append(stream_url)
        except Exception as e:
            print(f"Error for {name}: {e}")
    return "\n".join(lines)

@app.get("/")
def home():
    return {"status": "running", "total_channels": len(CHANNELS)}

@app.get("/playlist.m3u")
def playlist():
    m3u_data = generate_m3u()
    return Response(content=m3u_data, media_type="audio/x-mpegurl")
