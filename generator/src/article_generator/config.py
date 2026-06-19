"""LLM provider and agent routing configuration."""
from dataclasses import dataclass
from enum import Enum


class Provider(str, Enum):
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key: str


@dataclass(frozen=True)
class AgentConfig:
    provider: Provider
    model: str


@dataclass(frozen=True)
class AppConfig:
    providers: dict[Provider, ProviderConfig]
    agents: dict[str, AgentConfig]


def _provider(env: dict, name: Provider) -> ProviderConfig:
    prefix = name.value.upper()
    return ProviderConfig(
        base_url=env[f"{prefix}_BASE_URL"],
        api_key=env[f"{prefix}_API_KEY"],
    )


def _agent(env: dict, name: str) -> AgentConfig:
    return AgentConfig(
        provider=Provider(env[f"AGENT_{name}_PROVIDER"]),
        model=env[f"AGENT_{name}_MODEL"],
    )


def load_config(env: dict, *agent_names: str) -> AppConfig:
    agents = {name: _agent(env, name) for name in agent_names}
    providers = {
        agents[name].provider: _provider(env, agents[name].provider)
        for name in agent_names
    }
    return AppConfig(providers=providers, agents=agents)
