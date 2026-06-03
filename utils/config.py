"""Configuration loaded from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """DeepSeek API and pipeline settings, loaded from .env file."""

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"

    max_llm_chars: int = 120_000
    llm_max_retries: int = 3
    llm_timeout: int = 180

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


PROJECT_ROOT = Path(__file__).resolve().parent.parent

CACHE_DIR = PROJECT_ROOT / "cache"
PDF_CACHE_DIR = CACHE_DIR / "pdf"
LLM_CACHE_DIR = CACHE_DIR / "llm"

for d in (CACHE_DIR, PDF_CACHE_DIR, LLM_CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)
