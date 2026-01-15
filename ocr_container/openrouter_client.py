"""
OpenRouter API client for vision-based OCR.
Supports Llama 4 models with automatic fallback cascade.
Stage: Extraction Container - OCR Processing
"""
import time
from typing import List, Dict, Any, Optional, Tuple
from openai import OpenAI
import logging

from config import Config
from logger import logger


class OpenRouterClient:
    """
    OpenRouter API client with vision support and fallback logic.
    
    Implements automatic retry and model fallback for robust OCR processing.
    """
    
    def __init__(self):
        """Initialize OpenRouter client with configuration."""
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=Config.OPENROUTER_API_KEY,
        )
        
        # Model hierarchy for fallback
        self.models = [
            Config.PRIMARY_MODEL,      # meta-llama/llama-4-maverick
            Config.FALLBACK_MODEL_1,   # meta-llama/llama-guard-4-12b
            Config.FALLBACK_MODEL_2,   # meta-llama/llama-4-scout
        ]
        
        logger.info(f"OpenRouter client initialized with models: {self.models}")
    
    def chat_completion_with_vision(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        max_tokens: int = 4000,
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> Tuple[str, str]:
        """
        Create chat completion with vision support.
        
        Args:
            messages: List of message dicts with text and image_url
            model: Model to use (default: PRIMARY_MODEL)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            max_retries: Maximum retry attempts per model
            
        Returns:
            Tuple of (response_text, model_used)
            
        Raises:
            Exception: If all models and retries fail
        """
        if model is None:
            model = self.models[0]
        
        # Try primary model first, then fallbacks
        models_to_try = [model] if model != self.models[0] else self.models
        
        last_error = None
        
        for model_name in models_to_try:
            for attempt in range(max_retries):
                try:
                    logger.info(
                        f"Calling OpenRouter API with model {model_name} "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    
                    response = self.client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        extra_headers={
                            "HTTP-Referer": Config.OPENROUTER_APP_NAME,
                            "X-Title": "OCR Service - Tender Processing"
                        }
                    )
                    
                    # Extract response text
                    response_text = response.choices[0].message.content
                    
                    # Log token usage
                    if hasattr(response, 'usage'):
                        logger.info(
                            f"Token usage - prompt: {response.usage.prompt_tokens}, "
                            f"completion: {response.usage.completion_tokens}, "
                            f"total: {response.usage.total_tokens}"
                        )
                    
                    logger.info(f"Successfully completed with model {model_name}")
                    return response_text, model_name
                    
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"Error with model {model_name} (attempt {attempt + 1}): {e}"
                    )
                    
                    # Exponential backoff for retries
                    if attempt < max_retries - 1:
                        backoff_time = 2 ** attempt
                        logger.info(f"Retrying in {backoff_time}s...")
                        time.sleep(backoff_time)
                    else:
                        logger.error(f"All retries exhausted for model {model_name}")
            
            # If we've exhausted retries for this model, try next model
            if models_to_try.index(model_name) < len(models_to_try) - 1:
                logger.info(f"Falling back to next model in cascade")
        
        # All models and retries failed
        error_msg = f"All models failed after {max_retries} retries. Last error: {last_error}"
        logger.error(error_msg)
        raise Exception(error_msg)
    
    def ocr_image(
        self,
        image_base64: str,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 4000,
        temperature: float = 0.1,
    ) -> str:
        """
        OCR image using vision model.
        
        Args:
            image_base64: Base64-encoded image
            system_prompt: System instruction
            user_prompt: User prompt
            model: Model to use (default: PRIMARY_MODEL)
            max_tokens: Maximum tokens
            temperature: Sampling temperature
            
        Returns:
            Extracted markdown text
        """
        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    }
                ]
            }
        ]
        
        response_text, model_used = self.chat_completion_with_vision(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        return response_text
    
    def enhance_text(
        self,
        text: str,
        enhancement_prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.1,
    ) -> str:
        """
        Enhance text (e.g., table formatting).
        
        Args:
            text: Text to enhance
            enhancement_prompt: Enhancement instruction
            model: Model to use (default: PRIMARY_MODEL)
            max_tokens: Maximum tokens
            temperature: Sampling temperature
            
        Returns:
            Enhanced text
        """
        messages = [
            {
                "role": "system",
                "content": "You are a table formatting expert."
            },
            {
                "role": "user",
                "content": enhancement_prompt.format(table_content=text)
            }
        ]
        
        if model is None:
            model = self.models[0]
        
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_headers={
                    "HTTP-Referer": Config.OPENROUTER_APP_NAME,
                    "X-Title": "OCR Service - Text Enhancement"
                }
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"Text enhancement failed: {e}")
            return text  # Return original on error
