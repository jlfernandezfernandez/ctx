"""Minimal client for any OpenAI-compatible chat completions API.

Provider-agnostic on purpose: switching provider means changing
LLM_BASE_URL / LLM_API_KEY / LLM_MODEL, nothing else.
"""
import json

import requests


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 600):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, system: str, user: str) -> str:
        return self._chat(system, user)

    def generate_json(self, system: str, user: str) -> dict:
        """For metadata extraction. Falls back gracefully at call sites:
        providers without json_object support usually still return JSON text."""
        content = self._chat(system, user, response_format={"type": "json_object"})
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise LLMError(f"LLM did not return valid JSON: {content[:300]}") from exc
        if not isinstance(data, dict):
            raise LLMError(f"LLM JSON is not an object: {content[:300]}")
        return data

    def _chat(self, system: str, user: str, **extra) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                **extra,
            },
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"LLM API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected LLM response shape: {str(data)[:500]}") from exc
        if not content or not content.strip():
            raise LLMError("LLM returned empty content")
        return content.strip()
