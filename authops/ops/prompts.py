"""Prompt registry and regression gate: prompt strategies that are reproducible, not folklore.

Every prompt lives in prompts/<id>/<version>.yaml with its model, token limit, owner, status
and a changelog that states the hypothesis behind the change. A version's fingerprint is the
SHA-256 of model + template, so any backtest result can be traced to the exact text that
produced it.

A candidate replaces production only through gate(): it is backtested on the same golden
documents as the production version and is blocked if it lowers overall accuracy, raises
silent errors (wrong values sent with confidence), or drops any critical field by more than
the tolerance. Every backtest is appended to reports/prompt_backtests.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROMPT_DIR = ROOT / "prompts"
LOG = ROOT / "reports" / "prompt_backtests.jsonl"


@dataclass
class Prompt:
    id: str
    version: str
    template: str
    model: str
    max_tokens: int = 1500
    status: str = "candidate"
    owner: str = ""
    purpose: str = ""
    changelog: str = ""

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256((self.model + "\n" + self.template).encode()).hexdigest()[:12]


def load(ref: str, root: Path = PROMPT_DIR) -> Prompt:
    pid, ver = ref.split("@")
    d = yaml.safe_load((root / pid / f"{ver}.yaml").read_text())
    return Prompt(**{k: d[k] for k in Prompt.__dataclass_fields__ if k in d})


def versions(pid: str, root: Path = PROMPT_DIR) -> list[Prompt]:
    return [load(f"{pid}@{p.stem}", root) for p in sorted((root / pid).glob("v*.yaml"))]


def production(pid: str, root: Path = PROMPT_DIR) -> Prompt:
    live = [p for p in versions(pid, root) if p.status == "production"]
    if len(live) != 1:
        raise ValueError(f"{pid}: expected exactly one production version, found {len(live)}")
    return live[0]


def dataset_fingerprint(manifest: list[dict]) -> str:
    key = json.dumps([(m["doc_id"], m.get("truth")) for m in manifest], sort_keys=True, default=str)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def field_accuracy(rows: list[dict]) -> dict[str, float]:
    tot: dict[str, list[int]] = {}
    for r in rows:
        t = tot.setdefault(r["field"], [0, 0])
        t[0] += bool(r["ok"])
        t[1] += 1
    return {f: round(c / n, 3) for f, (c, n) in tot.items()}


def gate(base: dict, cand: dict, critical: set[str], tol_field: float = 0.02, tol_overall: float = 0.0) -> dict:
    """base/cand: {"summary": {...}, "rows": [...]} from docintel.evaluate.score."""
    b, c = base["summary"]["all"], cand["summary"]["all"]
    fb, fc = field_accuracy(base["rows"]), field_accuracy(cand["rows"])
    reasons = []
    if c["accuracy"] < b["accuracy"] - tol_overall:
        reasons.append(f"overall accuracy fell {b['accuracy']:.3f} -> {c['accuracy']:.3f}")
    if c["silent_error"] > b["silent_error"]:
        reasons.append(f"silent errors rose {b['silent_error']:.3f} -> {c['silent_error']:.3f}")
    drops = {f: (fb[f], fc.get(f, 0.0)) for f in critical if f in fb and fc.get(f, 0.0) < fb[f] - tol_field}
    for f, (x, y) in sorted(drops.items()):
        reasons.append(f"critical field {f} fell {x:.3f} -> {y:.3f}")
    gains = {f: (fb[f], fc[f]) for f in fb if f in fc and fc[f] > fb[f] + tol_field}
    return {"promote": not reasons, "reasons": reasons,
            "overall": {"base": b, "candidate": c},
            "field_deltas": {f: round(fc.get(f, 0.0) - fb[f], 3) for f in sorted(fb)},
            "improved_fields": sorted(gains)}


def record(base: Prompt, cand: Prompt, dataset: str, verdict: dict, extra: dict | None = None, log: Path = LOG) -> dict:
    entry = {"ts": time.strftime("%Y-%m-%d %H:%M"), "base": base.ref, "base_fp": base.fingerprint,
             "candidate": cand.ref, "candidate_fp": cand.fingerprint, "model": cand.model, "dataset": dataset,
             "promote": verdict["promote"], "reasons": verdict["reasons"],
             "accuracy": [verdict["overall"]["base"]["accuracy"], verdict["overall"]["candidate"]["accuracy"]],
             "silent_error": [verdict["overall"]["base"]["silent_error"], verdict["overall"]["candidate"]["silent_error"]],
             "field_deltas": verdict["field_deltas"], **(extra or {})}
    log.parent.mkdir(exist_ok=True)
    with log.open("a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    return entry
