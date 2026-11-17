"""Policies decide the next tool call. The runtime executes it.

PlaybookPolicy  deterministic: follows the portal's structured playbook (YAML), page by
                page. It is the RPA-style baseline, with no model in the loop. It fails
                loudly (needs_human) on anything the playbook does not cover.
ClaudePolicy    an LLM agent: reads the plain-English playbook, the case, a windowed
                history and a compact page snapshot, then returns one JSON tool call.
                Only tools on the portal's allow-list are accepted.

Both go through the same runtime, guards, scoring and experiment routing, so they
can be compared head to head on the same cases.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from authops.agent.observe import Observation
from authops.agent.tools import PORTAL_TOOLS, TOOL_REGISTRY

PLAYBOOK_DIR = Path(__file__).resolve().parents[2] / "playbooks"


def case_values(case: dict, files: list[str]) -> dict:
    return {
        "member_id": case["patient"]["member_id"], "dob": case["patient"]["dob"],
        "last_name": case["patient"]["last_name"], "specialty": case["specialty"],
        "cpt_csv": ", ".join(case["cpt_codes"]), "cpt_list": case["cpt_codes"],
        "icd_csv": ", ".join(case["icd10_codes"]), "units": str(case["requested_units"]),
        "start": case["start_date"], "end": case["end_date"], "npi": case["provider"]["npi"],
        "files": files,
    }


def render(template, values: dict):
    if isinstance(template, list):
        return [render(t, values) for t in template]
    if isinstance(template, dict):
        return {k: render(v, values) for k, v in template.items()}
    if not isinstance(template, str):
        return template
    m = re.fullmatch(r"\{(\w+)(?:\|(\w+))?\}", template)
    if not m:
        return template
    v = values[m.group(1)]
    f = m.group(2)
    if f == "mask3":
        v = f"{v[:3]}-{v[3:]}"
    elif f == "mdy":
        y, mo, d = v.split("-")
        v = f"{mo}/{d}/{y}"
    return v


class PlaybookPolicy:
    name = "playbook"
    model = None

    def __init__(self, portal: str):
        spec = yaml.safe_load((PLAYBOOK_DIR / f"{portal}.yaml").read_text())
        self.portal = portal
        self.start = spec["start"]
        self.expected_steps = spec.get("expected_steps", 20)
        # confirmation pages share URLs with forms, so text matches are checked first
        self.pages = sorted(spec["pages"], key=lambda p: 0 if "text" in p["match"] else 1)
        self.queue: list[dict] = []
        self.visit = None
        self.replays: dict[str, int] = {}

    def reset_page(self) -> None:
        self.visit = None

    def _match(self, obs: Observation):
        for p in self.pages:
            m = p["match"]
            if "text" in m and m["text"].lower() in obs.text.lower():
                return p
            if "url" in m and m["url"] in obs.url and "text" not in m:
                return p
        return None

    def _expand(self, actions, values, case, tools_query):
        out = []
        for tool, args in actions:
            if tool == "conditional":
                if case["specialty"] == args["if_specialty"]:
                    out += self._expand(args["actions"], values, case, tools_query)
            elif tool == "check_each":
                out += [{"tool": "check", "args": {"target": v}} for v in render(args["values"], values)]
            elif tool == "answer":
                out.append({"tool": "answer", "args": args})
            else:
                a = render(dict(args), values)
                submit = a.pop("submit", False)
                out.append({"tool": tool, "args": a, "submit": submit})
        return out

    def next_action(self, obs: Observation, ctx: dict, history: list[dict]) -> dict:
        key = obs.url + "|" + obs.heading + "|" + ("ERR" if obs.errors else "")
        if key != self.visit:
            self.visit = key
            page = self._match(obs)
            if page is None:
                return {"tool": "finish", "args": {"status": "needs_human",
                                                   "note": f"no playbook step for {obs.url}"}}
            self.replays[key] = self.replays.get(key, 0) + 1
            if self.replays[key] > 4:  # must exceed the runtime's 3 transient retries
                return {"tool": "finish", "args": {"status": "needs_human",
                                                   "note": "page repeated: " + "; ".join(obs.errors)[:200]}}
            values = case_values(ctx["case"], ctx["files"])
            self.queue = self._expand(page["actions"], values, ctx["case"], None)
        if not self.queue:
            note = "; ".join(obs.errors) or "playbook exhausted on this page"
            return {"tool": "finish", "args": {"status": "needs_human", "note": note[:200]}}
        return self.queue.pop(0)


SYSTEM = """You operate a payor web portal to submit a prior authorization for a patient.
You act only through tools. Return exactly one JSON object per turn:
{"tool": "<name>", "args": {...}, "reason": "<one short sentence>"}

Rules:
- Use type_credential to sign in. Never type usernames, passwords or codes yourself.
- Use only values from the CASE. Never invent or guess identifiers, dates or codes.
- If a dialog covers the page, call dismiss_overlays first.
- Use pick_date for every date field (it handles calendars and formats) unless the playbook says to type the date.
- If an error says a member is not found or an account is locked, call finish with status needs_human.
- After submitting, call read_confirmation, then finish with status submitted.
- Set "submit": true in the JSON when the click submits the request to the payor."""


class ClaudePolicy:
    def __init__(self, portal: str, llm, history_window: int = 8):
        self.portal = portal
        self.llm = llm
        self.model = llm.model
        self.name = f"claude:{llm.model}"
        self.window = history_window
        self.playbook = (PLAYBOOK_DIR / f"{portal}.md").read_text()
        spec = yaml.safe_load((PLAYBOOK_DIR / f"{portal}.yaml").read_text())
        self.start = spec["start"]
        self.expected_steps = spec.get("expected_steps", 20)
        self.allowed = PORTAL_TOOLS[portal]

    def next_action(self, obs: Observation, ctx: dict, history: list[dict]) -> dict:
        vals = case_values(ctx["case"], ctx["files"])
        tools = "\n".join(f"- {TOOL_REGISTRY[t]}" for t in self.allowed)
        old = len(history) - self.window
        hist = (f"({old} earlier steps omitted)\n" if old > 0 else "") + "\n".join(
            f"{h['tool']}({json.dumps(h['args'])[:120]}) -> {'ok' if h['ok'] else 'FAILED ' + h['error_class']}: "
            f"{h['detail'][:100]}" for h in history[-self.window:])
        prompt = (f"PLAYBOOK:\n{self.playbook}\n\nCASE:\n{json.dumps(vals, indent=1)}\n\nTOOLS:\n{tools}\n\n"
                  f"RECENT STEPS:\n{hist or '(none)'}\n\nCURRENT PAGE:\n{obs.for_model()}\n\nNext tool call as JSON:")
        r = self.llm.complete(prompt, system=SYSTEM, max_tokens=300)
        from authops.llm import parse_json

        act = parse_json(r.text) or {}
        act.setdefault("args", {})
        act["_tokens"] = (r.tokens_in, r.tokens_out)
        if act.get("tool") not in self.allowed:
            return {"tool": "invalid", "args": {"raw": r.text[:200]}, "_tokens": act["_tokens"]}
        return act
