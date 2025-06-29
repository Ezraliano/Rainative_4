import os
import re
import logging
import tempfile
import subprocess
from typing import Optional
from pathlib import Path

# Import OpenAI client and specific error types
from openai import OpenAI, APIConnectionError, RateLimitError, APIStatusError 
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled, VideoUnavailable
from xml.etree.ElementTree import ParseError

logger = logging.getLogger(__name__)

class TranscriberService:
    """
    Service for transcribing YouTube videos using youtube-transcript-api
    with a fallback to OpenAI's Whisper API.
    """
    
    def __init__(self):
        """
        Initializes the service by checking for ffmpeg and setting up the OpenAI client.
        """
        self._ffmpeg_available = self._check_ffmpeg_availability()
        self._yt_dlp_available = self._check_yt_dlp_availability()
        
        # Initialize OpenAI client
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            try:
                self.openai_client = OpenAI(
                    api_key=openai_api_key,
                    timeout=60.0  # Increased timeout for audio processing
                )
                logger.info("OpenAI client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                self.openai_client = None
        else:
            logger.warning("OPENAI_API_KEY not found. Whisper transcription will not be available.")
            self.openai_client = None
        
    def _check_ffmpeg_availability(self) -> bool:
        """Check if ffmpeg is available on the system."""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"], 
                capture_output=True, 
                text=True, 
                check=True,
                timeout=10
            )
            logger.info("ffmpeg is available")
            return True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning(f"ffmpeg not found or not working: {e}")
            return False
    
    def _check_yt_dlp_availability(self) -> bool:
        """Check if yt-dlp is available on the system."""
        try:
            result = subprocess.run(
                ["yt-dlp", "--version"], 
                capture_output=True, 
                text=True, 
                check=True,
                timeout=10
            )
            logger.info("yt-dlp is available")
            return True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning(f"yt-dlp not found or not working: {e}")
            return False
        
    def _extract_video_id(self, youtube_url: str) -> Optional[str]:
        """Extract video ID from various YouTube URL formats."""
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)',
            r'youtube\.com\/watch\?.*v=([^&\n?#]+)',
            r'youtube\.com\/v\/([^&\n?#]+)',
            r'youtube\.com\/shorts\/([^&\n?#]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, youtube_url)
            if match:
                video_id = match.group(1)
                # Clean up video ID (remove any extra parameters)
                video_id = re.sub(r'[^a-zA-Z0-9_-].*', '', video_id)
                return video_id
                
        logger.warning(f"Could not extract video ID from URL: {youtube_url}")
        return None

    async def get_transcript(self, youtube_url: str) -> str:
        """
        Get transcript from YouTube video using multiple fallback methods.
        
        Priority:
        1. YouTube auto-generated captions
        2. YouTube manual captions
        3. Audio extraction + Whisper transcription
        """
        try:
            video_id = self._extract_video_id(youtube_url)
            if not video_id:
                raise ValueError("Invalid YouTube URL format")

            logger.info(f"Attempting to fetch transcript for video ID: {video_id}")
            
            # Method 1: Try to get existing captions/subtitles
            try:
                transcript_text = await self._get_youtube_captions(video_id)
                if transcript_text and len(transcript_text.strip()) > 50:  # Ensure meaningful content
                    logger.info(f"Successfully fetched captions for video ID: {video_id}")
                    return transcript_text.strip()
                else:
                    logger.info("Captions found but content is too short, trying audio extraction")
            except (NoTranscriptFound, TranscriptsDisabled, ParseError) as e:
                logger.info(f"No captions available ({type(e).__name__}), falling back to audio transcription")
            
            # Method 2: Audio extraction + Whisper transcription
            if not self._ffmpeg_available:
                raise Exception("No captions available and ffmpeg is not installed. Please install ffmpeg to enable audio transcription.")
            
            if not self._yt_dlp_available:
                raise Exception("No captions available and yt-dlp is not installed. Please install yt-dlp to enable audio extraction.")
                
            if not self.openai_client:
                raise Exception("No captions available and OpenAI API is not configured. Please set OPENAI_API_KEY environment variable.")
            
            return await self._extract_audio_and_transcribe_with_whisper(youtube_url, video_id)
            
        except VideoUnavailable:
            logger.error(f"Video is unavailable or private: {youtube_url}")
            raise Exception("This video is not available, private, or has been removed.")
        except Exception as e:
            logger.error(f"Transcript extraction failed for {youtube_url}: {str(e)}", exc_info=True)
            raise

    async def _get_youtube_captions(self, video_id: str) -> str:
        """Get captions from YouTube using youtube-transcript-api."""
        try:
            # Try to get transcript in English first, then any available language
            transcript_list = YouTubeTranscriptApi.get_transcript(
                video_id, 
                languages=['en', 'en-US', 'en-GB']
            )
        except NoTranscriptFound:
            # If English not available, try any available language
            try:
                available_transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
                transcript = next(iter(available_transcripts))
                transcript_list = transcript.fetch()
            except Exception:
                raise NoTranscriptFound(video_id)
        
        if not transcript_list:
            raise NoTranscriptFound(video_id)
            
        # Combine all transcript segments
        transcript_text = " ".join([item.get('text', '') for item in transcript_list])
        return transcript_text

    async def _extract_audio_and_transcribe_with_whisper(self, youtube_url: str, video_id: str) -> str:
        """Extract audio from YouTube video and transcribe using OpenAI Whisper."""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path = Path(temp_dir) / f"{video_id}.mp3"
                
                # Enhanced yt-dlp command for better audio extraction
                cmd = [
                    "yt-dlp",
                    "--extract-audio",
                    "--audio-format", "mp3",
                    "--audio-quality", "0",  # Best quality
                    "--no-playlist",
                    "--no-warnings",
                    "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "--output", str(audio_path.with_suffix('.%(ext)s')),
                    youtube_url
                ]
                
                logger.info(f"Extracting audio from: {youtube_url}")
                result = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    timeout=300,  # 5 minutes timeout
                    cwd=temp_dir
                )
                
                if result.returncode != 0:
                    logger.error(f"yt-dlp stderr: {result.stderr}")
                    raise Exception(f"Failed to extract audio. yt-dlp error: {result.stderr}")

                # Find the actual audio file (yt-dlp might change the filename)
                audio_files = list(Path(temp_dir).glob("*.mp3"))
                if not audio_files:
                    raise FileNotFoundError("No audio file was created by yt-dlp")
                
                actual_audio_path = audio_files[0]
                file_size = actual_audio_path.stat().st_size
                
                logger.info(f"Audio extracted successfully. File size: {file_size / (1024*1024):.2f} MB")
                
                # Check file size limit (OpenAI has a 25MB limit)
                if file_size > 25 * 1024 * 1024:  # 25MB
                    logger.warning("Audio file is larger than 25MB, compressing...")
                    actual_audio_path = await self._compress_audio(actual_audio_path, temp_dir)
                
                # Transcribe with Whisper
                logger.info("Starting Whisper transcription...")
                
                with open(actual_audio_path, "rb") as audio_file:
                    transcription = self.openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        response_format="json",
                        language="en",  # Force English for better accuracy
                        prompt="This is a YouTube video transcript. Please transcribe accurately with proper punctuation."
                    )
                
                transcript_text = transcription.text
                if not transcript_text or len(transcript_text.strip()) < 10:
                    raise Exception("Whisper API returned empty or very short transcript")
                
                logger.info(f"Whisper transcription successful. Length: {len(transcript_text)} characters")
                return transcript_text.strip()

        except RateLimitError as e:
            logger.error(f"OpenAI API rate limit exceeded: {e}")
            raise Exception("OpenAI API rate limit exceeded. Please check your quota and try again later.")
        except APIConnectionError as e:
            logger.error(f"Failed to connect to OpenAI API: {e}")
            raise Exception("Could not connect to OpenAI API. Please check your internet connection.")
        except APIStatusError as e:
            logger.error(f"OpenAI API error: {e}")
            if e.status_code == 401:
                raise Exception("Invalid OpenAI API key. Please check your OPENAI_API_KEY environment variable.")
            elif e.status_code == 429:
                raise Exception("OpenAI API rate limit exceeded. Please try again later.")
            else:
                raise Exception(f"OpenAI API error: {e.status_code} - {e.response}")
        except subprocess.TimeoutExpired:
            logger.error("Audio extraction timed out")
            raise Exception("Audio extraction timed out. The video might be too long or unavailable.")
        except Exception as e:
            logger.error(f"Audio extraction/transcription error: {str(e)}", exc_info=True)
            raise Exception(f"Failed to transcribe audio: {str(e)}")

    async def _compress_audio(self, audio_path: Path, temp_dir: str) -> Path:
        """Compress audio file to reduce size for OpenAI API."""
        compressed_path = Path(temp_dir) / f"compressed_{audio_path.name}"
        
        try:
            cmd = [
                "ffmpeg",
                "-i", str(audio_path),
                "-ac", "1",  # Convert to mono
                "-ar", "16000",  # Reduce sample rate to 16kHz
                "-ab", "64k",  # Reduce bitrate to 64kbps
                "-y",  # Overwrite output file
                str(compressed_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                check=True
            )
            
            new_size = compressed_path.stat().st_size
            logger.info(f"Audio compressed. New size: {new_size / (1024*1024):.2f} MB")
            
            return compressed_path
            
        except Exception as e:
            logger.warning(f"Audio compression failed: {e}. Using original file.")
            return audio_path

    def get_supported_formats(self) -> dict:
        """Get information about supported formats and requirements."""
        return {
            "youtube_captions": True,
            "whisper_transcription": self.openai_client is not None,
            "ffmpeg_available": self._ffmpeg_available,
            "yt_dlp_available": self._yt_dlp_available,
            "requirements": {
                "ffmpeg": "Required for audio extraction",
                "yt-dlp": "Required for YouTube audio download", 
                "openai_api_key": "Required for Whisper transcription"
            }
        }