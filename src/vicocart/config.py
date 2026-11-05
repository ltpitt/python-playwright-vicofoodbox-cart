from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


class ConfigError(ValueError):
    """Invalid or incomplete configuration."""


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str = field(repr=False)


def load_credentials(env: Mapping[str, str]) -> Credentials | None:
    """Return credentials from VICO_EMAIL/VICO_PASSWORD, or None when neither is set."""
    email = env.get("VICO_EMAIL", "").strip()
    password = env.get("VICO_PASSWORD", "")
    if not email and not password:
        return None
    if not email or not password:
        raise ConfigError("VICO_EMAIL and VICO_PASSWORD must be set together")
    return Credentials(email=email, password=password)


@dataclass(frozen=True)
class LlmSettings:
    model: str
    base_url: str | None = None
    api_key: str = field(default="unused", repr=False)


def load_llm_settings(env: Mapping[str, str]) -> LlmSettings:
    """Read LLM_MODEL, LLM_BASE_URL and LLM_API_KEY; any OpenAI-compatible endpoint works."""
    model = env.get("LLM_MODEL", "").strip()
    if not model:
        raise ConfigError("LLM_MODEL is not set (see .env.example)")
    base_url = env.get("LLM_BASE_URL", "").strip() or None
    api_key = env.get("LLM_API_KEY", "").strip()
    if not api_key:
        if base_url is None:
            raise ConfigError("LLM_API_KEY is not set (see .env.example)")
        api_key = "unused"  # local servers such as Ollama ignore the key
    return LlmSettings(model=model, base_url=base_url, api_key=api_key)
