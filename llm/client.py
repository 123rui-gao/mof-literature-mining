"""DeepSeek API client with exponential backoff retry."""

from __future__ import annotations

import time
import httpx
from loguru import logger

from utils.config import Settings


def call_deepseek(
    system_prompt: str,
    user_prompt: str,
    settings: Settings | None = None,
) -> str:
    """Call DeepSeek chat/completions. Returns the assistant message content."""
    if settings is None:
        settings = Settings()

    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
    }

    last_error = None
    for attempt in range(settings.llm_max_retries):
        try:
            resp = httpx.post(
                url, json=payload, headers=headers,
                timeout=settings.llm_timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content

            msg = f"DeepSeek HTTP {resp.status_code}: {resp.text[:300]}"
            logger.warning(f"  LLM attempt {attempt + 1}: {msg}")
            last_error = msg

        except httpx.TimeoutException:
            logger.warning(f"  LLM attempt {attempt + 1}: timeout")
            last_error = "timeout"
        except Exception as e:
            logger.warning(f"  LLM attempt {attempt + 1}: {e}")
            last_error = str(e)

        if attempt < settings.llm_max_retries - 1:
            delay = 2 ** attempt
            time.sleep(delay)

    raise RuntimeError(f"DeepSeek API call failed after {settings.llm_max_retries} attempts: {last_error}")
