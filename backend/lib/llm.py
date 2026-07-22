"""Provider-neutral LLM wrapper. One entry point for all narrative generation.

DOCTRINE: the LLM writes narrative AROUND numbers, never the numbers. It interprets evidence
and connects signals. Any structured output it returns is schema-validated before use elsewhere.

Providers are OpenAI-compatible. Primary Groq, fallback GLM (Z.ai). Auto-failover when Groq
returns 429 (org-level free-tier rate limit ~30 req/min, ~1000 req/day) or errors. Every call is
cached by input hash in SQLite so testing and repeated renders don't burn the quota.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import storage

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    model: str


# Env-overridable so models can be swapped without code changes.
PROVIDERS: dict[str, ProviderConfig] = {
    "groq": ProviderConfig(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    ),
    # GLM flash models are reasoning models: they spend tokens in reasoning_content and can hit
    # max_tokens before emitting content. We disable thinking for narrative calls (see _call_provider).
    "glm": ProviderConfig(
        name="glm",
        base_url=os.getenv("GLM_BASE_URL", "https://api.z.ai/api/paas/v4"),
        api_key_env="GLM_API_KEY",
        model=os.getenv("GLM_MODEL", "glm-4.5-flash"),
    ),
}

PRIMARY = os.getenv("LLM_PROVIDER", "groq")
FALLBACK = "glm" if PRIMARY == "groq" else "groq"


class LLMError(RuntimeError):
    pass


def _client(cfg: ProviderConfig):
    from openai import OpenAI  # lazy import so importing this module is cheap
    key = os.getenv(cfg.api_key_env)
    if not key:
        raise LLMError(f"missing {cfg.api_key_env} for provider {cfg.name}")
    return OpenAI(base_url=cfg.base_url, api_key=key)


def _hash(messages: list[dict], model: str, temperature: float, json_mode: bool) -> str:
    blob = json.dumps(
        {"m": messages, "model": model, "t": temperature, "j": json_mode},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _call_provider(cfg: ProviderConfig, messages: list[dict], temperature: float,
                   max_tokens: int, json_mode: bool) -> str:
    client = _client(cfg)
    kwargs: dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if cfg.name == "glm":
        # Disable GLM's reasoning so tokens go to the answer, not the scratchpad.
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    content = msg.content or ""
    if not content:
        # Defensive: a reasoning model that still emitted only reasoning_content.
        content = getattr(msg, "reasoning_content", "") or ""
    return content


def complete(messages: list[dict], *, temperature: float = 0.3, max_tokens: int = 800,
             json_mode: bool = False, prompt_name: str | None = None,
             use_cache: bool = True, provider: str | None = None) -> str:
    """Run a chat completion with cache + auto-failover.

    Order: cache -> primary provider -> fallback provider. Raises LLMError only if all fail.
    """
    primary_name = provider or PRIMARY
    primary = PROVIDERS[primary_name]

    h = _hash(messages, primary.model, temperature, json_mode)
    if use_cache:
        cached = storage.get_llm_cache(h)
        if cached is not None:
            return cached

    errors: list[str] = []
    chain = [primary_name]
    if FALLBACK not in chain:
        chain.append(FALLBACK)

    for pname in chain:
        cfg = PROVIDERS[pname]
        try:
            out = _call_provider(cfg, messages, temperature, max_tokens, json_mode)
            if use_cache:
                storage.cache_llm(h, cfg.name, cfg.model, prompt_name, out)
            return out
        except Exception as exc:  # includes rate-limit (429) -> fall through to fallback
            errors.append(f"{pname}: {type(exc).__name__}: {exc}")
            continue

    raise LLMError("all providers failed -> " + " | ".join(errors))


def complete_json(messages: list[dict], *, schema_keys: list[str] | None = None,
                  **kwargs: Any) -> dict[str, Any]:
    """Completion that must return a JSON object. Validates presence of required top-level keys.

    Schema validation is intentionally strict-but-light here; engine-facing structures get full
    validation at their own boundary. This guards against the LLM inventing shape.
    """
    kwargs["json_mode"] = True
    raw = complete(messages, **kwargs)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM did not return valid JSON: {exc}\n---\n{raw[:500]}")
    if not isinstance(data, dict):
        raise LLMError(f"LLM returned non-object JSON: {type(data).__name__}")
    if schema_keys:
        missing = [k for k in schema_keys if k not in data]
        if missing:
            raise LLMError(f"LLM JSON missing required keys: {missing}")
    return data


def load_prompt(name: str) -> str:
    """Load a prompt template from backend/prompts/<name>.txt."""
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise LLMError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def health() -> dict[str, Any]:
    """Report which providers have keys present. Does NOT spend a request."""
    return {
        "primary": PRIMARY,
        "fallback": FALLBACK,
        "providers": {
            name: {"model": cfg.model, "key_present": bool(os.getenv(cfg.api_key_env))}
            for name, cfg in PROVIDERS.items()
        },
    }
