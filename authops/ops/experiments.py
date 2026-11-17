"""Experiments platform: model arms and the human-QA ramp.

Portals have no staging, so changes are tested live on a controlled share of traffic:

* Arm assignment: each case is hashed into a weighted arm (e.g. 50% playbook policy,
  50% Claude Haiku), so arms see comparable cases and the split is reproducible.
* QA ramp: per portal, a share of runs is routed to human QA before (in production)
  the submission goes out. The share starts at 100% for a new portal and is lowered
  in steps only while success, smoothness and the audited silent-error rate hold;
  any regression pushes it back up. This is the "reduce human QA as metrics
  improve" loop, made explicit and testable.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Arm:
    name: str
    make_policy: Callable[[str], object]  # portal -> policy
    weight: float


class Experiment:
    def __init__(self, name: str, arms: list[Arm]):
        self.name = name
        self.arms = arms
        total = sum(a.weight for a in arms)
        self.cum = []
        acc = 0.0
        for a in arms:
            acc += a.weight / total
            self.cum.append((acc, a))

    def assign(self, case_id: str) -> Arm:
        u = int(hashlib.sha256(f"{self.name}:{case_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        for edge, arm in self.cum:
            if u <= edge:
                return arm
        return self.arms[-1]


@dataclass
class RampState:
    qa_share: float = 1.0
    history: list[dict] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


class QARamp:
    def __init__(self, window: int = 8, floor: float = 0.1, step: float = 0.3,
                 min_success: float = 0.9, min_smooth: float = 80.0, seed: int = 5, max_silent: int = 0):
        self.window, self.floor, self.step = window, floor, step
        self.min_success, self.min_smooth = min_success, min_smooth
        self.max_silent = max_silent  # silent errors tolerated per window before the share goes back up
        self.state: dict[str, RampState] = {}
        self.rng = random.Random(seed)

    def route_to_qa(self, portal: str) -> bool:
        st = self.state.setdefault(portal, RampState())
        return self.rng.random() < st.qa_share

    def record(self, portal: str, success: bool, smooth: float, silent_error: bool) -> None:
        st = self.state.setdefault(portal, RampState())
        st.history.append({"success": success, "smooth": smooth, "silent_error": silent_error})
        if len(st.history) % self.window:
            return
        w = st.history[-self.window:]
        sr = sum(r["success"] for r in w) / len(w)
        sm = sum(r["smooth"] for r in w) / len(w)
        se = sum(r["silent_error"] for r in w)
        before = st.qa_share
        if sr >= self.min_success and sm >= self.min_smooth and se <= self.max_silent:
            st.qa_share = max(self.floor, round(st.qa_share - self.step, 2))
        elif sr < self.min_success - 0.15 or se > self.max_silent:
            st.qa_share = min(1.0, round(st.qa_share + 2 * self.step, 2))
        st.log.append(f"after {len(st.history)} runs: success {sr:.2f}, smoothness {sm:.0f}, "
                      f"silent errors {se} -> QA share {before:.2f} -> {st.qa_share:.2f}")
