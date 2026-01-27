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
    from openai import OpenAI, AsyncOpenAI, APIError
except ImportError:
    OpenAI = None
    AsyncOpenAI = None
    APIError = Exception

logger = logging.getLogger(__name__)


class OpenRouterClientWrapper:
    """
    OpenRouter API client wrapper with automatic model fallback.
    
    Supports hierarchical model fallback:
    1. meta-llama/llama-4-maverick (Primary)
    2. meta-llama/llama-4-scout (Secondary)
    3. google/gemini-2.5-flash-lite (Tertiary)
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

        # Initialize Async OpenAI client
        self.async_client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "Tender Extraction Service"
            }
        )
        
        # Model hierarchy from environment variables
        self.models = []
        
        primary = os.environ.get("PRIMARY_MODEL")
        if primary:
            self.models.append(primary)
            
        fallback_1 = os.environ.get("FALLBACK_MODEL_1")
        if fallback_1:
            self.models.append(fallback_1)
            
        fallback_2 = os.environ.get("FALLBACK_MODEL_2")
        if fallback_2:
            self.models.append(fallback_2)
            
        if not self.models:
            logger.warning("No models configured in environment variables! Please set PRIMARY_MODEL.")
            # Fallback default to avoid crash if env missing
            self.models = ["meta-llama/llama-4-maverick"]
        
        logger.info(f"OpenRouter client initialized with {len(self.models)} fallback models")

    def chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.0, 
        json_mode: bool = False
    ) -> str:
        """
        Execute synchronous chat completion with automatic model fallback.
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

    async def chat_completion_async(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.0, 
        json_mode: bool = False
    ) -> str:
        """
        Execute ASYNC chat completion with automatic model fallback.
        """
        last_exception = None
        
        for model in self.models:
            try:
                logger.debug(f"Attempting ASYNC inference with model: {model}")
                
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }
                
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                
                response = await self.async_client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                
                logger.info(f"✓ Successfully generated ASYNC response using {model}")
                return content
                
            except Exception as e:
                logger.warning(f"OpenRouter model {model} failed (Async): {str(e)}")
                last_exception = e
                # Continue to next model in fallback chain
        
        # All models failed
        logger.error("All OpenRouter models failed after exhausting fallback chain (Async)")
        if last_exception:
            raise last_exception
        raise Exception("Unknown error in OpenRouterClientWrapper: All models failed silently")
