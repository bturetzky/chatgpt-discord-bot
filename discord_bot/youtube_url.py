"""Validate and canonicalize public YouTube video links without network access."""
import re
from urllib.parse import parse_qs, urlsplit

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


def normalize_youtube_url(url):
    """Undo common Markdown/HTML ampersand escaping before strict URL validation."""
    if not isinstance(url, str):
        return None
    return url.strip().replace(r"\&", "&").replace("&amp;", "&")


def youtube_video_id(url):
    """Return the video ID for supported HTTPS links, or None for everything else."""
    try:
        parsed = urlsplit(normalize_youtube_url(url))
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443)):
            return None
        host = parsed.hostname
        parts = parsed.path.strip("/").split("/")
        if host == "youtu.be" and len(parts) == 1:
            video_id = parts[0]
        elif host in YOUTUBE_HOSTS and parsed.path == "/watch":
            values = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
            if len(values) != 1:
                return None
            video_id = values[0]
        elif host in YOUTUBE_HOSTS and len(parts) == 2 and parts[0] in ("shorts", "live", "embed"):
            video_id = parts[1]
        else:
            return None
        return video_id if VIDEO_ID.fullmatch(video_id) else None
    except (TypeError, ValueError):
        return None


def canonical_youtube_url(video_id):
    if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
        raise ValueError("Invalid YouTube video ID")
    return "https://www.youtube.com/watch?v=" + video_id
