"""Tests for the OpenAI-compatible LLM client."""
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


def test_generate_json_parses_object_and_requests_json_format():
    payload = {"choices": [{"message": {"content": '{"summary": "s", "tags": ["a"]}'}}]}
    with patch("article_generator.llm.requests.post", return_value=make_response(payload=payload)) as post:
        assert client().generate_json("sys", "user") == {"summary": "s", "tags": ["a"]}
    assert post.call_args.kwargs["json"]["response_format"] == {"type": "json_object"}


def test_generate_json_strips_code_fences():
    payload = {"choices": [{"message": {"content": '```json\n{"tags": []}\n```'}}]}
    with patch("article_generator.llm.requests.post", return_value=make_response(payload=payload)):
        assert client().generate_json("sys", "user") == {"tags": []}


def test_generate_json_raises_on_invalid_json():
    payload = {"choices": [{"message": {"content": "not json"}}]}
    with patch("article_generator.llm.requests.post", return_value=make_response(payload=payload)):
        with pytest.raises(LLMError, match="JSON"):
            client().generate_json("sys", "user")


def test_generate_json_raises_on_non_object():
    payload = {"choices": [{"message": {"content": "[1, 2]"}}]}
    with patch("article_generator.llm.requests.post", return_value=make_response(payload=payload)):
        with pytest.raises(LLMError, match="JSON"):
            client().generate_json("sys", "user")
