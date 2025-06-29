import httpx
import re
import logging
from typing import Optional
from models.schemas import VideoMetadata
from datetime import datetime, timedelta
import os

logger = logging.getLogger(__name__)

class YouTubeUtils:
    """
    Utility class for YouTube-related operations.
    """
    
    def __init__(self):
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY")
        self.base_url = "https://www.googleapis.com/youtube/v3"
        
    def extract_video_id(self, youtube_url: str) -> Optional[str]:
        """
        Extract video ID from YouTube URL.
        """
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)',
            r'youtube\.com\/watch\?.*v=([^&\n?#]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, youtube_url)
            if match:
                return match.group(1)
        
        return None
    
    async def get_video_metadata(self, youtube_url: str) -> Optional[VideoMetadata]:
        """
        Get video metadata from YouTube API.
        """
        video_id = self.extract_video_id(youtube_url)
        if not video_id:
            logger.error(f"Invalid YouTube URL: {youtube_url}")
            return None
        
        logger.info(f"Getting metadata for video ID: {video_id}")
        
        if not self.youtube_api_key:
            logger.error("YOUTUBE_API_KEY environment variable not set.")
            raise Exception("YouTube API key is not configured on the server.")
        
        try:
            return await self._fetch_from_youtube_api(video_id)
        except Exception as e:
            logger.error(f"Error getting video metadata: {str(e)}")
            return None
    
    async def _fetch_from_youtube_api(self, video_id: str) -> Optional[VideoMetadata]:
        """
        Fetch video metadata from YouTube Data API v3.
        """
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/videos"
            params = {
                "part": "snippet,statistics,contentDetails",
                "id": video_id,
                "key": self.youtube_api_key
            }
            
            response = await client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            if not data.get("items"):
                logger.warning(f"No video data found for ID: {video_id}")
                return None
            
            item = data["items"][0]
            snippet = item["snippet"]
            statistics = item.get("statistics", {})
            content_details = item["contentDetails"]
            
            duration_seconds = self._parse_duration(content_details.get("duration", "PT0S"))
            
            return VideoMetadata(
                title=snippet.get("title", "No Title"),
                duration=duration_seconds,
                thumbnail_url=snippet.get("thumbnails", {}).get("high", {}).get("url"),
                channel_name=snippet.get("channelTitle", "Unknown Channel"),
                view_count=int(statistics.get("viewCount", 0)),
                like_count=int(statistics.get("likeCount", 0)),
                published_at=datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")),
                description=snippet.get("description", "")
            )
    
    def _parse_duration(self, duration_str: str) -> int:
        """
        Parse ISO 8601 duration string to seconds. (e.g., "PT1H2M3S" -> 3723)
        """
        if not duration_str.startswith('PT'):
            return 0
            
        duration_str = duration_str[2:]
        total_seconds = 0
        
        time_matches = re.match(r'(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
        if not time_matches:
            return 0

        hours = int(time_matches.group(1)) if time_matches.group(1) else 0
        minutes = int(time_matches.group(2)) if time_matches.group(2) else 0
        seconds = int(time_matches.group(3)) if time_matches.group(3) else 0
        
        total_seconds = hours * 3600 + minutes * 60 + seconds
        return total_seconds
    
    def is_valid_youtube_url(self, url: str) -> bool:
        """
        Check if URL is a valid YouTube URL.
        """
        return self.extract_video_id(url) is not None