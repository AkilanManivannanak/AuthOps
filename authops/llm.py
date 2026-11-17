"""LLM provider abstraction.

Everything in AuthOps runs offline by default. When ANTHROPIC_API_KEY is set, the
Claude-backed paths (LLM extraction, natural-language rules, LLM agent policy, drift
judge) switch on. Every call records latency and tokens so experiments can compare
model arms on cost and speed, not only accuracy.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path


def load_env(path: str | Path = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

# Rough list prices per million tokens, used only for cost-per-auth estimates.
PRICE_PER_MTOK = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-opus-4-1": (15.0, 75.0),
}


@dataclass
class LLMResult:
    text: str
    model: str
    latency_ms: float
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def cost_usd(self) -> float:
        pin, pout = PRICE_PER_MTOK.get(self.model, (3.0, 15.0))
        return (self.tokens_in * pin + self.tokens_out * pout) / 1e6


@dataclass
class UsageMeter:
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: list[float] = field(default_factory=list)

    def add(self, r: LLMResult) -> None:
        self.calls += 1
        self.tokens_in += r.tokens_in
        self.tokens_out += r.tokens_out
        self.cost_usd += r.cost_usd
        self.latency_ms.append(r.latency_ms)


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


class ClaudeLLM:
    def __init__(self, model: str | None = None, meter: UsageMeter | None = None):
        import anthropic  # imported lazily so offline mode needs no SDK

        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("AUTHOPS_MODEL", "claude-haiku-4-5")
        self.meter = meter or UsageMeter()

    def complete(self, prompt: str, system: str = "", images: list[Path] | None = None,
                 max_tokens: int = 1024) -> LLMResult:
        content: list[dict] = []
        for img in images or []:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/png",
                "data": base64.b64encode(Path(img).read_bytes()).decode()}})
        content.append({"type": "text", "text": prompt})
        t0 = time.perf_counter()
        msg = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=0.0,
            system=system or "You are a careful healthcare operations assistant.",
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        r = LLMResult(text=text, model=self.model, latency_ms=(time.perf_counter() - t0) * 1000,
                      tokens_in=msg.usage.input_tokens, tokens_out=msg.usage.output_tokens)
        self.meter.add(r)
        return r


def parse_json(text: str) -> dict | list | None:
    """Pull the last JSON object or array out of a model response."""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None
