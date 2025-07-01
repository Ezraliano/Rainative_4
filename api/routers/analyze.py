# api/routers/analyze.py

from fastapi import APIRouter, HTTPException
from models.schemas import AnalyzeRequest, AnalyzeResponse
from services.transcriber import TranscriberService, VideoProcessingError
from services.viral import ViralAnalysisService
from services.gemini_utils import (
    summarize_transcript, 
    explain_why_viral, 
    generate_content_idea
)
from utils import youtube
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Inisialisasi service
transcriber_service = TranscriberService()
viral_service = ViralAnalysisService()

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_content(request: AnalyzeRequest):
    if not request.youtube_url:
        raise HTTPException(status_code=400, detail="youtube_url must be provided")

    logger.info(f"Analyzing YouTube content: {request.youtube_url}")

    try:
        # 1. Dapatkan Metadata Video
        video_metadata = await youtube.get_video_metadata(request.youtube_url)
        if not video_metadata:
            raise HTTPException(status_code=404, detail="Invalid YouTube URL or video not found.")

        # 2. Dapatkan Transkrip (menggunakan service yang sudah diubah)
        transcript = ""
        try:
            transcript = await transcriber_service.get_transcript(request.youtube_url)
            if not transcript or len(transcript.strip()) < 20:
                raise HTTPException(status_code=422, detail="Transcript is too short or empty. Analysis cannot proceed.")
        except VideoProcessingError as e:
            # Menangkap error spesifik dari Pytube dan menampilkannya dengan jelas
            logger.error(f"Video processing failed for URL {request.youtube_url}: {e}")
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            logger.error(f"Transcript extraction failed unexpectedly: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="An unexpected error occurred while extracting video content.")

        # 3. Hasilkan Ringkasan dan Analisis dengan Gemini
        overall_summary = await summarize_transcript(transcript)
        viral_explanation = await explain_why_viral(
            video_metadata.title, 
            video_metadata.view_count or 0, 
            video_metadata.like_count or 0, 
            overall_summary
        )
        recommendations = await generate_content_idea("general", overall_summary, viral_explanation)
        
        # 4. Hitung Skor Viral
        viral_score = await viral_service.calculate_viral_score(
            transcript,
            video_metadata.title,
            video_metadata.view_count or 0,
            video_metadata.like_count or 0
        )
        
        # 5. Tentukan Label Viral
        if viral_score >= 80:
            viral_label = "Very High Potential"
        elif viral_score >= 60:
            viral_label = "Good Potential"
        else:
            viral_label = "Needs Improvement"
        
        # Placeholder untuk ringkasan timeline (bisa diimplementasikan nanti)
        timeline_summary = []

        # 6. Kembalikan Respons Lengkap
        return AnalyzeResponse(
            video_metadata=video_metadata,
            summary=overall_summary,
            timeline_summary=timeline_summary,
            viral_score=viral_score,
            viral_label=viral_label,
            viral_explanation=viral_explanation,
            recommendations=recommendations,
        )

    except HTTPException:
        raise # Lemparkan kembali HTTPException agar ditangani oleh FastAPI
    except Exception as e:
        logger.error(f"An unexpected server error occurred during analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred on the server.")