"""Tests for the OpenAI-compatible LLM client."""
from unittest.mock import patch, MagicMock

import pytest

from daily_journal_generator.llm import LLMClient, LLMError


def make_response(status=200, payload=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = text
    return resp


def client():
    return LLMClient(base_url="https://llm.example/v1/", api_key="k", model="m")


def test_generate_returns_message_content():
    payload = {"choices": [{"message": {"content": " hola "}}]}
    with patch("daily_journal_generator.llm.requests.post", return_value=make_response(payload=payload)) as post:
        assert client().generate("sys", "user") == "hola"
    args, kwargs = post.call_args
    assert args[0] == "https://llm.example/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer k"
    assert kwargs["json"]["model"] == "m"
    assert kwargs["json"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]


def test_generate_raises_on_http_error():
    with patch("daily_journal_generator.llm.requests.post", return_value=make_response(status=500, text="boom")):
        with pytest.raises(LLMError, match="500"):
            client().generate("sys", "user")


def test_generate_raises_on_unexpected_shape():
    with patch("daily_journal_generator.llm.requests.post", return_value=make_response(payload={"oops": True})):
        with pytest.raises(LLMError):
            client().generate("sys", "user")


def test_generate_raises_on_empty_content():
    payload = {"choices": [{"message": {"content": "  "}}]}
    with patch("daily_journal_generator.llm.requests.post", return_value=make_response(payload=payload)):
        with pytest.raises(LLMError, match="empty"):
            client().generate("sys", "user")
