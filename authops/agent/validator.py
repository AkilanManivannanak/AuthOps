"""Turn validator: a second check on every agent action before it runs.

Silna describes an auto validator that compares each turn against the page and the goal, and
automated detection of claimed UI elements that are not on screen and reasoning that contradicts
the action. This is that check, done deterministically so it is cheap enough for every turn:

* phantom_target   the action names an element that is not in the current observation
* reason_mismatch  the stated reason names a different field than the one being acted on
* unsourced_value  a value being typed is not in the case, the documents, or a document answer
* off_domain       the page left the portal's host (an agent must never follow a link out)

Blocking flags stop the action and go back to the model as a failed step; warnings are persisted
and lower the session's smoothness so QA sees them first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

BLOCKING = {"phantom_target", "unsourced_value", "off_domain"}
SAFE_VALUES = {"yes", "no", "true", "false", "on", "off", "initial", "continuation", "concurrent", "urgent",
               "standard", "routine", "other", "n/a", "na"}
FIELD_WORDS = re.compile(r"(?i)\b(?:click|press|fill|enter|type|select|choose|set|upload)\s+(?:the\s+)?['\"]?([a-z][a-z0-9 _\-/]{2,40}?)['\"]?(?:\s+(?:field|button|box|dropdown|link|with|to|as)\b|[.,]|$)")


@dataclass
class Flag:
    kind: str
    detail: str

    @property
    def blocking(self) -> bool:
        return self.kind in BLOCKING


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _elements(obs) -> list[dict]:
    return [e for f in obs.frames for e in f.elements]


def _matches(target: str, e: dict) -> bool:
    t = _norm(target.lstrip("#"))
    if not t:
        return False
    hay = [_norm(e.get(k, "")) for k in ("id", "name", "label")]
    if t in hay:
        return True
    words = set(re.findall(r"[a-z0-9]+", target.lower()))
    have = set(re.findall(r"[a-z0-9]+", " ".join(e.get(k, "") for k in ("id", "name", "label")).lower()))
    return bool(words) and len(words & have) / len(words) >= 0.6


def _sources(case: dict, values: dict, history: list[dict]) -> set[str]:
    out: set[str] = set()

    def add(v):
        if isinstance(v, (list, tuple)):
            for x in v:
                add(x)
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
        elif v is not None:
            s = str(v)
            out.add(_norm(s))
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):          # dates may be typed in portal format
                y, m, d = s.split("-")
                out.update({_norm(f"{m}/{d}/{y}"), _norm(f"{m}{d}{y}"), _norm(f"{int(m)}/{int(d)}/{y}")})
    add(case)
    add(values)
    for h in history:                                         # answers pulled from documents count
        if h.get("tool") == "answer" and h.get("ok"):
            m = re.search(r"answer '([^']+)'", h.get("detail", ""))
            if m:
                out.add(_norm(m.group(1)))
    return out


def check(obs, act: dict, case: dict, values: dict, history: list[dict], base_url: str,
          playbook: object = None) -> list[Flag]:
    tool, args = act.get("tool"), act.get("args", {}) or {}
    flags: list[Flag] = []
    host = urlparse(base_url).netloc
    if obs.url and host and urlparse(obs.url).netloc not in ("", host):
        flags.append(Flag("off_domain", f"page is on {urlparse(obs.url).netloc}, portal is {host}"))
    target = args.get("target")
    els = _elements(obs)
    if tool in ("click", "fill", "select", "check", "upload", "pick_date") and target:
        if not any(_matches(target, e) for e in els):
            flags.append(Flag("phantom_target", f"'{target}' is not on the page"))
    if tool in ("fill", "select") and "value" in args:
        v = str(args["value"])
        srcs = _sources(case, values, history) | _sources(playbook or {}, {}, [])
        if tool == "select":   # a dropdown value is sourced if it is one of that field's own options
            opts = [o for e in els if _matches(target or "", e) for o in e.get("options", [])]
            srcs |= {_norm(o) for o in opts}
        if _norm(v) and v.lower() not in SAFE_VALUES and _norm(v) not in srcs:
            # partial matches are fine for words ("Physical therapy" vs "physical_therapy");
            # anything with a digit (IDs, units, dates, codes) must match a source exactly
            if re.search(r"\d", v) or not any(_norm(v) in s or s in _norm(v) for s in srcs if len(s) >= 4):
                flags.append(Flag("unsourced_value", f"'{v[:40]}' is not in the case, documents or playbook"))
    reason = str(act.get("reason", ""))
    if reason and target:
        named = [m.group(1).strip() for m in FIELD_WORDS.finditer(reason)]
        if named and not any(_matches(n, {"id": target, "name": "", "label": target}) or
                             _norm(n) in _norm(target) or _norm(target) in _norm(n) for n in named):
            flags.append(Flag("reason_mismatch", f"reason names '{named[0]}', action targets '{target}'"))
    return flags
