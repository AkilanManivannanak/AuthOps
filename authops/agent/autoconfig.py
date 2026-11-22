"""Draft a portal playbook automatically, by walking the portal's sandbox once.

Silna's AI Operations team estimated that covering the long tail of payor portals by hand
would take over 5,000 hours of configuration, and named automating that configuration
layer as their next phase. This module is a small version of that idea:

1. Walk the portal once in the sandbox with a test patient (sign in, navigate, fill, submit),
   reading each page's HTML: labels, input types, options, buttons, links.
2. Map every field label to a request variable (member ID, DOB, CPT, ...) with either a
   lexicon scorer (offline) or Claude (labels only; no credentials or patient data in the
   prompt).
3. Pick the forward button and ignore decoys ("Save draft", "Cancel", "Back").
4. Emit a playbook in the same YAML format as the hand-written ones, plus a report of what
   was mapped, what was not, and where the walk stopped.

The output is a draft for a person to review, not an auto-deploy. The evaluation compares
drafts to the hand-written playbooks and runs the draft for the held-out Lakeshore portal
end to end.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

VARIABLES = {
    "member_id": "insurance member / subscriber / Medicaid ID",
    "dob": "patient date of birth",
    "last_name": "patient last name",
    "specialty": "service type / program / specialty (a dropdown)",
    "cpt_csv": "procedure codes (CPT/HCPCS), comma separated",
    "icd_csv": "diagnosis codes (ICD-10), comma separated",
    "units": "units / visits / quantity requested",
    "start": "service start date",
    "end": "service end date",
    "npi": "rendering or treating provider NPI",
    "files": "clinical documents to upload (a file input)",
}
DATE_VARS = {"dob", "start", "end"}
LEXICON = {
    "member_id": ["member id", "subscriber", "medicaid id", "member number", "insurance id", "policy number", "beneficiary"],
    "dob": ["date of birth", "birthdate", "birth date", "dob"],
    "last_name": ["last name", "surname", "family name"],
    "specialty": ["service type", "program", "specialty", "service category", "type of service", "service line"],
    "cpt_csv": ["cpt", "procedure", "hcpcs", "service code"],
    "icd_csv": ["diagnos", "icd", "dx"],
    "units": ["units", "quantity", "qty", "number of visits", "visits requested"],
    "start": ["start date", "service from", "from date", "begin", "effective date", "start of service"],
    "end": ["end date", "service through", "through date", "thru", "to date", "end of service"],
    "npi": ["npi"],
    "files": ["document", "attachment", "upload", "documentation", "records"],
}
SPECIALTY_WORDS = {"aba": ["aba", "behavior analysis", "autism"],
                   "physical_therapy": ["physical", "pt ", "pt/", "rehab", "therapy services"],
                   "behavioral_health": ["behavioral", "mental", "counsel", "psych"]}
DECOY = re.compile(r"(?i)\b(draft|cancel|back|reset|clear|save for later|print|log ?out|sign ?out)\b")
FORWARD = re.compile(r"(?i)\b(submit|send|next|continue|find|search|look ?up|log ?in|sign ?in|verify|proceed)\b")
NAV_GOAL = ["new prior authorization", "new request", "start", "prior auth", "utilization review", "authorization request",
            "submit a request", "new"]
ATTEST = re.compile(r"(?i)attest|certify|confirm that|accurate and complete|i agree")


# ------------------------------------------------------------------ HTML reading

@dataclass
class Field:
    kind: str            # text | password | date | number | select | file | checkbox | hidden
    name: str
    id: str
    label: str = ""
    placeholder: str = ""
    options: list[tuple[str, str]] = field(default_factory=list)  # (value, text)


@dataclass
class PageForm:
    url: str
    title: str = ""
    heading: str = ""
    action: str = ""
    method: str = "get"
    fields: list[Field] = field(default_factory=list)
    buttons: list[tuple[str, str, str]] = field(default_factory=list)  # (text, name, value)
    links: list[tuple[str, str]] = field(default_factory=list)        # (text, href)
    iframes: list[str] = field(default_factory=list)
    text: str = ""


class _Reader(HTMLParser):
    def __init__(self, url: str):
        super().__init__(convert_charrefs=True)
        self.p = PageForm(url)
        self.labels_for: dict[str, str] = {}
        self._label_stack: list[dict] = []
        self._cur_select: Field | None = None
        self._cur_option: list | None = None
        self._cur_button: list | None = None
        self._cur_link: list | None = None
        self._cap: str | None = None
        self._texts: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and not self.p.action:
            self.p.action, self.p.method = a.get("action", ""), (a.get("method") or "get").lower()
        elif tag == "label":
            self._label_stack.append({"for": a.get("for"), "text": [], "inputs": []})
        elif tag == "input":
            t = (a.get("type") or "text").lower()
            kind = {"password": "password", "date": "date", "number": "number", "file": "file",
                    "checkbox": "checkbox", "hidden": "hidden", "submit": "submit"}.get(t, "text")
            if kind == "submit":
                self.p.buttons.append((a.get("value", "Submit"), a.get("name", ""), a.get("value", "")))
                return
            f = Field(kind, a.get("name", ""), a.get("id", ""), placeholder=a.get("placeholder", ""))
            self.p.fields.append(f)
            if self._label_stack:
                self._label_stack[-1]["inputs"].append(f)
        elif tag == "select":
            self._cur_select = Field("select", a.get("name", ""), a.get("id", ""))
            self.p.fields.append(self._cur_select)
        elif tag == "option" and self._cur_select is not None:
            self._cur_option = [a.get("value", ""), ""]
        elif tag == "button":
            self._cur_button = ["", a.get("name", ""), a.get("value", "")]
            m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)", a.get("onclick", "") or "")
            if m:   # a button that only navigates is a link
                self._cur_button.append(m.group(1))
        elif tag == "a":
            self._cur_link = ["", a.get("href", "")]
        elif tag == "iframe" and a.get("src"):
            self.p.iframes.append(a["src"])
        elif tag in ("title", "h1", "h2"):
            self._cap = tag

    def handle_endtag(self, tag):
        if tag == "label" and self._label_stack:
            lab = self._label_stack.pop()
            text = " ".join("".join(lab["text"]).split())
            if lab["for"]:
                self.labels_for[lab["for"]] = text
            for f in lab["inputs"]:
                f.label = text
        elif tag == "select":
            self._cur_select = None
        elif tag == "option" and self._cur_option is not None and self._cur_select is not None:
            self._cur_select.options.append((self._cur_option[0], " ".join(self._cur_option[1].split())))
            self._cur_option = None
        elif tag == "button" and self._cur_button is not None:
            text = " ".join(self._cur_button[0].split())
            if len(self._cur_button) > 3:
                self.p.links.append((text, self._cur_button[3]))
            else:
                self.p.buttons.append((text, self._cur_button[1], self._cur_button[2]))
            self._cur_button = None
        elif tag == "a" and self._cur_link is not None:
            self.p.links.append((" ".join(self._cur_link[0].split()), self._cur_link[1]))
            self._cur_link = None
        elif tag == self._cap:
            self._cap = None

    def handle_data(self, data):
        self._texts.append(data)
        if self._label_stack:
            self._label_stack[-1]["text"].append(data)
        if self._cur_option is not None:
            self._cur_option[1] += data
        if self._cur_button is not None:
            self._cur_button[0] += data
        if self._cur_link is not None:
            self._cur_link[0] += data
        if self._cap == "title":
            self.p.title += data
        elif self._cap in ("h1", "h2") and not self.p.heading:
            self.p.heading = data.strip()

    def result(self) -> PageForm:
        for f in self.p.fields:
            if not f.label and f.id in self.labels_for:
                f.label = self.labels_for[f.id]
        self.p.text = " ".join(" ".join(self._texts).split())
        return self.p


def read_page(html: str, url: str) -> PageForm:
    r = _Reader(url)
    r.feed(html)
    return r.result()


# ------------------------------------------------------------------ label -> variable

def lexicon_map(fields: list[Field]) -> dict[str, str | None]:
    """Score each label against the lexicon; each variable is used at most once per page."""
    out: dict[str, str | None] = {}
    scored = []
    for f in fields:
        if f.kind in ("hidden", "password", "checkbox"):
            continue
        lab = " " + (f.label + " " + f.placeholder).lower() + " "
        for var, words in LEXICON.items():
            s = sum(3 if " " in w.strip() else 2 for w in words if w in lab)
            if var == "files" and f.kind == "file":
                s += 5
            if var == "specialty" and f.kind == "select":
                s += 2
            if var in DATE_VARS and f.kind in ("date",) or (var in DATE_VARS and "mm/dd" in lab):
                s += 1
            if var not in DATE_VARS and f.kind == "date":
                s -= 3
            if s > 0:
                scored.append((s, f.label or f.name, var))
    used_labels, used_vars = set(), set()
    for s, lab, var in sorted(scored, key=lambda x: -x[0]):
        if lab in used_labels or var in used_vars:
            continue
        out[lab] = var
        used_labels.add(lab)
        used_vars.add(var)
    for f in fields:
        if f.kind not in ("hidden", "password", "checkbox"):
            out.setdefault(f.label or f.name, None)
    return out


def claude_map(fields: list[Field], llm) -> dict[str, str | None]:
    from authops.llm import parse_json
    items = [{"label": f.label or f.name, "type": f.kind, "placeholder": f.placeholder,
              "options": [t for _, t in f.options][:8]} for f in fields
             if f.kind not in ("hidden", "password", "checkbox")]
    prompt = ("Map each form field on a payor prior-authorization portal to one request variable, or null if "
              "none fits. Variables:\n" + "\n".join(f"- {k}: {v}" for k, v in VARIABLES.items()) +
              f"\n\nFields:\n{items}\n\nReturn only JSON: {{\"<label>\": \"<variable or null>\", ...}}")
    r = llm.complete(prompt, max_tokens=600)
    got = parse_json(r.text) or {}
    return {it["label"]: (got.get(it["label"]) if got.get(it["label"]) in VARIABLES else None) for it in items}


def option_for(f: Field, specialty: str) -> tuple[str, str] | None:
    best, score = None, 0
    for val, text in f.options:
        if not val:
            continue
        t = " " + text.lower() + " " + val.lower() + " "
        s = sum(w in t for w in SPECIALTY_WORDS[specialty]) + (2 if specialty.replace("_", " ") in t else 0)
        if s > score:
            best, score = (val, text), s
    return best


def date_format(f: Field) -> str:
    lab = (f.label + " " + f.placeholder).upper()
    return "iso" if f.kind == "date" or "YYYY-MM-DD" in lab else "mdy"


def forward_button(p: PageForm) -> tuple[str, str, str] | None:
    cands = [b for b in p.buttons if not DECOY.search(b[0])]
    fw = [b for b in cands if FORWARD.search(b[0])]
    return (fw or cands or [None])[-1]


# ------------------------------------------------------------------ walk the sandbox

@dataclass
class Draft:
    portal: str
    spec: dict
    pages: list[dict]       # per page: url, kind, mapping, unmapped, button
    reached_confirmation: bool
    stopped_reason: str = ""


def _test_value(var: str, values: dict, f: Field) -> str:
    v = values[var]
    if var in DATE_VARS and date_format(f) == "mdy":
        y, m, d = v.split("-")
        return f"{m}/{d}/{y}"
    if var == "member_id" and re.search(r"[A-Z0-9]{3}-", f.placeholder or ""):
        return f"{v[:3]}-{v[3:]}"
    return v


def draft_playbook(client, portal: str, start: str, credential: dict, case: dict, mapper="lexicon", llm=None,
                   max_pages: int = 10, totp=None) -> Draft:
    from authops.agent.policy import case_values
    values = case_values(case, ["plan.pdf"])
    values["files"] = None
    spec = {"portal": portal, "start": start, "generated": True, "pages": []}
    trace: list[dict] = []
    url = start
    resp = client.get(url)
    reached, reason = False, "page limit"
    for _ in range(max_pages):
        html = resp.text
        p = read_page(html, str(resp.url))
        path = urlparse(str(resp.url)).path
        if "Request submitted" in p.text or "Reference Number" in p.text:
            spec["pages"].append({"match": {"text": "Request submitted"},
                                  "actions": [["read_confirmation", {}], ["finish", {"status": "submitted"}]]})
            reached, reason = True, "confirmation"
            break
        err = re.search(r"class='err'[^>]*>([^<]+)", html) or re.search(r'class="err"[^>]*>([^<]+)', html)
        if err and trace and trace[-1]["url"] == path:
            reason = "portal rejected the draft's input: " + err.group(1)
            break
        if p.iframes and not [f for f in p.fields if f.kind != "hidden"]:
            inner = client.get(urljoin(str(resp.url), p.iframes[0]))
            q = read_page(inner.text, str(inner.url))
            q.url = str(resp.url)
            p, html, frame_path = q, inner.text, urlparse(str(inner.url)).path
        else:
            frame_path = path
        pw = [f for f in p.fields if f.kind == "password"]
        visible = [f for f in p.fields if f.kind not in ("hidden",)]
        if pw:   # sign-in page
            user = next(f for f in visible if f.kind == "text")
            btn = forward_button(p)
            spec["pages"].append({"match": {"url": path}, "actions": [["type_credential", {
                "user_target": user.label, "pass_target": pw[0].label, "button": btn[0] if btn else "Sign in"}]]})
            trace.append({"url": path, "kind": "sign-in", "mapping": {}, "unmapped": [], "button": btn and btn[0]})
            data = {user.name: credential["username"], pw[0].name: credential["password"]}
            resp = client.post(urljoin(str(resp.url), p.action or frame_path), data=data)
            continue
        otp = [f for f in visible if re.search(r"(?i)code|one.time|otp|authenticator", f.label + f.placeholder)]
        if otp and len(visible) == 1 and totp:
            btn = forward_button(p)
            spec["pages"].append({"match": {"url": path}, "actions": [["enter_totp", {"target": otp[0].label,
                                                                                      "button": btn[0] if btn else "Verify"}]]})
            trace.append({"url": path, "kind": "one-time code", "mapping": {}, "unmapped": [], "button": btn and btn[0]})
            resp = client.post(urljoin(str(resp.url), p.action or frame_path), data={otp[0].name: totp()})
            continue
        if not visible:   # navigation page: choose the link that starts a new request
            best, score = None, 0
            for text, href in p.links:
                t = text.lower()
                s = max((len(g) for g in NAV_GOAL if g in t), default=0)
                if s > score:
                    best, score = (text, href), s
            if not best:
                reason = f"no way forward from {path}"
                break
            spec["pages"].append({"match": {"url": path}, "actions": [["click", {"target": best[0]}]]})
            trace.append({"url": path, "kind": "navigation", "mapping": {}, "unmapped": [], "button": best[0]})
            resp = client.get(urljoin(str(resp.url), best[1]))
            continue
        # form page
        mapping = claude_map(visible, llm) if mapper == "claude" else lexicon_map(visible)
        actions, data, files = [], {}, []
        by_label = {(f.label or f.name): f for f in visible}
        for lab, var in mapping.items():
            f = by_label.get(lab)
            if not f or not var:
                continue
            if var == "files" or f.kind == "file":
                actions.append(["upload", {"target": lab, "files": "{files}"}])
                files.append((f.name, ("plan.pdf", b"%PDF-1.4 test", "application/pdf")))
            elif var == "specialty" and f.kind == "select":
                conds = []
                for spc in SPECIALTY_WORDS:
                    o = option_for(f, spc)
                    if o:
                        conds.append(["conditional", {"if_specialty": spc, "actions": [["select", {"target": lab, "value": o[0]}]]}])
                actions += conds
                o = option_for(f, case["specialty"])
                data[f.name] = o[0] if o else ""
            elif var in DATE_VARS:
                actions.append(["pick_date", {"target": lab, "iso": "{" + var + "}"}])
                if f.id.endswith("-display"):   # calendar widget: the value lives in a hidden twin input
                    twin = next((h for h in p.fields if h.kind == "hidden" and h.id == f.id[:-8]), None)
                    if twin:
                        data[twin.name] = values[var]
                if f.name:
                    data[f.name] = _test_value(var, values, f)
            else:
                val = "{member_id|mask3}" if var == "member_id" and re.search(r"[A-Z0-9]{3}-", f.placeholder or "") else "{" + var + "}"
                actions.append(["fill", {"target": lab, "value": val}])
                data[f.name] = _test_value(var, values, f)
        for f in visible:
            if f.kind == "checkbox" and ATTEST.search(f.label):
                actions.append(["check", {"target": f.label}])
                data[f.name] = "yes"
        btn = forward_button(p)
        if not btn:
            reason = f"no forward button on {path}"
            break
        is_final = bool(files) or re.search(r"(?i)submit|send", btn[0]) is not None
        actions.append(["click", {"target": btn[0], **({"submit": True} if is_final else {})}])
        if btn[1]:
            data[btn[1]] = btn[2]
        unmapped = [lab for lab, v in mapping.items() if v is None]
        spec["pages"].append({"match": {"url": path}, "actions": actions})
        trace.append({"url": path, "kind": "form", "mapping": mapping, "unmapped": unmapped, "button": btn[0],
                      "fields": sorted((f.label or f.name, f.kind) for f in visible)})
        target = urljoin(str(resp.url), p.action or frame_path)
        resp = client.post(target, data=data, files=files or None)
    spec["expected_steps"] = sum(len(pg["actions"]) for pg in spec["pages"]) + 2
    return Draft(portal, spec, trace, reached, reason)


# ------------------------------------------------------------------ compare with a hand-written playbook

def label_pairs(spec: dict) -> dict[str, str]:
    """target label -> variable, from any playbook (hand-written or drafted)."""
    out = {}

    def walk(actions):
        for tool, args in actions:
            if tool == "conditional":
                walk(args["actions"])
                continue
            if tool == "select" and "{" not in str(args.get("value", "")):
                out[_norm(args["target"])] = "specialty"
                continue
            for k in ("value", "iso", "files"):
                v = str(args.get(k, ""))
                m = re.fullmatch(r"\{(\w+)(?:\|\w+)?\}", v)
                if m:
                    out[_norm(args["target"])] = m.group(1)
    for pg in spec["pages"]:
        walk(pg["actions"])
    return out


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _same(a: str, b: str) -> bool:
    ta, tb = set(re.findall(r"[a-z0-9]+", a)), set(re.findall(r"[a-z0-9]+", b))
    return bool(ta) and (ta <= tb or tb <= ta)


def compare(hand: dict, draft: dict) -> dict:
    h, d0 = label_pairs(hand), label_pairs(draft)
    d = {}
    for hk in h:   # the resolver matches labels loosely, so "CPT Codes" and "CPT Codes (comma separated)" are one field
        dk = next((k for k in d0 if _same(hk, k)), None)
        if dk:
            d[hk] = d0[dk]
    d.update({k: v for k, v in d0.items() if not any(_same(k, hk) for hk in h)})
    right = sum(1 for k, v in h.items() if d.get(k) == v)
    wrong = [(k, h[k], d[k]) for k in h if k in d and d[k] != h[k]]
    missed = [k for k in h if k not in d]
    extra = [k for k in d if k not in h]
    return {"hand_fields": len(h), "matched": right, "wrong": wrong, "missed": missed, "extra": extra,
            "recall": round(right / len(h), 3) if h else None}
