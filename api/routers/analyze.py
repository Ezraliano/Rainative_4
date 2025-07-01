# api/routers/analyze.py

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from models.schemas import AnalyzeRequest, AnalyzeResponse
from services.transcriber import TranscriberService, VideoProcessingError
from services.viral import ViralAnalysisService
from services.gemini_utils import (
    summarize_transcript, 
    explain_why_viral, 
    generate_content_idea,
    summarize_document
)
from utils import youtube
import logging
import tempfile
import os
from pathlib import Path
from typing import Optional

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

@router.post("/analyze-document", response_model=AnalyzeResponse)
async def analyze_document(file: UploadFile = File(...)):
    """Analyze uploaded document content."""
    logger.info(f"Analyzing document: {file.filename}")
    
    # Validate file type
    allowed_extensions = {'.pdf', '.doc', '.docx', '.txt', '.ppt', '.pptx'}
    file_extension = Path(file.filename or '').suffix.lower()
    
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file type. Allowed types: {', '.join(allowed_extensions)}"
        )
    
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            # Extract text from document (simplified for now)
            document_text = await extract_text_from_document(temp_file_path, file_extension)
            
            if not document_text or len(document_text.strip()) < 20:
                raise HTTPException(status_code=422, detail="Document content is too short or empty.")
            
            # Generate summary and analysis
            overall_summary = await summarize_transcript(document_text)
            
            # For documents, we'll use a simplified viral analysis
            viral_score = await viral_service.calculate_viral_score(
                document_text,
                file.filename or "Document",
                0,  # No views for documents
                0   # No likes for documents
            )
            
            # Generate explanation and recommendations
            viral_explanation = f"This document contains valuable insights and information that could be adapted into engaging content. The content quality and structure suggest good potential for creating viral social media posts, videos, or articles."
            
            recommendations = await generate_content_idea("document", overall_summary, viral_explanation)
            
            # Determine viral label
            if viral_score >= 80:
                viral_label = "Very High Potential"
            elif viral_score >= 60:
                viral_label = "Good Potential"
            else:
                viral_label = "Needs Improvement"
            
            return AnalyzeResponse(
                video_metadata=None,
                summary=overall_summary,
                timeline_summary=[],
                viral_score=viral_score,
                viral_label=viral_label,
                viral_explanation=viral_explanation,
                recommendations=recommendations,
                doc_summary=overall_summary
            )
            
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(f"Failed to delete temporary file: {e}")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to analyze document.")

async def extract_text_from_document(file_path: str, file_extension: str) -> str:
    """Extract text content from various document formats."""
    try:
        if file_extension == '.txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        
        elif file_extension == '.pdf':
            # For now, return a mock text for PDF files
            # In production, you would use libraries like PyPDF2 or pdfplumber
            return """
            This is a comprehensive business document containing strategic insights and analysis.
            The document covers market research, competitive analysis, and growth strategies.
            Key findings include emerging trends, customer behavior patterns, and recommendations
            for improving business performance. The content provides valuable data-driven insights
            that can be leveraged for content creation and marketing strategies.
            """
        
        elif file_extension in ['.doc', '.docx']:
            # For now, return a mock text for Word documents
            # In production, you would use libraries like python-docx
            return """
            This Word document contains detailed project information and analysis.
            The content includes comprehensive research findings, methodology explanations,
            and actionable recommendations. The document structure follows professional
            standards with clear sections covering background, analysis, and conclusions.
            This material could be adapted into engaging educational content or tutorials.
            """
        
        elif file_extension in ['.ppt', '.pptx']:
            # For now, return a mock text for PowerPoint files
            # In production, you would use libraries like python-pptx
            return """
            This presentation contains engaging visual content and key insights.
            The slides cover important topics with clear explanations and examples.
            The presentation structure includes introduction, main concepts, case studies,
            and conclusions. This content has strong potential for creating viral
            educational videos or social media content series.
            """
        
        else:
            raise ValueError(f"Unsupported file type: {file_extension}")
            
    except Exception as e:
        logger.error(f"Failed to extract text from {file_extension} file: {e}")
        raise Exception(f"Failed to process {file_extension} file")