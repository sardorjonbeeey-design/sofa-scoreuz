"""YouTube Transcript MCP server: captions first, Whisper fallback."""
import os
import re
import glob
import shutil
import tempfile
import subprocess

import httpx
from mcp.server.fastmcp import FastMCP
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig

TOKEN = os.environ.get("ACCESS_TOKEN", "change-me")
PORT = int(os.environ.get("PORT", "8000"))
PROXY_URL = os.environ.get("PROXY_URL") or None
WHISPER_KEY = os.environ.get("WHISPER_API_KEY", "")
WHISPER_BASE = os.environ.get("WHISPER_BASE_URL", "https://api.groq.com/openai/v1")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "whisper-large-v3-turbo")
CHUNK_SEC = 1200  # 20 min chunks stay well under the 25 MB upload limit
MAX_CHARS = 200_000

mcp = FastMCP(
    "youtube-transcript",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    streamable_http_path=f"/{TOKEN}/mcp",
)


def video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/|/v/)([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url.strip()):
        return url.strip()
    raise ValueError(f"Not a YouTube URL: {url}")


def fmt(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def from_captions(vid: str, timestamps: bool):
    api = YouTubeTranscriptApi(
        proxy_config=GenericProxyConfig(http_url=PROXY_URL, https_url=PROXY_URL) if PROXY_URL else None
    )
    tl = api.list(vid)
    items = list(tl)
    if not items:
        return None
    pick = next((t for t in items if not t.is_generated), items[0])
    data = pick.fetch()
    if timestamps:
        text = "\n".join(f"[{fmt(s.start)}] {s.text}" for s in data)
    else:
        text = " ".join(s.text for s in data)
    kind = "auto-captions" if pick.is_generated else "captions"
    return text, f"{kind} ({pick.language_code})"


def whisper_file(path: str) -> dict:
    with open(path, "rb") as f:
        r = httpx.post(
            f"{WHISPER_BASE}/audio/transcriptions",
            headers={"Authorization": f"Bearer {WHISPER_KEY}"},
            files={"file": (os.path.basename(path), f, "audio/ogg")},
            data={"model": WHISPER_MODEL, "response_format": "verbose_json"},
            timeout=600,
        )
    r.raise_for_status()
    return r.json()


def from_whisper(url: str, timestamps: bool):
    if not WHISPER_KEY:
        raise RuntimeError("No captions and WHISPER_API_KEY is not set.")
    tmp = tempfile.mkdtemp()
    try:
        cmd = ["yt-dlp", "-f", "bestaudio/best", "--no-playlist", "-o", f"{tmp}/a.%(ext)s", url]
        if PROXY_URL:
            cmd[1:1] = ["--proxy", PROXY_URL]
        cookies = os.environ.get("YT_COOKIES", "").strip()
        if cookies:
            cpath = f"{tmp}/cookies.txt"
            with open(cpath, "w") as f:
                f.write(cookies.replace("\\t", "\t").replace("\\n", "\n") + "\n")
            cmd[1:1] = ["--cookies", cpath]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        src = glob.glob(f"{tmp}/a.*")
        if p.returncode != 0 or not src:
            raise RuntimeError(f"Audio download failed: {p.stderr[-500:]}")
        subprocess.run(
            ["ffmpeg", "-y", "-i", src[0], "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k",
             "-f", "segment", "-segment_time", str(CHUNK_SEC), f"{tmp}/c%03d.ogg"],
            capture_output=True, check=True, timeout=900,
        )
        parts, lang = [], None
        for i, chunk in enumerate(sorted(glob.glob(f"{tmp}/c*.ogg"))):
            res = whisper_file(chunk)
            lang = lang or res.get("language")
            offset = i * CHUNK_SEC
            if timestamps and res.get("segments"):
                parts += [f"[{fmt(s['start'] + offset)}] {s['text'].strip()}" for s in res["segments"]]
            else:
                parts.append(res.get("text", "").strip())
        return ("\n" if timestamps else " ").join(parts), f"whisper ({lang or 'auto'})"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@mcp.tool()
def get_transcript(url: str, timestamps: bool = False, force_whisper: bool = False) -> str:
    """Get the spoken content of a YouTube video as text.

    Uses the video's captions when available; otherwise downloads the audio and
    transcribes it with Whisper. Works for any language.

    Args:
        url: YouTube link (watch, youtu.be, shorts, live) or 11-char video ID.
        timestamps: Prefix each line with [HH:MM:SS].
        force_whisper: Skip captions and always transcribe the audio.
    """
    vid = video_id(url)
    full = f"https://www.youtube.com/watch?v={vid}"
    result, cap_err = None, None
    if not force_whisper:
        try:
            result = from_captions(vid, timestamps)
        except Exception as e:  # no captions, blocked, etc.
            cap_err = f"{type(e).__name__}"
    if result is None:
        try:
            result = from_whisper(full, timestamps)
        except Exception as e:
            return f"ERROR: captions unavailable ({cap_err}); whisper failed: {e}"
    text, source = result
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n...[truncated]"
    return f"Source: {source}\nVideo: {full}\n\n{text}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
