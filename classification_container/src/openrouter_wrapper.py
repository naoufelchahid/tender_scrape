"""
Pipeline Stage: Extraction Container
OpenRouter API Wrapper for LLM Inference with Fallback Logic
"""

import os
import logging
from typing import List, Optional, Dict
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Use standard OpenAI client for OpenRouter compatibility
try:
    from openai import OpenAI, APIError
except ImportError:
    OpenAI = None
    APIError = Exception

logger = logging.getLogger(__name__)


class OpenRouterClientWrapper:
    """
    OpenRouter API client wrapper with automatic model fallback.
    
    Supports hierarchical model fallback (all free models):
    1. openai/gpt-oss-20b:free (Primary)
    2. qwen/qwen3-next-80b-a3b-instruct:free (Secondary)
    3. nvidia/nemotron-nano-9b-v2:free (Tertiary)
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize OpenRouter client.
        
        Args:
            api_key: OpenRouter API key (optional, defaults to OPENROUTER_API_KEY env var)
        
        Raises:
            ImportError: If openai package is not installed
        """
        if not OpenAI:
            raise ImportError("openai package is required for OpenRouter integration")
        
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not found. Operations will fail if not provided.")
        
        # Initialize OpenAI client with OpenRouter endpoint
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "Tender Extraction Service"
            }
        )
        
        # Model hierarchy - Free models for classification
        self.models = [
            os.getenv("MODEL_PRIMARY", "google/gemma-3n-e2b-it:free"),
            os.getenv("MODEL_SECONDARY", "qwen/qwen3-next-80b-a3b-instruct:free"),
            os.getenv("MODEL_TERTIARY", "nvidia/nemotron-nano-9b-v2:free"),
        ]
        
        logger.info(f"OpenRouter client initialized with {len(self.models)} fallback models")

    def chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.0, 
        json_mode: bool = False
    ) -> str:
        """
        Execute chat completion with automatic model fallback.
        
        Attempts inference using models in priority order. If a model fails,
        automatically falls back to the next model in the hierarchy.
        
        Args:
            messages: List of chat messages in OpenAI format
            temperature: Sampling temperature (0.0 = deterministic)
            json_mode: Whether to request JSON-formatted output
        
        Returns:
            Model response content as string
        
        Raises:
            Exception: If all models fail
        """
        last_exception = None
        
        for model in self.models:
            try:
                logger.debug(f"Attempting inference with model: {model}")
                
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }
                
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                
                logger.info(f"✓ Successfully generated response using {model}")
                return content
                
            except Exception as e:
                logger.warning(f"OpenRouter model {model} failed: {str(e)}")
                last_exception = e
                # Continue to next model in fallback chain
        
        # All models failed
        logger.error("All OpenRouter models failed after exhausting fallback chain")
        if last_exception:
            raise last_exception
        raise Exception("Unknown error in OpenRouterClientWrapper: All models failed silently")
