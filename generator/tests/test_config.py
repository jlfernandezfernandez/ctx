"""Tests for LLM provider and agent routing configuration."""
import pytest

from article_generator.config import Provider, load_config

ENV = {
    "OLLAMA_BASE_URL": "https://ollama.com/v1",
    "OLLAMA_API_KEY": "ok",
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    "OPENROUTER_API_KEY": "rk",
    "AGENT_TRIAGE_PROVIDER": "openrouter",
    "AGENT_TRIAGE_MODEL": "triage-m",
    "AGENT_WRITER_PROVIDER": "ollama",
    "AGENT_WRITER_MODEL": "writer-m",
    "AGENT_WRITER_JSON_PROVIDER": "openrouter",
    "AGENT_WRITER_JSON_MODEL": "writer-json-m",
    "AGENT_REVIEWER_PROVIDER": "openrouter",
    "AGENT_REVIEWER_MODEL": "reviewer-m",
}


def test_load_config_reads_only_requested_agents():
    config = load_config(ENV, "TRIAGE", "WRITER")
    assert set(config.agents) == {"TRIAGE", "WRITER"}
    assert set(config.providers) == {Provider.OPENROUTER, Provider.OLLAMA}
    assert config.agents["TRIAGE"].provider == Provider.OPENROUTER
    assert config.agents["WRITER"].model == "writer-m"


def test_load_config_rejects_unknown_provider():
    bad = {**ENV, "AGENT_TRIAGE_PROVIDER": "unknown"}
    with pytest.raises(ValueError, match="Provider"):
        load_config(bad, "TRIAGE")
