"""LLM backends. Anything with `json(kind, system, user, ctx) -> dict` works."""
from __future__ import annotations

import json
import os
import re


def extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model reply: {text[:200]!r}")
    return json.loads(text[start:end + 1])


class AnthropicLLM:
    """Claude backend. Needs `pip install anthropic` and ANTHROPIC_API_KEY."""

    def __init__(self, model: str | None = None):
        import anthropic  # imported lazily so the offline demo has zero dependencies
        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("SKILLFORGE_MODEL", "claude-sonnet-5-5")

    def json(self, kind: str, system: str, user: str, ctx: dict | None = None) -> dict:
        last_err = None
        for _ in range(2):  # one retry if the reply is not valid JSON
            msg = self.client.messages.create(
                model=self.model, max_tokens=4096, system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            try:
                return extract_json(text)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = e
                user += "\n\nYour previous reply was not valid JSON. Reply with JSON only."
        raise RuntimeError(f"model never returned valid JSON: {last_err}")
