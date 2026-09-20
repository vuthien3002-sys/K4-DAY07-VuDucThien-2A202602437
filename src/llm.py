"""Small, dependency-light LLM adapters for the lab demo."""

from __future__ import annotations

import json
import os
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


GEMINI_LLM_MODEL = "gemini-3.6-flash"
OPENROUTER_LLM_MODEL = "google/gemini-2.5-flash"


class RemoteLLM:
    """Call Gemini or OpenRouter without adding another Python SDK dependency."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._backend_name = f"{provider}:{model}"

    def __call__(self, prompt: str) -> str:
        if self.provider == "gemini":
            return self._call_gemini(prompt)
        if self.provider == "openrouter":
            return self._call_openrouter(prompt)
        raise RuntimeError(f"Unsupported LLM provider: {self.provider}")

    def _post_json(self, url: str, payload: dict, headers: dict[str, str]) -> dict:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=60) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                if error.code in {429, 500, 503} and attempt < 2:
                    time.sleep(1.5 * (2**attempt))
                    continue
                detail = error.read().decode("utf-8", errors="replace")[:400]
                raise RuntimeError(f"{self.provider} request failed ({error.code}): {detail}") from error
            except URLError as error:
                raise RuntimeError(f"{self.provider} network request failed: {error.reason}") from error
        raise RuntimeError(f"{self.provider} request failed after retries")

    def _call_gemini(self, prompt: str) -> str:
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }
        data = self._post_json(endpoint, payload, {})
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        answer = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not answer:
            raise RuntimeError("Gemini returned no text content")
        return answer.strip()

    def _call_openrouter(self, prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        site_url = os.getenv("OPENROUTER_SITE_URL", "").strip()
        app_name = os.getenv("OPENROUTER_APP_NAME", "K4-L3B PolicyLens").strip()
        if site_url:
            headers["HTTP-Referer"] = site_url
        if app_name:
            headers["X-Title"] = app_name

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        data = self._post_json("https://openrouter.ai/api/v1/chat/completions", payload, headers)
        message = data.get("choices", [{}])[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            )
        if not content:
            raise RuntimeError("OpenRouter returned no text content")
        return str(content).strip()


def resolve_llm_from_env(fallback: Callable[[str], str]) -> Callable[[str], str]:
    """Return a configured remote LLM, or the deterministic fallback."""
    load_dotenv(override=False)
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "600"))

    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key:
            return RemoteLLM(
                provider="gemini",
                api_key=api_key,
                model=os.getenv("GEMINI_LLM_MODEL", GEMINI_LLM_MODEL).strip(),
                temperature=temperature,
                max_tokens=max_tokens,
            )
    elif provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if api_key:
            return RemoteLLM(
                provider="openrouter",
                api_key=api_key,
                model=os.getenv("OPENROUTER_MODEL", OPENROUTER_LLM_MODEL).strip(),
                temperature=temperature,
                max_tokens=max_tokens,
            )

    return fallback
