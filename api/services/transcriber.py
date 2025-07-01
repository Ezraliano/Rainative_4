# api/services/transcriber.py

import os
import re
import logging
import tempfile
import subprocess
from typing import Optional
from pathlib import Path

from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, VideoUnavailable

logger = logging.getLogger(__name__)

class VideoProcessingError(Exception):
    """Exception khusus untuk kegagalan pemrosesan video yang spesifik."""
    pass

class TranscriberService:
    def __init__(self):
        """Inisialisasi service dan client OpenAI."""
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            self.openai_client = OpenAI(api_key=openai_api_key, timeout=120.0)
            logger.info("OpenAI client initialized.")
        else:
            self.openai_client = None
            logger.warning("OPENAI_API_KEY not found. Whisper transcription will not be available.")
        
        self.cookies_path = os.getenv("YOUTUBE_COOKIES_PATH", "./cookies.txt")

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Mengekstrak ID video dari URL YouTube."""
        patterns = [r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1).split('&')[0]
        return None

    async def get_transcript(self, youtube_url: str) -> str:
        """
        Mendapatkan transkrip dengan strategi 2 lapis:
        1. Coba ambil teks/caption resmi (metode tercepat).
        2. Jika gagal, unduh audio dengan yt-dlp (metode paling andal) dan transkripsi.
        """
        video_id = self._extract_video_id(youtube_url)
        if not video_id:
            raise ValueError("Invalid YouTube URL format.")
            
        logger.info(f"Processing video ID: {video_id}")

        # --- LAPISAN 1: Coba Ambil Teks Resmi ---
        try:
            logger.info("Layer 1: Attempting to fetch official transcript.")
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['id', 'en'])
            transcript_text = " ".join(item.get('text', '') for item in transcript_list)
            if len(transcript_text.strip()) > 20:
                logger.info("Layer 1 Succeeded: Found official transcript.")
                return transcript_text.strip()
        except Exception as e:
            logger.warning(f"Layer 1 Failed: Could not fetch official transcript ({type(e).__name__}). Falling back to audio download.")

        # --- LAPISAN 2: Unduh dengan yt-dlp dan Transkripsi ---
        return await self._download_and_transcribe_with_yt_dlp(youtube_url)

    async def _download_and_transcribe_with_yt_dlp(self, youtube_url: str) -> str:
        """Mengunduh audio menggunakan yt-dlp dan mentranskripsikannya dengan Whisper."""
        if not self.openai_client:
            raise VideoProcessingError("Cannot transcribe audio: OpenAI API key is not configured.")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            output_template = temp_path / "audio"
            
            cmd = [
                "yt-dlp",
                "--extract-audio",
                "--audio-format", "mp3",
                "--no-playlist",
                "--output", f"{output_template}.%(ext)s"
            ]

            # Logika krusial untuk menggunakan cookies
            if Path(self.cookies_path).exists():
                logger.info(f"Using cookies file found at: {self.cookies_path}")
                cmd.extend(["--cookies", self.cookies_path])
            else:
                logger.warning(f"Cookies file not found at '{self.cookies_path}'. Download may be blocked by YouTube.")

            cmd.append(youtube_url)
            
            try:
                logger.info("Layer 2: Attempting audio download with yt-dlp.")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)

                # Analisis hasil dari yt-dlp
                if result.returncode != 0:
                    stderr = result.stderr.lower()
                    # Memberikan pesan eror yang spesifik dan solutif
                    if "sign in to confirm" in stderr or "confirm you’re not a bot" in stderr or "403" in stderr:
                        logger.error("yt-dlp failed due to bot detection.")
                        raise VideoProcessingError("YouTube blocked the download, suspecting automation. Please generate a fresh 'cookies.txt' file and place it in the 'api' directory.")
                    else:
                        logger.error(f"yt-dlp failed with an unknown error. Stderr: {result.stderr}")
                        raise VideoProcessingError(f"Failed to download audio. yt-dlp error: {result.stderr[:200]}")

                audio_path = Path(f"{output_template}.mp3")
                if not audio_path.exists():
                    raise FileNotFoundError("Audio file was not created by yt-dlp despite a successful run.")
                
                # Proses Transkripsi
                logger.info(f"Audio downloaded successfully. Transcribing file: {audio_path}")
                with open(audio_path, "rb") as audio_file:
                    transcription = self.openai_client.audio.transcriptions.create(model="whisper-1", file=audio_file)
                
                return transcription.text.strip()

            except Exception as e:
                if isinstance(e, VideoProcessingError):
                    raise e # Lemparkan lagi eror yang sudah kita buat
                logger.error(f"An unexpected error occurred during yt-dlp processing: {e}", exc_info=True)
                raise VideoProcessingError("An unexpected error occurred while trying to download and transcribe the video.")