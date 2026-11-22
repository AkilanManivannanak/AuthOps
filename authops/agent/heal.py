"""Self-healing playbooks: notice a portal release, re-draft what broke, verify before reuse.

Portals change without notice: labels are renamed, fields move, buttons get new text, new
required questions appear. A hand-written playbook then fails on every submission until someone
notices the failures and edits it.

1. canary(): one sandbox walk per portal per day; each page is fingerprinted (field labels and
   types, forward button) and compared with the fingerprint stored when the playbook was approved.
2. heal(): on a mismatch, re-draft the portal with autoconfig, keep hand-written steps whose
   targets still exist (judgment answers, conditional ABA questions), and replay the candidate in
   the sandbox. Only a candidate that reaches a confirmation is offered, as a patch for review.
3. Anything the drafter cannot map (a new required clinical question) is returned as a
   needs-human item instead of a guess.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from authops.agent.autoconfig import Draft, _norm, _same, draft_playbook, label_pairs

PLAYBOOK_DIR = Path(__file__).resolve().parents[2] / "playbooks"


def fingerprint(d: Draft) -> dict:
    return {pg["url"]: {"fields": [list(x) for x in pg.get("fields", [])], "button": pg.get("button")}
            for pg in d.pages if pg["kind"] == "form"}


@dataclass
class CanaryResult:
    portal: str
    changed: bool
    pages: dict = field(default_factory=dict)   # url -> {"added": [...], "removed": [...], "button": (old, new)}


def canary(stored: dict, d: Draft, portal: str) -> CanaryResult:
    now = fingerprint(d)
    out = {}
    for url in set(stored) | set(now):
        a = {tuple(x) for x in stored.get(url, {}).get("fields", [])}
        b = {tuple(x) for x in now.get(url, {}).get("fields", [])}
        ob, nb = stored.get(url, {}).get("button"), now.get(url, {}).get("button")
        if a != b or ob != nb:
            out[url] = {"added": sorted(b - a), "removed": sorted(a - b), "button": [ob, nb] if ob != nb else None}
    return CanaryResult(portal, bool(out), out)


def _carry_over(old: dict, new: dict, new_labels: set[str]) -> list[str]:
    """Hand-written judgment steps (answer / conditional answer) whose targets still exist."""
    kept = []
    for opg in old["pages"]:
        for act in opg["actions"]:
            tool, args = act
            inner = args.get("actions", []) if tool == "conditional" else [act]
            if not all(t == "answer" for t, _ in inner):
                continue
            if all(any(_same(_norm(a["target"]), lab) for lab in new_labels) for _, a in inner):
                for npg in new["pages"]:
                    if npg["match"].get("url") == opg["match"].get("url"):
                        npg["actions"].insert(max(0, len(npg["actions"]) - 2), act)
                        kept.append(" / ".join(a["target"] for _, a in inner))
    return kept


@dataclass
class HealResult:
    status: str                 # healed | needs_human | no_change
    renamed: list = field(default_factory=list)      # (variable, old label, new label)
    added_unmapped: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    button: list | None = None
    carried_over: list = field(default_factory=list)
    verified_in_sandbox: bool = False
    candidate: dict | None = None
    patch: str = ""
    stopped: str = ""


def heal(old_spec: dict, client, portal: str, start: str, credential: dict, case: dict, totp=None,
         mapper: str = "lexicon", llm=None) -> HealResult:
    d = draft_playbook(client, portal, start, credential, case, mapper=mapper, llm=llm, totp=totp)
    old_pairs, new_pairs = label_pairs(old_spec), label_pairs(d.spec)
    old_by_var = {v: k for k, v in old_pairs.items()}
    new_by_var = {v: k for k, v in new_pairs.items()}
    renamed = sorted((v, old_by_var[v], new_by_var[v]) for v in old_by_var
                     if v in new_by_var and not _same(old_by_var[v], new_by_var[v]))
    removed = sorted(old_by_var[v] for v in old_by_var if v not in new_by_var)
    unmapped = sorted({u for pg in d.pages for u in pg["unmapped"]})
    ob = [a[1]["target"] for pg in old_spec["pages"] for a in pg["actions"] if a[0] == "click" and a[1].get("submit")]
    nb = [a[1]["target"] for pg in d.spec["pages"] for a in pg["actions"] if a[0] == "click" and a[1].get("submit")]
    new_labels = {_norm(x[0]) for pg in d.pages for x in pg.get("fields", [])}
    cand = json.loads(json.dumps(d.spec))
    kept = _carry_over(old_spec, cand, new_labels)
    cand.pop("generated", None)
    cand["healed_from"] = old_spec.get("version", "v1")
    patch = "".join(difflib.unified_diff(yaml.safe_dump(old_spec, sort_keys=False).splitlines(True),
                                         yaml.safe_dump(cand, sort_keys=False).splitlines(True),
                                         f"playbooks/{portal}.yaml (approved)", f"playbooks/{portal}.yaml (candidate)"))
    if not renamed and not removed and ob == nb and not unmapped:
        return HealResult("no_change", verified_in_sandbox=d.reached_confirmation)
    status = "healed" if d.reached_confirmation and not removed else "needs_human"
    return HealResult(status, renamed, unmapped, removed, [ob[0] if ob else None, nb[0] if nb else None] if ob != nb else None,
                      kept, d.reached_confirmation, cand if d.reached_confirmation else None, patch,
                      "" if d.reached_confirmation else d.stopped_reason)


def stored_fingerprint(portal: str) -> dict | None:
    p = PLAYBOOK_DIR / f"{portal}.fingerprint.json"
    return json.loads(p.read_text()) if p.exists() else None


def save_fingerprint(portal: str, d: Draft) -> Path:
    p = PLAYBOOK_DIR / f"{portal}.fingerprint.json"
    p.write_text(json.dumps(fingerprint(d), indent=1))
    return p
