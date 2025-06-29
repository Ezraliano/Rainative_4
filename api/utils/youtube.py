import httpx
import re
import logging
from typing import Optional
from models.schemas import VideoMetadata
from datetime import datetime
import os

logger = logging.getLogger(__name__)

# Menggunakan konstanta di level modul untuk menghindari masalah state
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
BASE_URL = "https://www.googleapis.com/youtube/v3"

def extract_video_id(youtube_url: str) -> Optional[str]:
    """Mengekstrak ID video dari URL YouTube."""
    if not isinstance(youtube_url, str):
        return None
    
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)',
        r'youtube\.com\/watch\?.*v=([^&\n?#]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, youtube_url)
        if match:
            # Mengembalikan grup pertama yang cocok (ID video)
            return match.group(1)
    return None

def _parse_duration(duration_str: str) -> int:
    """Mengurai durasi ISO 8601 menjadi detik."""
    if not duration_str or not duration_str.startswith('PT'):
        return 0
    
    duration_str = duration_str[2:]
    total_seconds = 0
    time_matches = re.match(r'(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    
    if not time_matches:
        return 0
        
    hours, minutes, seconds = time_matches.groups()
    total_seconds += int(hours) * 3600 if hours else 0
    total_seconds += int(minutes) * 60 if minutes else 0
    total_seconds += int(seconds) if seconds else 0
    return total_seconds

async def get_video_metadata(youtube_url: str) -> Optional[VideoMetadata]:
    """Mengambil metadata video dari YouTube API."""
    video_id = extract_video_id(youtube_url)
    if not video_id:
        logger.error(f"URL YouTube tidak valid atau ID video tidak dapat diekstrak: {youtube_url}")
        return None

    if not YOUTUBE_API_KEY:
        logger.error("Variabel lingkungan YOUTUBE_API_KEY tidak diatur.")
        raise Exception("Kunci API YouTube tidak dikonfigurasi di server.")

    # URL dan parameter untuk permintaan API
    api_url = f"{BASE_URL}/videos"
    params = {
        "part": "snippet,statistics,contentDetails",
        "id": video_id,
        "key": YOUTUBE_API_KEY
    }

    try:
        async with httpx.AsyncClient() as client:
            logger.info(f"Mengambil metadata dari URL: {api_url} untuk video_id: {video_id}")
            response = await client.get(api_url, params=params)
            response.raise_for_status()  # Akan raise exception untuk status 4xx/5xx
            data = response.json()
    except httpx.RequestError as e:
        logger.error(f"Permintaan HTTP gagal saat mengambil metadata video: {e}")
        return None
    except Exception as e:
        logger.error(f"Terjadi kesalahan tak terduga saat mengambil metadata video: {e}")
        return None

    if not data.get("items"):
        logger.warning(f"Tidak ada data video yang ditemukan untuk ID: {video_id}")
        return None

    # Ekstrak data dari respons JSON
    item = data["items"][0]
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    content_details = item.get("contentDetails", {})

    return VideoMetadata(
        title=snippet.get("title", "No Title"),
        duration=_parse_duration(content_details.get("duration")),
        thumbnail_url=snippet.get("thumbnails", {}).get("high", {}).get("url"),
        channel_name=snippet.get("channelTitle", "Unknown Channel"),
        view_count=int(statistics.get("viewCount", 0)),
        like_count=int(statistics.get("likeCount", 0)),
        published_at=datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")) if "publishedAt" in snippet else None,
        description=snippet.get("description", "")
    )