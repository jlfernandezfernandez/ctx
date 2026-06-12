"""Loads static system prompts without composing or interpolating them."""
from pathlib import Path


PROMPT_DIR = Path(__file__).with_name("system_prompts")


def load_system_prompt(agent: str) -> str:
    return (PROMPT_DIR / f"{agent}.txt").read_text(encoding="utf-8").strip()
