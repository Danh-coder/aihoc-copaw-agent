# -*- coding: utf-8 -*-
import os
import requests
from typing import List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

EMBED_API_KEY = os.environ.get("EMBEDDING_API_KEY")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBEDDING_TIMEOUT_SEC = int(os.environ.get("EMBEDDING_TIMEOUT_SEC", "30"))

QRANDT_API_URL = os.environ.get("QRANDT_API_URL")
QRANDT_API_KEY = os.environ.get("QRANDT_API_KEY")
LLM_API_URL = os.environ.get("LLM_API_URL")
LLM_API_KEY = os.environ.get("LLM_API_KEY")


class EmbeddingClient:
    """Google Generative AI embedding client using the google-genai SDK.
    
    Uses google.genai library for embeddings.
    Set EMBEDDING_API_KEY to your Google API key.
    """

    def __init__(
        self,
        api_key: str = EMBED_API_KEY,
        model: str = EMBEDDING_MODEL,
        request_timeout_sec: int = EMBEDDING_TIMEOUT_SEC,
    ):
        if not api_key:
            raise RuntimeError("EMBEDDING_API_KEY not configured")
        self.api_key = api_key
        try:
            from google import genai
            self._client = genai.Client(api_key=api_key)
        except ImportError:
            raise RuntimeError(
                "google-genai is not installed. Run: uv pip install google-genai"
            )
        self.model = model
        self.request_timeout_sec = max(1, request_timeout_sec)

    def _embed_single(self, text: str) -> List[float]:
        result = self._client.models.embed_content(
            model=self.model,
            contents=text,
        )
        if hasattr(result, "embeddings") and result.embeddings:
            return result.embeddings[0].values
        if hasattr(result, "embedding") and getattr(result, "embedding", None):
            return result.embedding.values
        raise RuntimeError("Unexpected embedding response shape")

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts using Google's embedding model."""
        if not texts:
            return []
        embeddings = []
        for text in texts:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._embed_single, text)
                try:
                    embeddings.append(future.result(timeout=self.request_timeout_sec))
                except FutureTimeoutError as exc:
                    raise RuntimeError(
                        f"Embedding request timed out after {self.request_timeout_sec}s"
                    ) from exc
        return embeddings


class QrandtClient:
    """Minimal adapter for qrandt vector DB (demo). Expects QRANDT_API_URL and key.

    Endpoints used:
    - POST {QRANDT_API_URL}/vectors/upsert -> body {"vectors": [{"id":..., "values":..., "metadata": {...}}]}
    - POST {QRANDT_API_URL}/vectors/search -> body {"vector": [...], "top_k": n}
    """

    def __init__(self, api_url: str = QRANDT_API_URL, api_key: str = QRANDT_API_KEY):
        self.api_url = api_url
        self.api_key = api_key

    def upsert(self, vectors: List[dict]):
        if not self.api_url:
            raise RuntimeError("QRANDT_API_URL not configured")
        url = f"{self.api_url.rstrip('/')}/vectors/upsert"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        resp = requests.post(url, json={"vectors": vectors}, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def search(self, vector: List[float], top_k: int = 5):
        if not self.api_url:
            raise RuntimeError("QRANDT_API_URL not configured")
        url = f"{self.api_url.rstrip('/')}/vectors/search"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        resp = requests.post(url, json={"vector": vector, "top_k": top_k}, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()


class LLMClient:
    """Simple LLM adapter that calls an external completion API.

    Expected contract: POST {LLM_API_URL}/completions with JSON {"prompt": str, "max_tokens": int}
    Response expected: {"text": "..."}
    """

    def __init__(self, api_url: str = LLM_API_URL, api_key: str = LLM_API_KEY):
        self.api_url = api_url
        self.api_key = api_key

    def generate(self, prompt: str, max_tokens: int = 256) -> str:
        if not self.api_url:
            raise RuntimeError("LLM_API_URL not configured")
        url = f"{self.api_url.rstrip('/')}/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"prompt": prompt, "max_tokens": max_tokens}
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        # Support multiple API shapes
        if isinstance(data, dict) and "text" in data:
            return data.get("text") or ""
        if isinstance(data, dict) and "choices" in data:
            # e.g., OpenAI-like
            choices = data.get("choices") or []
            if choices and isinstance(choices, list):
                return choices[0].get("text", "")
        return ""
