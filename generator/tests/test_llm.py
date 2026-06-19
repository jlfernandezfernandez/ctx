"""Tests for the OpenAI-compatible LLM client."""
import os
from unittest.mock import patch, MagicMock

import pytest

from article_generator.llm import LLMClient, LLMError


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
    with patch("article_generator.llm.requests.post", return_value=make_response(payload=payload)) as post:
        assert client().generate("sys", "user") == "hola"
    args, kwargs = post.call_args
    assert args[0] == "https://llm.example/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer k"
    assert kwargs["json"]["model"] == "m"
    assert kwargs["json"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]


def test_generate_passes_optional_completion_parameters():
    payload = {"choices": [{"message": {"content": "ok"}}]}
    with patch("article_generator.llm.requests.post", return_value=make_response(payload=payload)) as post:
        client().generate("sys", "user", temperature=0, max_tokens=100)
    assert post.call_args.kwargs["json"]["temperature"] == 0
    assert post.call_args.kwargs["json"]["max_tokens"] == 100


def test_generate_raises_on_http_error():
    with patch("article_generator.llm.requests.post", return_value=make_response(status=500, text="boom")):
        with pytest.raises(LLMError, match="500"):
            client().generate("sys", "user")


def test_generate_raises_on_unexpected_shape():
    with patch("article_generator.llm.requests.post", return_value=make_response(payload={"oops": True})):
        with pytest.raises(LLMError):
            client().generate("sys", "user")


def test_generate_raises_on_empty_content():
    payload = {"choices": [{"message": {"content": "  "}}]}
    with patch("article_generator.llm.requests.post", return_value=make_response(payload=payload)):
        with pytest.raises(LLMError, match="empty"):
            client().generate("sys", "user")


def test_generate_structured_uses_json_schema():
    schema = {
        "title": "test",
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
        "additionalProperties": False,
    }
    payload = {"choices": [{"message": {"content": '{"x": 1}'}}]}
    with patch("article_generator.llm.requests.post", return_value=make_response(payload=payload)) as post:
        assert client().generate_structured("sys", "user", schema) == {"x": 1}
    rf = post.call_args.kwargs["json"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "test"
    assert rf["json_schema"]["strict"] is True


def test_generate_structured_raises_on_invalid_json():
    payload = {"choices": [{"message": {"content": "not json"}}]}
    with patch("article_generator.llm.requests.post", return_value=make_response(payload=payload)):
        with pytest.raises(LLMError, match="JSON"):
            client().generate_structured("sys", "user", {})


def test_generate_structured_raises_on_non_object():
    payload = {"choices": [{"message": {"content": "[1, 2]"}}]}
    with patch("article_generator.llm.requests.post", return_value=make_response(payload=payload)):
        with pytest.raises(LLMError, match="JSON"):
            client().generate_structured("sys", "user", {})


@pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="needs OPENROUTER_API_KEY for a live OpenRouter call",
)
def test_generate_structured_against_openrouter():
    """Live: OpenRouter honours json_schema strict and returns conforming JSON."""
    llm = LLMClient(
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.getenv("LLM_TEST_MODEL", "openai/gpt-4o-mini"),
    )
    schema = {
        "title": "color",
        "type": "object",
        "properties": {"name": {"type": "string"}, "hex": {"type": "string"}},
        "required": ["name", "hex"],
        "additionalProperties": False,
    }
    data = llm.generate_structured(
        "Eres un conversor de colores.", "Dame el color rojo.", schema
    )
    assert set(data) == {"name", "hex"}
    assert isinstance(data["name"], str) and isinstance(data["hex"], str)
