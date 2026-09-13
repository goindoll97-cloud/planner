from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Mapping
from urllib.parse import urlparse

import requests


DEFAULT_PROVIDER = "ollama"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OPENAI_COMPATIBLE_URL = "http://127.0.0.1:1234"
DEFAULT_MODEL = "qwen3:14b"

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class LocalLLMConfig:
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_OLLAMA_URL
    timeout_seconds: int = 180
    max_output_tokens: int = 12000


def validate_local_base_url(base_url: str) -> str:
    """Allow only loopback endpoints so company data cannot be sent remotely."""
    value = str(base_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("로컬 LLM 주소가 비어 있습니다.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("로컬 LLM 주소는 http 또는 https 형식이어야 합니다.")
    hostname = (parsed.hostname or "").lower()
    if hostname not in _LOCAL_HOSTS:
        raise ValueError(
            "보안을 위해 AI 문장 보강은 127.0.0.1/localhost/::1 로컬 주소만 허용합니다. "
            "회사 자료를 외부 또는 원격 서버로 전송할 수 없습니다."
        )
    return value


def local_llm_config_from_sources(values: Mapping[str, Any] | None = None) -> LocalLLMConfig:
    values = values or {}

    def _get(name: str, default: str = "") -> str:
        value = values.get(name)
        if value not in (None, ""):
            return str(value).strip()
        return str(os.getenv(name, default) or "").strip()

    provider = (_get("LOCAL_LLM_PROVIDER", DEFAULT_PROVIDER) or DEFAULT_PROVIDER).lower()
    if provider not in {"ollama", "openai_compatible"}:
        raise ValueError("LOCAL_LLM_PROVIDER는 ollama 또는 openai_compatible 이어야 합니다.")

    default_url = DEFAULT_OLLAMA_URL if provider == "ollama" else DEFAULT_OPENAI_COMPATIBLE_URL
    base_url = validate_local_base_url(_get("LOCAL_LLM_URL", default_url) or default_url)
    model = _get("LOCAL_LLM_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL

    try:
        timeout = max(30, int(_get("LOCAL_LLM_TIMEOUT_SECONDS", "180")))
    except ValueError:
        timeout = 180
    try:
        max_tokens = max(1000, int(_get("LOCAL_LLM_MAX_OUTPUT_TOKENS", "12000")))
    except ValueError:
        max_tokens = 12000

    return LocalLLMConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout,
        max_output_tokens=max_tokens,
    )


def _parse_json_object(text: str) -> Mapping[str, Any]:
    source = str(text or "").strip()
    if source.startswith("```"):
        source = source.removeprefix("```json").removeprefix("```").strip()
        if source.endswith("```"):
            source = source[:-3].strip()
    try:
        data = json.loads(source)
    except json.JSONDecodeError:
        start = source.find("{")
        end = source.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("로컬 LLM 응답이 JSON 객체 형식이 아닙니다.")
        data = json.loads(source[start : end + 1])
    if not isinstance(data, Mapping):
        raise ValueError("로컬 LLM 응답 JSON의 최상위 값은 객체여야 합니다.")
    return data


class OllamaLocalClient:
    def __init__(self, config: LocalLLMConfig) -> None:
        self.config = config
        self.model = config.model
        self.base_url = validate_local_base_url(config.base_url)

    def generate_json(self, *, instructions: str, prompt: str) -> Mapping[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "format": "json",
                "options": {"num_predict": self.config.max_output_tokens},
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json()
        message = raw.get("message")
        text = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Ollama 응답에서 문장 출력을 찾지 못했습니다.")
        return _parse_json_object(text)


class OpenAICompatibleLocalClient:
    """Local OpenAI-compatible client for LM Studio/llama.cpp style servers.

    No API key is sent. The endpoint is loopback-only by construction.
    """

    def __init__(self, config: LocalLLMConfig) -> None:
        self.config = config
        self.model = config.model
        self.base_url = validate_local_base_url(config.base_url)

    def generate_json(self, *, instructions: str, prompt: str) -> Mapping[str, Any]:
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": self.config.max_output_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json()
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("로컬 OpenAI 호환 서버 응답에서 choices를 찾지 못했습니다.")
        first = choices[0]
        message = first.get("message") if isinstance(first, Mapping) else None
        text = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("로컬 OpenAI 호환 서버 응답에서 문장 출력을 찾지 못했습니다.")
        return _parse_json_object(text)


def build_local_llm_client(config: LocalLLMConfig):
    validate_local_base_url(config.base_url)
    if config.provider == "ollama":
        return OllamaLocalClient(config)
    if config.provider == "openai_compatible":
        return OpenAICompatibleLocalClient(config)
    raise ValueError("지원하지 않는 로컬 LLM 공급자입니다.")


def local_runtime_label(config: LocalLLMConfig) -> str:
    provider = "Ollama" if config.provider == "ollama" else "로컬 OpenAI 호환 서버"
    return f"{provider} · {config.model} · {config.base_url}"
