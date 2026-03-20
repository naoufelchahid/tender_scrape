import logging
import requests
from typing import List, Optional
from .config import settings

logger = logging.getLogger(__name__)

class EmbeddingClient:
    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.model = settings.EMBEDDING_MODEL
        self.base_url = "https://openrouter.ai/api/v1/embeddings"

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Fetch embedding vector from OpenRouter."""
        if not text:
            return None
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "input": text[:8000] # Simple truncation to stay within typical limits
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]
        except Exception as e:
            logger.error(f"Failed to fetch embedding: {str(e)}")
            return None

    def batch_get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Fetch embeddings for multiple texts."""
        # OpenRouter/OpenAI support batching input
        if not texts:
            return []
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "input": [t[:8000] for t in texts]
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            # Sort by index to maintain order
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [x["embedding"] for x in sorted_data]
        except Exception as e:
            logger.error(f"Failed to fetch batch embeddings: {str(e)}")
            return []
