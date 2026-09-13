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


@dataclass(frozen=True)
class LocalLLMProbe:
    connected: bool
    provider: str
    base_url: str
    models: tuple[str, ...] = ()
    selected_model_available: bool = False
    message: str = ""

    @property
    def ready(self) -> bool:
        return self.connected and self.selected_model_available


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


def local_runtime_setup_steps(config: LocalLLMConfig) -> tuple[str, ...]:
    if config.provider == "ollama":
        return (
            "Ollama가 설치되어 있지 않으면 먼저 이 PC에 설치합니다.",
            "Ollama 앱을 실행합니다. 서버가 자동으로 시작되지 않으면 명령 프롬프트에서 `ollama serve`를 실행합니다.",
            "명령 프롬프트에서 `ollama list`로 설치된 모델을 확인합니다.",
            f"현재 설정 모델이 없으면 `ollama pull {config.model}`로 모델을 설치하거나, 프로그램의 모델 이름을 이미 설치된 모델명으로 바꿉니다.",
            f"프로그램의 로컬 주소는 `{config.base_url}`로 사용합니다.",
        )
    return (
        "LM Studio 등 OpenAI 호환 로컬 실행기를 이 PC에서 실행합니다.",
        "로컬 서버 기능을 시작하고 외부 네트워크 공개가 아닌 로컬 PC 전용으로 사용합니다.",
        "사용할 모델을 먼저 로드합니다.",
        f"프로그램의 로컬 주소는 `{config.base_url}`로 사용합니다.",
        "연결 후 서버에 표시되는 모델 ID를 프로그램의 로컬 모델 이름에 입력합니다.",
    )


def _extract_ollama_models(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        return ()
    rows = payload.get("models")
    if not isinstance(rows, list):
        return ()
    names: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or row.get("model") or "").strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _extract_openai_models(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        return ()
    rows = payload.get("data")
    if not isinstance(rows, list):
        return ()
    names: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("id") or "").strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _model_matches(selected: str, available: tuple[str, ...]) -> bool:
    target = str(selected or "").strip()
    if not target:
        return False
    if target in available:
        return True
    return f"{target}:latest" in available or (target.endswith(":latest") and target[:-7] in available)


def probe_local_llm_runtime(config: LocalLLMConfig, *, timeout_seconds: float = 2.5) -> LocalLLMProbe:
    """Check only the loopback runtime and list locally available models.

    This probe never sends company/project content. It only calls the runtime's
    local model-list endpoint.
    """
    base_url = validate_local_base_url(config.base_url)
    endpoint = f"{base_url}/api/tags" if config.provider == "ollama" else f"{base_url}/v1/models"
    try:
        response = requests.get(endpoint, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except requests.ConnectionError:
        provider_label = "Ollama" if config.provider == "ollama" else "로컬 AI 서버"
        return LocalLLMProbe(
            connected=False,
            provider=config.provider,
            base_url=base_url,
            message=f"{provider_label}에 연결할 수 없습니다. 이 PC에서 로컬 AI 서버를 먼저 실행하세요.",
        )
    except requests.Timeout:
        return LocalLLMProbe(
            connected=False,
            provider=config.provider,
            base_url=base_url,
            message="로컬 AI 서버 응답 시간이 초과되었습니다. 서버가 정상 실행 중인지 확인하세요.",
        )
    except requests.RequestException as exc:
        return LocalLLMProbe(
            connected=False,
            provider=config.provider,
            base_url=base_url,
            message=f"로컬 AI 서버 상태 확인에 실패했습니다: {type(exc).__name__}",
        )
    except (ValueError, json.JSONDecodeError):
        return LocalLLMProbe(
            connected=False,
            provider=config.provider,
            base_url=base_url,
            message="로컬 AI 서버가 예상한 상태정보 형식으로 응답하지 않았습니다. 실행기 종류와 주소를 확인하세요.",
        )

    models = _extract_ollama_models(payload) if config.provider == "ollama" else _extract_openai_models(payload)
    selected_available = _model_matches(config.model, models)
    if not models:
        message = "로컬 AI 서버에는 연결되었지만 사용할 수 있는 모델을 찾지 못했습니다. 모델을 설치하거나 로드하세요."
    elif not selected_available:
        message = f"로컬 AI 서버는 실행 중이지만 현재 설정 모델 '{config.model}'을 찾지 못했습니다. 설치·로드된 모델 중 하나를 선택하세요."
    else:
        message = f"로컬 AI 서버와 모델 '{config.model}'을 사용할 수 있습니다."
    return LocalLLMProbe(
        connected=True,
        provider=config.provider,
        base_url=base_url,
        models=models,
        selected_model_available=selected_available,
        message=message,
    )


def local_runtime_not_ready_message(config: LocalLLMConfig, probe: LocalLLMProbe) -> str:
    parts = [probe.message]
    if probe.models and not probe.selected_model_available:
        parts.append("현재 사용 가능한 모델: " + ", ".join(probe.models[:12]))
    parts.append("조치 방법: " + " → ".join(local_runtime_setup_steps(config)))
    return " ".join(part for part in parts if part)


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
    probe = probe_local_llm_runtime(config)
    if not probe.ready:
        raise ValueError(local_runtime_not_ready_message(config, probe))
    if config.provider == "ollama":
        return OllamaLocalClient(config)
    if config.provider == "openai_compatible":
        return OpenAICompatibleLocalClient(config)
    raise ValueError("지원하지 않는 로컬 LLM 공급자입니다.")


def local_runtime_label(config: LocalLLMConfig) -> str:
    provider = "Ollama" if config.provider == "ollama" else "로컬 OpenAI 호환 서버"
    return f"{provider} · {config.model} · {config.base_url}"
