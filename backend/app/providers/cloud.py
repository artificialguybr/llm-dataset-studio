"""Small stdlib-only adapters for hosted text-LLM providers.

The provider registry decides *which* service runs. This module only translates
a prompt+text request into each vendor's HTTP contract. Any OpenAI-compatible
endpoint (OpenAI, Ollama, vLLM, LM Studio) works by pointing the base URL
at it in Settings.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from ..config import get_settings, provider_model


def _request(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"{url} returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach {url}: {exc.reason}") from exc


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "content", "caption", "output", "response"):
            if key in value:
                return _text(value[key])
    return str(value)


def _normalize(payload: Any) -> dict[str, Any]:
    """Extrai texto + JSON embutido da resposta do LLM (formato livre)."""
    output = payload.get("output", payload) if isinstance(payload, dict) else payload
    if isinstance(output, dict):
        result = dict(output)
        text = _text(output)
    else:
        text = _text(output)
        result = {"text": text}
    result.setdefault("text", text)
    result.setdefault("caption", text)
    if text:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict):
                    result.update(parsed)
            except json.JSONDecodeError:
                pass
    return result


def call_text(provider: str, text: str, prompt: str, capability: str) -> dict[str, Any]:
    """Envia prompt+texto para um LLM hospedado e devolve o resultado normalizado."""
    settings = get_settings()
    model = provider_model(provider, capability)
    if not model:
        raise RuntimeError(f"no {provider} model configured for {capability}")
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user",
                      "content": prompt + "\n\n---\n" + text}],
        "temperature": 0,
    }
    if provider == "openai":
        payload = _request(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            {"authorization": f"Bearer {settings.openai_api_key}"},
            body,
        )
        content = payload["choices"][0]["message"]["content"]
        return _normalize(content)
    raise ValueError(f"unsupported cloud provider: {provider}")
