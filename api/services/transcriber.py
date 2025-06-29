import os
import re
import logging
import tempfile
import subprocess
from typing import Optional
from pathlib import Path

from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, VideoUnavailable
from youtube_transcript_api._errors import NoTranscriptFound
from xml.etree.ElementTree import ParseError

logger = logging.getLogger(__name__)

class VideoProcessingError(Exception):
    """Exception khusus untuk kegagalan pemrosesan video yang spesifik."""
    pass

class TranscriberService:
    def __init__(self):
        # ... (kode __init__ dari jawaban sebelumnya tidak perlu diubah)
        self._ffmpeg_available = self._check_command_availability("ffmpeg", "-version")
        self._yt_dlp_available = self._check_command_availability("yt-dlp", "--version")
        self.cookies_path = os.getenv("YOUTUBE_COOKIES_PATH")

        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            self.openai_client = OpenAI(api_key=openai_api_key, timeout=90.0)
            logger.info("OpenAI client initialized.")
        else:
            self.openai_client = None
            logger.warning("OPENAI_API_KEY not found. Whisper fallback will not be available.")

    def _check_command_availability(self, command: str, arg: str) -> bool:
        # ... (kode _check_command_availability dari jawaban sebelumnya tidak perlu diubah)
        try:
            subprocess.run([command, arg], capture_output=True, check=True, timeout=10)
            logger.info(f"'{command}' is available.")
            return True
        except Exception:
            logger.warning(f"'{command}' not found or not working.")
            return False


    def _extract_video_id(self, url: str) -> Optional[str]:
        # ... (kode _extract_video_id dari jawaban sebelumnya tidak perlu diubah)
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1).split('&')[0]
        return None


    async def get_transcript(self, youtube_url: str) -> str:
        # ... (kode get_transcript dari jawaban sebelumnya tidak perlu diubah)
        video_id = self._extract_video_id(youtube_url)
        if not video_id:
            raise ValueError("Invalid YouTube URL format.")

        logger.info(f"Processing video ID: {video_id}")

        try:
            transcript_text = await self._get_youtube_captions(video_id)
            if transcript_text and len(transcript_text.strip()) > 20:
                logger.info("Successfully fetched captions.")
                return transcript_text.strip()
        except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable, ParseError) as e:
            logger.warning(f"Could not fetch captions ({type(e).__name__}). Falling back to audio transcription.")
        
        return await self._extract_audio_and_transcribe_with_whisper(youtube_url)


    async def _get_youtube_captions(self, video_id: str) -> str:
        # ... (kode _get_youtube_captions dari jawaban sebelumnya tidak perlu diubah)
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['id', 'en'])
        except NoTranscriptFound:
            logger.info(f"No preferred transcript found. Checking all languages for {video_id}.")
            available = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript_obj = next(iter(available), None)
            if not transcript_obj:
                raise NoTranscriptFound(video_id, [], {})
            logger.info(f"Found transcript in '{transcript_obj.language_code}'.")
            transcript_list = transcript_obj.fetch()
        
        return " ".join(item.get('text', '') for item in transcript_list)


    async def _extract_audio_and_transcribe_with_whisper(self, youtube_url: str) -> str:
        if not self._ffmpeg_available or not self._yt_dlp_available:
            raise Exception("Audio transcription failed: Required tools (ffmpeg, yt-dlp) are not installed.")
        if not self.openai_client:
            raise Exception("Audio transcription failed: OpenAI API is not configured.")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_template = Path(temp_dir) / "audio"
            cmd = [
                "yt-dlp", "--extract-audio", "--audio-format", "mp3",
                "--no-playlist", "--output", f"{output_template}.%(ext)s",
            ]
            
            if self.cookies_path and Path(self.cookies_path).exists():
                logger.info(f"Using cookies from: {self.cookies_path}")
                cmd.extend(["--cookies", self.cookies_path])
            
            cmd.append(youtube_url)

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                stderr_lower = result.stderr.lower()
                # --- PERUBAHAN DI SINI ---
                if "requested format is not available" in stderr_lower:
                    logger.error("yt-dlp failed: Audio format not available for this video.")
                    raise VideoProcessingError("No downloadable audio format was found for this video. It might be a livestream, a premiere, or protected.")
                elif "sign in to confirm" in stderr_lower or "403" in stderr_lower:
                    logger.error("YouTube download blocked (bot detection).")
                    raise VideoProcessingError("YouTube blocked the download, suspecting automation. Please ensure your cookies.txt file is fresh and valid.")
                else:
                    logger.error(f"yt-dlp failed with an unknown error. Stderr: {result.stderr}")
                    raise Exception("Failed to extract audio due to an unknown yt-dlp error.")

            audio_path = Path(f"{output_template}.mp3")
            if not audio_path.exists():
                raise FileNotFoundError("Audio file was not created by yt-dlp.")
            
            with open(audio_path, "rb") as audio_file:
                transcription = self.openai_client.audio.transcriptions.create(
                    model="whisper-1", file=audio_file
                )
            
            return transcription.text.strip()