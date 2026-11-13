"""Bring-your-own AI: one place that turns a prompt into text.

Each user can save a provider, base URL, model and API key in Settings.
- Claude uses Anthropic's official SDK (Messages API).
- ChatGPT, Gemini, OpenRouter, Groq, Ollama and any other OpenAI-compatible
  server use the OpenAI SDK's Chat Completions with that base URL.
- With no user setting, the server's OPENAI_API_KEY (if any) is used.
- With nothing configured, callers fall back to the built-in, no-AI path.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

AI_TIMEOUT_SECONDS = 60.0
MAX_OUTPUT_TOKENS = 16000

# Claude models that accept Anthropic's server-side refusal fallback.
_CLAUDE_FALLBACK_MODELS = {
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
}

PRESETS: dict[str, dict] = {
    "anthropic": {
        "label": "Claude (Anthropic)",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-opus-5-5",
        "needs_key": True,
        "key_help": "Create a key at console.anthropic.com.",
    },
    "openai": {
        "label": "ChatGPT (OpenAI)",
        "kind": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5-mini",
        "needs_key": True,
        "key_help": "Create a key at platform.openai.com.",
    },
    "gemini": {
        "label": "Gemini (Google)",
        "kind": "openai_compatible",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
        "needs_key": True,
        "key_help": "Create a key in Google AI Studio.",
    },
    "openrouter": {
        "label": "OpenRouter (many open-source models)",
        "kind": "openai_compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct",
        "needs_key": True,
        "key_help": "Create a key at openrouter.ai.",
    },
    "groq": {
        "label": "Groq (fast open-source models)",
        "kind": "openai_compatible",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "needs_key": True,
        "key_help": "Create a key at console.groq.com.",
    },
    "ollama": {
        "label": "Ollama (runs on your computer)",
        "kind": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.2",
        "needs_key": False,
        "key_help": "No key needed. Only works when Life Inbox runs on the same computer.",
    },
    "custom": {
        "label": "Other (OpenAI-compatible)",
        "kind": "openai_compatible",
        "base_url": "",
        "model": "",
        "needs_key": False,
        "key_help": "Any server that speaks the OpenAI Chat Completions API.",
    },
}


class AIProviderError(Exception):
    """The provider call failed. The message is safe to show the user."""


@dataclass(frozen=True)
class AIConfig:
    provider: str  # a PRESETS key, or "server" for the env-configured default
    kind: str  # anthropic | openai_compatible | server_openai
    base_url: str
    model: str
    api_key: Optional[str]
    source: str  # user | server

    @property
    def label(self) -> str:
        if self.provider == "server":
            return "Server default (OpenAI)"
        return PRESETS.get(self.provider, {}).get("label", self.provider)


def _is_local_environment() -> bool:
    from app.config import load_config

    return load_config(strict=False).environment == "local"


def validate_base_url(url: str) -> str:
    """Hosted sites only call public https endpoints; local runs may use localhost."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL must start with http:// or https://.")
    if parsed.username or parsed.password:
        raise ValueError("Base URL must not contain a username or password.")
    if _is_local_environment():
        return url
    if parsed.scheme != "https":
        raise ValueError("Base URL must use https:// on the hosted site.")
    from app.capture.url_fetch import validate_public_http_url

    try:
        validate_public_http_url(url)
    except ValueError as exc:
        raise ValueError(
            "That base URL points to a private or local address, which the "
            "hosted site cannot use."
        ) from exc
    return url


def _server_default() -> Optional[AIConfig]:
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return None
    return AIConfig(
        provider="server",
        kind="server_openai",
        base_url="",
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        api_key=None,  # the OpenAI SDK reads OPENAI_API_KEY itself
        source="server",
    )


def user_ai_config(owner_user_id: int) -> Optional[AIConfig]:
    """The AI settings a user saved, or None."""
    from app.database import get_user_settings
    from app.secret_box import decrypt_secret

    settings = get_user_settings(owner_user_id)
    provider = settings.get("ai_provider")
    if not provider or provider not in PRESETS:
        return None
    preset = PRESETS[provider]
    base_url = (settings.get("ai_base_url") or preset["base_url"]).strip()
    model = (settings.get("ai_model") or preset["model"]).strip()
    api_key = decrypt_secret(settings.get("ai_api_key_enc"))
    if not base_url or not model:
        return None
    if preset["needs_key"] and not api_key:
        return None
    return AIConfig(
        provider=provider,
        kind=preset["kind"],
        base_url=base_url,
        model=model,
        api_key=api_key,
        source="user",
    )


def resolve_ai_config() -> Optional[AIConfig]:
    """User settings for the signed-in owner, else the server default, else None."""
    from app.database import get_current_owner_id

    owner = get_current_owner_id()
    if owner is not None:
        config = user_ai_config(owner)
        if config is not None:
            return config
    return _server_default()


def _complete_anthropic(prompt: str, config: AIConfig) -> str:
    import anthropic

    client = anthropic.Anthropic(
        api_key=config.api_key,
        base_url=config.base_url or None,
        timeout=AI_TIMEOUT_SECONDS,
        max_retries=1,
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        if config.model in _CLAUDE_FALLBACK_MODELS:
            # On a policy decline, let the API retry on a suitable model.
            response = client.beta.messages.create(
                model=config.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=messages,
            )
        else:
            response = client.messages.create(
                model=config.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                messages=messages,
            )
    except anthropic.AuthenticationError as exc:
        raise AIProviderError("Claude rejected the API key.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIProviderError("This Claude API key cannot use that model.") from exc
    except anthropic.NotFoundError as exc:
        raise AIProviderError(f"Claude model “{config.model}” was not found.") from exc
    except anthropic.RateLimitError as exc:
        raise AIProviderError("Claude rate limit reached. Try again shortly.") from exc
    except anthropic.APIStatusError as exc:
        raise AIProviderError(f"Claude returned an error ({exc.status_code}).") from exc
    except anthropic.APIConnectionError as exc:
        raise AIProviderError("Could not reach the Claude API.") from exc

    if response.stop_reason == "refusal":
        raise AIProviderError("Claude declined this request.")
    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    )
    if not text.strip():
        raise AIProviderError("Claude returned an empty answer.")
    return text


def _complete_openai_compatible(prompt: str, config: AIConfig) -> str:
    import openai

    client = openai.OpenAI(
        api_key=config.api_key or "not-needed",
        base_url=config.base_url,
        timeout=AI_TIMEOUT_SECONDS,
        max_retries=1,
    )
    try:
        response = client.chat.completions.create(
            model=config.model,
            messages=[{"role": "user", "content": prompt}],
        )
    except openai.AuthenticationError as exc:
        raise AIProviderError(f"{config.label} rejected the API key.") from exc
    except openai.NotFoundError as exc:
        raise AIProviderError(
            f"{config.label} could not find model “{config.model}” (or the base URL is wrong)."
        ) from exc
    except openai.RateLimitError as exc:
        raise AIProviderError(f"{config.label} rate limit reached. Try again shortly.") from exc
    except openai.APIStatusError as exc:
        raise AIProviderError(f"{config.label} returned an error ({exc.status_code}).") from exc
    except openai.APIConnectionError as exc:
        raise AIProviderError(f"Could not reach {config.label} at that base URL.") from exc

    choices = getattr(response, "choices", None) or []
    text = (choices[0].message.content or "") if choices else ""
    if not text.strip():
        raise AIProviderError(f"{config.label} returned an empty answer.")
    return text


def _complete_server_openai(prompt: str, config: AIConfig) -> str:
    from openai import OpenAI

    client = OpenAI()
    response = client.responses.create(model=config.model, input=prompt)
    return response.output_text


def complete_text(prompt: str, config: AIConfig) -> str:
    """Send one prompt and return the reply text, or raise AIProviderError."""
    if config.kind == "anthropic":
        return _complete_anthropic(prompt, config)
    if config.kind == "openai_compatible":
        if config.source == "user":
            validate_base_url(config.base_url)
        return _complete_openai_compatible(prompt, config)
    return _complete_server_openai(prompt, config)


def check_connection(config: AIConfig) -> str:
    reply = complete_text(
        "Reply with exactly the word: ready",
        config,
    )
    return reply.strip()[:200]
