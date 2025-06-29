from fastapi import APIRouter, HTTPException, BackgroundTasks
from models.schemas import AnalyzeRequest, AnalyzeResponse
from services.gemini_utils import (
    summarize_transcript,
    explain_why_viral,
    generate_content_idea,
    summarize_document
)
from services.transcriber import TranscriberService
from services.viral import ViralAnalysisService
# --- PERUBAHAN DI SINI ---
from utils import youtube # Impor modulnya
import logging

# Import specific exceptions for better error handling
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize services
transcriber_service = TranscriberService()
viral_service = ViralAnalysisService()
# --- PERUBAHAN DI SINI ---
# Hapus baris ini: youtube_utils = YouTubeUtils()

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_content(request: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Analyze YouTube video content or document for viral potential and generate recommendations.
    """
    try:
        if not request.youtube_url and not request.file_path:
            raise HTTPException(
                status_code=400,
                detail="Either youtube_url or file_path must be provided"
            )

        video_metadata = None
        timeline_summary = None
        doc_summary = None
        transcript = ""

        if request.youtube_url:
            logger.info(f"Analyzing YouTube content: {request.youtube_url}")

            # Get video metadata
            try:
                # --- PERUBAHAN DI SINI ---
                # Panggil fungsi langsung dari modul youtube
                video_metadata = await youtube.get_video_metadata(str(request.youtube_url))
                if not video_metadata:
                    # Pesan error dibuat lebih spesifik
                    raise HTTPException(
                        status_code=404,
                        detail="Invalid YouTube URL or video not found. Please check the URL and try again."
                    )
            except Exception as e:
                logger.error(f"Error getting video metadata: {e}")
                raise HTTPException(
                    status_code=500, # Menggunakan 500 karena ini error server/konfigurasi
                    detail=f"Unable to access video information. Reason: {e}"
                )

            # Get transcript with enhanced error handling (kode selanjutnya tetap sama)
            try:
                transcript = await transcriber_service.get_transcript(str(request.youtube_url))
                if not transcript or len(transcript.strip()) < 50:
                    raise HTTPException(
                        status_code=422,
                        detail="The transcript is too short or empty. Please try a different video with more content."
                    )
            except HTTPException:
                raise
            except Exception as e:
                error_message = str(e).lower()
                if "no subtitles" in error_message or "no captions" in error_message:
                    raise HTTPException(status_code=404, detail="This video doesn't have subtitles or captions available.")
                elif "unavailable" in error_message or "private" in error_message:
                    raise HTTPException(status_code=403, detail="This video is not available, private, or has been removed.")
                else:
                    logger.error(f"Transcript extraction error: {e}")
                    raise HTTPException(status_code=500, detail=f"Failed to extract video content: {str(e)}")

            # Generate timeline summary
            try:
                timeline_summary = await _generate_timeline_summary(transcript, video_metadata.duration)
            except Exception as e:
                logger.warning(f"Timeline summary generation failed: {e}")
                timeline_summary = []

        # (Sisa dari file ini tidak perlu diubah)
        # ...

        # Handle document analysis
        if request.file_path:
            logger.info(f"Analyzing document: {request.file_path}")
            try:
                doc_summary = await summarize_document(request.file_path)
                transcript = doc_summary
            except Exception as e:
                logger.error(f"Document analysis error: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to analyze document. Please ensure the file is accessible and in a supported format."
                )

        # Generate overall summary
        try:
            overall_summary = await summarize_transcript(transcript)
        except Exception as e:
            logger.error(f"Summary generation error: {e}")
            overall_summary = "Unable to generate summary at this time."

        # Calculate viral score
        title_for_analysis = video_metadata.title if video_metadata else "Document Analysis"
        views_for_analysis = video_metadata.view_count if video_metadata else 0
        likes_for_analysis = video_metadata.like_count if video_metadata else 0

        try:
            viral_score = await viral_service.calculate_viral_score(
                transcript,
                title_for_analysis,
                views_for_analysis,
                likes_for_analysis
            )
        except Exception as e:
            logger.error(f"Viral score calculation error: {e}")
            viral_score = 65  # Default moderate score

        # Determine viral label
        if viral_score >= 80:
            viral_label = "Very Viral"
        elif viral_score >= 60:
            viral_label = "Moderately Viral"
        else:
            viral_label = "Low Reach"

        # Generate viral explanation
        try:
            viral_explanation = await explain_why_viral(
                title_for_analysis,
                views_for_analysis,
                likes_for_analysis,
                overall_summary
            )
        except Exception as e:
            logger.error(f"Viral explanation error: {e}")
            viral_explanation = "This content shows potential for engagement based on its topic and presentation style."

        # Generate recommendations
        try:
            recommendations = await generate_content_idea(
                "general",
                overall_summary,
                viral_explanation
            )
        except Exception as e:
            logger.error(f"Recommendations generation error: {e}")
            from services.gemini_utils import _create_fallback_recommendation
            recommendations = _create_fallback_recommendation()

        response = AnalyzeResponse(
            video_metadata=video_metadata,
            summary=overall_summary,
            timeline_summary=timeline_summary,
            viral_score=viral_score,
            viral_label=viral_label,
            viral_explanation=viral_explanation,
            recommendations=recommendations,
            doc_summary=doc_summary
        )

        logger.info(f"Analysis completed successfully for: {request.youtube_url or request.file_path}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during analysis: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal server error occurred. Please try again later."
        )


async def _generate_timeline_summary(transcript: str, duration_seconds: int):
    # (Fungsi ini tidak perlu diubah)
    # ...
    try:
        if not transcript or duration_seconds <= 0:
            return []

        words = transcript.split()
        if len(words) < 10:  # Too short for meaningful timeline
            return []

        # Calculate optimal number of chunks (aim for 1-2 minute segments)
        target_segment_duration = 90  # 1.5 minutes
        num_chunks = max(2, min(8, duration_seconds // target_segment_duration))
        words_per_chunk = max(10, len(words) // num_chunks)

        timeline_items = []
        
        for i in range(num_chunks):
            start_time = (i * duration_seconds) // num_chunks
            end_time = min(((i + 1) * duration_seconds) // num_chunks, duration_seconds)
            
            start_word = i * words_per_chunk
            end_word = min((i + 1) * words_per_chunk, len(words))
            
            chunk_text = " ".join(words[start_word:end_word])

            if chunk_text.strip() and len(chunk_text.strip()) > 20:
                try:
                    chunk_summary = await summarize_transcript(chunk_text)
                    timeline_items.append({
                        "timestamp": f"{start_time//60:02d}:{start_time%60:02d} - {end_time//60:02d}:{end_time%60:02d}",
                        "summary": chunk_summary
                    })
                except Exception as e:
                    logger.warning(f"Failed to summarize chunk {i}: {e}")
                    continue

        return timeline_items

    except Exception as e:
        logger.error(f"Error generating timeline summary: {str(e)}")
        return []


@router.get("/analyze/status/{task_id}")
async def get_analysis_status(task_id: str):
    # (Fungsi ini tidak perlu diubah)
    # ...
    return {
        "task_id": task_id, 
        "status": "completed", 
        "progress": 100
    }

@router.get("/analyze/health")
async def health_check():
    # (Fungsi ini tidak perlu diubah)
    # ...
    services_status = {
        "transcriber": transcriber_service.get_supported_formats(),
        "gemini_available": True,
        "youtube_utils": True,
    }
    
    return {
        "status": "healthy",
        "services": services_status,
        "timestamp": "2024-01-01T00:00:00Z"
    }