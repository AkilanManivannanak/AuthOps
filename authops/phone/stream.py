"""Streaming speech path for the phone agent: sentence chunking, latency budget, interruptions.

Three things Silna describes for its chained voice pipeline, built so they can be tested without
audio:

* Sentence-level streaming. The LLM's text is cut into speakable chunks as it arrives and each
  chunk goes to TTS immediately, so the caller hears the first words while the model is still
  writing. Chunks never split a member ID, a date or a dollar amount.
* A latency budget per stage. `simulate_turn` adds up STT finalization, LLM time to first token,
  token rate and TTS time to first byte, with and without streaming, and checks the result
  against the IVR's silence timeout. The stage timings are assumptions you pass in (defaults are
  stated below), so the output is a model of the pipeline, not a measurement of a vendor.
* Interruption handling with play marks. Each chunk gets a mark when it finishes playing. If the
  other side starts talking, queued chunks are dropped and the transcript records only what was
  actually heard, so the audit trail never claims the agent said a member ID it never finished.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

# keep these together inside one spoken chunk
_PROTECT = re.compile(r"(?:[A-Z]\s){2}[A-Z](?:\s(?:zero|one|two|three|four|five|six|seven|eight|nine))+|"
                      r"(?:(?:zero|one|two|three|four|five|six|seven|eight|nine)\s?){4,}|"
                      r"[A-Z][a-z]+ \d{1,2}, \d{4}|\$?\d[\d,]*(?:\.\d+)?")
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|(?<=[,;:])\s+(?=\S{3,})")


def speakable_chunks(text: str, min_words: int = 4) -> list[str]:
    """Split text into chunks a TTS engine can start on, never inside a protected span."""
    protected = [(m.start(), m.end()) for m in _PROTECT.finditer(text)]
    cuts, last = [], 0
    for m in _BOUNDARY.finditer(text):
        if any(a < m.start() < b for a, b in protected):
            continue
        piece = text[last:m.start()].strip()
        if len(piece.split()) >= min_words:
            cuts.append(piece)
            last = m.end()
    tail = text[last:].strip()
    if tail:
        if cuts and len(tail.split()) < min_words:
            cuts[-1] = cuts[-1] + " " + tail
        else:
            cuts.append(tail)
    return cuts


@dataclass
class Budget:
    """Stage timings in milliseconds. Defaults are assumptions, documented, not vendor numbers."""
    stt_final_ms: float = 250       # end of caller speech -> final transcript
    llm_first_token_ms: float = 450
    llm_tokens_per_s: float = 60
    tts_first_byte_ms: float = 180
    ivr_silence_timeout_ms: float = 3000   # IVRs repeat or hang up after a few seconds of silence
    jitter: float = 0.35            # lognormal-ish spread applied per stage


def _j(x: float, rng: random.Random, jitter: float) -> float:
    return x * rng.lognormvariate(0, jitter)


def simulate_turn(reply: str, budget: Budget, rng: random.Random, streaming: bool) -> float:
    """Milliseconds from the end of the caller's speech to the first audio the caller hears."""
    tok = lambda s: max(1, round(len(s.split()) * 1.3))  # noqa: E731  rough tokens per word
    stt = _j(budget.stt_final_ms, rng, budget.jitter)
    first = _j(budget.llm_first_token_ms, rng, budget.jitter)
    rate = budget.llm_tokens_per_s / rng.lognormvariate(0, budget.jitter / 2)
    tts = _j(budget.tts_first_byte_ms, rng, budget.jitter)
    if streaming:
        chunk = speakable_chunks(reply)[0]
        return stt + first + tok(chunk) / rate * 1000 + tts
    return stt + first + tok(reply) / rate * 1000 + tts


def latency_report(replies: list[str], budget: Budget | None = None, seed: int = 3, n: int = 400) -> dict:
    budget = budget or Budget()
    out = {}
    for streaming in (False, True):
        rng = random.Random(seed)
        xs = sorted(simulate_turn(rng.choice(replies), budget, rng, streaming) for _ in range(n))
        out["streaming" if streaming else "full_response"] = {
            "p50_ms": round(xs[n // 2]), "p95_ms": round(xs[int(n * .95)]),
            "over_ivr_timeout": round(sum(x > budget.ivr_silence_timeout_ms for x in xs) / n, 3)}
    out["assumptions"] = budget.__dict__
    return out


@dataclass
class Playback:
    """Queued TTS chunks with play marks; an interruption drops what has not played."""
    queue: list[str] = field(default_factory=list)
    heard: list[str] = field(default_factory=list)   # chunks whose play mark came back
    dropped: list[str] = field(default_factory=list)

    def say(self, text: str) -> None:
        self.queue.extend(speakable_chunks(text))

    def mark(self) -> None:
        """The telephony side confirms the oldest queued chunk finished playing."""
        if self.queue:
            self.heard.append(self.queue.pop(0))

    def interrupt(self) -> None:
        """Caller barged in: clear the queue (cancel LLM + TTS + telephony buffer)."""
        self.dropped.extend(self.queue)
        self.queue.clear()

    def transcript(self) -> str:
        return " ".join(self.heard)
