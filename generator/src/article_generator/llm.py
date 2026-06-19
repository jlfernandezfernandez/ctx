"""Minimal client for any OpenAI-compatible chat completions API.

Provider-agnostic on purpose: the caller decides which provider and model
to use for each task.
"""
import json
import time

import requests


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 600):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate_structured(self, system: str, user: str, schema: dict) -> dict:
        """Generate a response that conforms to the supplied JSON schema."""
        content = self.generate(
            system,
            user,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.get("title", "response"),
                    "strict": True,
                    "schema": schema,
                },
            },
        )
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise LLMError(f"LLM did not return valid JSON: {content[:300]}") from exc
        if not isinstance(data, dict):
            raise LLMError(f"LLM JSON is not an object: {content[:300]}")
        return data

    # ponytail: retry transient errors; cron is daily so a blip = lost day
    RETRY_STATUS = {429, 500, 502, 503, 504}

    def generate(self, system: str, user: str, **extra) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            **extra,
        }
        resp = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                if attempt == 2:
                    raise LLMError(f"LLM request failed: {exc}") from exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code in self.RETRY_STATUS and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            break
        if resp.status_code != 200:
            raise LLMError(f"LLM API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected LLM response shape: {str(data)[:500]}") from exc
        if not content or not content.strip():
            raise LLMError("LLM returned empty content")
        usage = data.get("usage") or {}
        if usage:
            print(
                f"[llm] {self.model} tokens "
                f"in={usage.get('prompt_tokens', '?')} "
                f"out={usage.get('completion_tokens', '?')} "
                f"total={usage.get('total_tokens', '?')}"
            )
        return content.strip()
