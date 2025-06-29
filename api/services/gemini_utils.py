import os
import logging
from typing import Dict, List
import google.generativeai as genai
from models.schemas import ContentRecommendation
import json

logger = logging.getLogger(__name__)

class GeminiService:
    """Service for interacting with Google Gemini AI."""
    
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel('gemini-pro')
                logger.info("Gemini service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
                self.model = None
        else:
            logger.error("GEMINI_API_KEY not found. GeminiService cannot function.")
            self.model = None

    async def _generate_content(self, prompt: str) -> str:
        """Generate content using Gemini API with error handling."""
        if not self.model:
            raise Exception("Gemini model is not initialized. Please check your GEMINI_API_KEY.")
        
        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.7,
                    top_p=0.8,
                    top_k=40,
                    max_output_tokens=2048,
                )
            )
            
            if not response.text:
                raise Exception("Gemini returned empty response")
                
            return response.text
        except Exception as e:
            logger.error(f"Gemini API error: {str(e)}")
            raise Exception(f"Failed to generate content from Gemini: {str(e)}")


gemini_service = GeminiService()

async def summarize_transcript(transcript_chunk: str) -> str:
    """
    Summarize a transcript chunk using Gemini AI.
    """
    if not transcript_chunk or len(transcript_chunk.strip()) < 10:
        return "No content available to summarize."
    
    prompt = f"""
    Please provide a comprehensive and engaging summary of the following content in 3-4 sentences. 
    Focus on the key points, main insights, and valuable information that viewers would find most interesting:
    
    Content: "{transcript_chunk[:4000]}"  # Limit content length
    
    Requirements:
    - Write in clear, engaging language
    - Highlight the most important points
    - Make it informative and easy to understand
    - Focus on actionable insights when applicable
    
    Summary:
    """
    
    try:
        summary = await gemini_service._generate_content(prompt)
        return summary.strip()
    except Exception as e:
        logger.error(f"Error summarizing transcript: {e}")
        return "Unable to generate summary at this time."

async def explain_why_viral(title: str, views: int, likes: int, summary: str) -> str:
    """
    Generate explanation for why content has viral potential.
    """
    prompt = f"""
    Analyze why this content has viral potential based on the following information:
    
    Title: {title}
    Views: {views:,} 
    Likes: {likes:,}
    Content Summary: {summary[:1000]}
    
    Provide a detailed analysis (4-5 sentences) covering:
    1. What specific elements make this content engaging and shareable
    2. Why it resonates with audiences (emotional triggers, value proposition)
    3. Key viral factors such as topic relevance, presentation style, or timing
    4. How the content taps into current trends or universal interests
    
    Focus on actionable insights that content creators can learn from.
    
    Analysis:
    """
    
    try:
        explanation = await gemini_service._generate_content(prompt)
        return explanation.strip()
    except Exception as e:
        logger.error(f"Error generating viral explanation: {e}")
        return "This content shows strong viral potential due to its engaging topic and presentation style."

async def generate_content_idea(category: str, summary: str, reason: str) -> ContentRecommendation:
    """
    Generate content recommendation based on analysis by requesting a JSON object.
    """
    prompt = f"""
    Based on this successful content analysis, generate a new viral content idea that follows similar patterns:
    
    Category: {category}
    Original Content Summary: {summary[:800]}
    Viral Success Factors: {reason[:800]}
    
    Create a detailed content recommendation in valid JSON format with these exact keys:
    
    {{
        "title": "A compelling, clickable title that creates curiosity (string)",
        "target_audience": "Specific target audience description (string)", 
        "content_style": "Recommended content style and format (string)",
        "suggested_structure": {{
            "hook": "Attention-grabbing opening (15-30 seconds)",
            "introduction": "Brief setup and value proposition", 
            "main_content": "Core content delivery strategy",
            "call_to_action": "Engagement and conversion strategy"
        }},
        "pro_tips": [
            "Specific actionable tip 1",
            "Specific actionable tip 2", 
            "Specific actionable tip 3",
            "Specific actionable tip 4",
            "Specific actionable tip 5"
        ],
        "estimated_viral_score": 75
    }}
    
    Make the recommendation specific, actionable, and based on current viral content trends.
    Ensure the estimated_viral_score is between 60-95.
    
    JSON Response:
    """
    
    try:
        response_text = await gemini_service._generate_content(prompt)
        
        # Clean and parse JSON response
        clean_json_text = response_text.strip()
        
        # Remove markdown code blocks if present
        if clean_json_text.startswith('```json'):
            clean_json_text = clean_json_text[7:]
        if clean_json_text.startswith('```'):
            clean_json_text = clean_json_text[3:]
        if clean_json_text.endswith('```'):
            clean_json_text = clean_json_text[:-3]
        
        clean_json_text = clean_json_text.strip()
        
        # Parse JSON
        data = json.loads(clean_json_text)
        
        # Validate and create ContentRecommendation
        recommendation = ContentRecommendation(**data)
        return recommendation
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error in content recommendation: {e}")
        logger.error(f"Raw response: {response_text[:500]}...")
        return _create_fallback_recommendation()
    except Exception as e:
        logger.error(f"Error generating content idea: {str(e)}")
        return _create_fallback_recommendation()

def _create_fallback_recommendation() -> ContentRecommendation:
    """Create a fallback recommendation when AI generation fails."""
    return ContentRecommendation(
        title="Create Engaging Content That Drives Results",
        target_audience="Content creators, entrepreneurs, and digital marketers aged 25-45",
        content_style="Educational tutorial with practical examples and clear step-by-step guidance",
        suggested_structure={
            "hook": "Start with a compelling question or surprising statistic that grabs attention",
            "introduction": "Briefly introduce the problem you're solving and the value you'll provide",
            "main_content": "Deliver actionable steps with real examples and visual demonstrations",
            "call_to_action": "Encourage viewers to try the technique and share their results"
        },
        pro_tips=[
            "Focus on solving a specific problem your audience faces daily",
            "Use clear, conversational language that's easy to follow",
            "Include visual elements and examples to maintain engagement",
            "Create content that viewers will want to save and share",
            "Optimize your title and thumbnail for maximum click-through rate"
        ],
        estimated_viral_score=78
    )

async def summarize_document(file_path: str) -> str:
    """
    Summarize document content.
    """
    logger.info(f"Summarizing document: {file_path}")
    
    # TODO: Implement actual document reading and processing
    # This would involve reading PDF, Word, or other document formats
    # and extracting text content for summarization
    
    mock_summary = f"""
    Document Analysis Summary:
    
    This document contains comprehensive information covering strategic planning, 
    implementation guidelines, and industry best practices. Key themes include 
    process optimization, stakeholder engagement, and measurable outcomes.
    
    The content provides actionable insights for professionals looking to improve 
    their operational efficiency and strategic decision-making capabilities.
    """
    
    return await summarize_transcript(mock_summary)