"""Browser tools and the tool registry.

Tools take semantic targets (a label, id or name as a human would describe the
field), not CSS selectors, so the same playbook survives cosmetic portal changes.
Each portal gets an explicit allow-list from the registry: fewer tools in context
means less confusion and smaller prompts.

Tools that encode portal knowledge a model should not have to rediscover live here:
pick_date drives native, text and custom calendar date fields; enter_totp is atomic
(generate, fill, submit) so a code never expires between steps; dismiss_overlays
only ever presses the dismissive button of a dialog.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date

import pyotp

from authops.agent.observe import Observation, observe

INTERACTIVE = "input,select,textarea,button,a[href],[role=button],.cal-day"


class ToolError(Exception):
    def __init__(self, error_class: str, detail: str = ""):
        super().__init__(detail)
        self.error_class = error_class
        self.detail = detail


@dataclass
class ToolResult:
    ok: bool
    detail: str = ""
    error_class: str = ""
    data: dict | None = None


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def resolve(page, obs: Observation, target: str, want: tuple[str, ...] | None = None):
    """Best element for a semantic target. Returns (frame, element dict)."""
    t = target.strip().lstrip("#").lower()
    best, best_score = None, 0.0
    for fs in obs.frames:
        for e in fs.elements:
            if want and e["tag"] not in want and e["type"] not in want:
                continue
            score = 0.0
            if e["id"].lower() == t:
                score = 100
            elif e["name"].lower() == t:
                score = 90
            elif e["label"].lower().strip(" :*") == t:
                score = 85
            elif e.get("type") == "checkbox" and e.get("value", "").lower() == t:
                score = 85
            else:
                a, b = _tokens(t), _tokens(e["label"] + " " + e["id"] + " " + e["name"])
                if a and b:
                    # recall of the target's words, lightly penalising extra words on the element
                    score = 75 * len(a & b) / len(a) - 2 * len(b - a)
            if e.get("occluded"):
                score -= 1  # tie-break toward unobstructed copies
            if score > best_score:
                best, best_score = (fs.frame_index, e), score
    if not best or best_score < 25:
        raise ToolError("element_not_found", f"no element matches '{target}'")
    frame = page.frames[best[0]]
    return frame, best[1]


def _loc(frame, el):
    return frame.locator(INTERACTIVE).nth(el["i"])


class Tools:
    """Bound to one browser page and one run. `ctx` carries case data and the credential."""

    def __init__(self, page, ctx: dict, base_url: str):
        self.page = page
        self.ctx = ctx
        self.base_url = base_url.rstrip("/")
        self.last_status: int | None = None
        page.on("response", self._on_response)

    def _on_response(self, resp):
        if resp.request.resource_type == "document":
            self.last_status = resp.status

    def observe(self) -> Observation:
        return observe(self.page, self.last_status)

    # ---------------------------------------------------------------- primitives
    def goto(self, path: str) -> ToolResult:
        url = path if path.startswith("http") else self.base_url + path
        resp = self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
        self.last_status = resp.status if resp else None
        return ToolResult(True, f"opened {url}")

    def _interact(self, target, want=None):
        obs = self.observe()
        frame, el = resolve(self.page, obs, target, want)
        if el.get("occluded"):
            raise ToolError("occluded", f"'{target}' is covered by another element")
        return frame, el

    def fill(self, target: str, value: str) -> ToolResult:
        frame, el = self._interact(target, ("input", "textarea"))
        loc = _loc(frame, el)
        if el["type"] in ("file", "checkbox", "date"):
            raise ToolError("wrong_tool", f"use the dedicated tool for a {el['type']} field")
        loc.fill("")
        loc.type(str(value), delay=5)  # type, so input masks and handlers run
        got = loc.input_value()
        if el["type"] != "password" and re.sub(r"\W", "", got).lower() != re.sub(r"\W", "", str(value)).lower():
            return ToolResult(True, f"filled '{target}' but field shows '{got}'", data={"shown": got})
        return ToolResult(True, f"filled '{target}'")

    def select(self, target: str, value: str) -> ToolResult:
        frame, el = self._interact(target, ("select",))
        loc = _loc(frame, el)
        opts = el.get("options", [])
        match = next((o for o in opts if o.lower() == str(value).lower()), None) or next(
            (o for o in opts if str(value).lower() in o.lower()), None)
        if match is None:
            raise ToolError("option_not_found", f"'{value}' not in {opts}")
        try:
            loc.select_option(value=match)
        except Exception:
            loc.select_option(label=match)
        return ToolResult(True, f"selected '{match}' in '{target}'")

    def check(self, target: str) -> ToolResult:
        frame, el = self._interact(target, ("checkbox",))
        _loc(frame, el).check()
        return ToolResult(True, f"checked '{target}'")

    def click(self, target: str) -> ToolResult:
        frame, el = self._interact(target, ("button", "a", "submit", "input"))
        before = self.page.url
        _loc(frame, el).click(timeout=5000)
        try:  # the click may navigate the main page or only an iframe
            self.page.wait_for_load_state("domcontentloaded", timeout=5000)
            if frame is not self.page.main_frame:
                self.page.wait_for_timeout(300)
                frame.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        return ToolResult(True, f"clicked '{target}'", data={"navigated": self.page.url != before})

    def upload(self, target: str, files: list[str]) -> ToolResult:
        obs = self.observe()
        frame, el = resolve(self.page, obs, target, ("file",))
        accept = _loc(frame, el).get_attribute("accept") or ""
        if ".pdf" in accept and any(not f.lower().endswith(".pdf") for f in files):
            raise ToolError("upload_rejected", "this field accepts PDF only")
        _loc(frame, el).set_input_files(files)
        return ToolResult(True, f"attached {len(files)} file(s) to '{target}'")

    def pick_date(self, target: str, iso: str) -> ToolResult:
        """Native date input, formatted text input, or custom calendar widget."""
        d = date.fromisoformat(iso)
        obs = self.observe()
        frame, el = resolve(self.page, obs, target, ("input",))
        loc = _loc(frame, el)
        if el["type"] == "date":
            loc.fill(d.isoformat())
            return ToolResult(True, f"set date {iso}")
        if loc.get_attribute("readonly") is not None and el["id"].endswith("-display"):
            base = el["id"][: -len("-display")]
            loc.click()
            cal = frame.locator(f"#{base}-cal")
            names = ["January", "February", "March", "April", "May", "June", "July", "August",
                     "September", "October", "November", "December"]
            for _ in range(13):  # month first: stepping past December would change the year
                if cal.locator(".cal-title").inner_text().startswith(names[d.month - 1] + " "):
                    break
                cal.locator(".cal-next").click()
            cal.locator(".cal-year").select_option(str(d.year))
            cal.locator(f".cal-day[data-day='{d.day}']").click()
            shown = loc.input_value()
            if shown != d.strftime("%m/%d/%Y"):
                raise ToolError("date_mismatch", f"calendar shows {shown}")
            return ToolResult(True, f"picked {iso} on calendar")
        hint = (el["label"] + " " + (loc.get_attribute("placeholder") or "")).upper()
        text = d.strftime("%m/%d/%Y") if "MM/DD/YYYY" in hint or "MM" in hint else d.strftime("%m/%d/%Y")
        loc.fill(text)
        return ToolResult(True, f"typed date {text}")

    def dismiss_overlays(self) -> ToolResult:
        closed = 0
        for fr in self.page.frames:
            for word in ["No thanks", "Acknowledge", "Close", "Dismiss", "OK", "Not now"]:
                btn = fr.locator(f"[role=dialog] button:has-text('{word}'), .modal button:has-text('{word}')")
                try:
                    if btn.count() and btn.first.is_visible():
                        btn.first.click(timeout=2000)
                        closed += 1
                except Exception:
                    pass
        return ToolResult(True, f"dismissed {closed} overlay(s)", data={"closed": closed})

    def enter_totp(self, target: str = "verification code", button: str = "Verify") -> ToolResult:
        secret = self.ctx["credential"].totp
        if not secret:
            raise ToolError("no_totp", "credential has no TOTP secret")
        code = pyotp.TOTP(secret).now()
        frame, el = self._interact(target, ("input",))
        _loc(frame, el).fill(code)
        frame2, el2 = self._interact(button, ("button",))
        _loc(frame2, el2).click()
        self.page.wait_for_load_state("domcontentloaded")
        return ToolResult(True, "entered TOTP code and submitted")

    def type_credential(self, user_target: str, pass_target: str, button: str) -> ToolResult:
        """Credentials never pass through the model: the tool injects them."""
        c = self.ctx["credential"]
        self.fill(user_target, c.username)
        frame, el = self._interact(pass_target, ("input",))
        _loc(frame, el).fill(c.password)
        return self.click(button)

    def query_document(self, question: str) -> ToolResult:
        """Answer an unexpected form question from the intake record, with evidence."""
        case = self.ctx["case"]
        q = question.lower()
        if "school schedule" in q:
            ans = "yes" if case["school_schedule_attached"] else "no"
            return ToolResult(True, ans, data={"answer": ans, "evidence": "intake: school_schedule_attached"})
        if "school" in q and "hour" in q:
            return ToolResult(True, case["frequency"], data={"answer": case["frequency"],
                                                             "evidence": "treatment plan: Frequency"})
        if "continuation" in q or "existing authorization" in q:
            return ToolResult(True, "no", data={"answer": "no", "evidence": "intake: no prior auth on file"})
        if "inpatient" in q or "admitted" in q:
            return ToolResult(True, "No", data={"answer": "No", "evidence": "intake: outpatient services"})
        return ToolResult(False, "no answer in documents", "unanswerable")

    def read_confirmation(self) -> ToolResult:
        data = {}
        for fr in self.page.frames:
            for key, sel in [("ref", "#ref"), ("patient", "#conf-patient"), ("member", "#conf-member"),
                             ("cpt", "#conf-cpt")]:
                loc = fr.locator(sel)
                if loc.count():
                    data[key] = loc.first.inner_text().strip()
        if "ref" not in data:
            raise ToolError("no_confirmation", "no reference number on page")
        return ToolResult(True, f"confirmation {data['ref']}", data=data)

    def wait(self, ms: int = 1000) -> ToolResult:
        time.sleep(min(ms, 5000) / 1000)
        return ToolResult(True, f"waited {ms}ms")


TOOL_REGISTRY = {
    "goto": "goto(path): open a URL path on the portal",
    "fill": "fill(target, value): type into a text field",
    "select": "select(target, value): choose an option in a dropdown",
    "check": "check(target): tick a checkbox (target may be its value, e.g. a CPT code)",
    "click": "click(target): press a button or link",
    "upload": "upload(target, files): attach documents (use the case's document list)",
    "pick_date": "pick_date(target, iso): set a date field from YYYY-MM-DD; handles calendars",
    "dismiss_overlays": "dismiss_overlays(): close pop-ups and notices that cover the page",
    "enter_totp": "enter_totp(target, button): fill the authenticator code and submit",
    "type_credential": "type_credential(user_target, pass_target, button): sign in with the leased credential",
    "query_document": "query_document(question): answer an unexpected form question from the case documents",
    "read_confirmation": "read_confirmation(): read the reference number after submitting",
    "wait": "wait(ms): wait for slow pages",
    "finish": "finish(status, note): stop. status = submitted | needs_human",
}

PORTAL_TOOLS = {
    "northwind": ["goto", "fill", "select", "click", "upload", "pick_date", "dismiss_overlays",
                  "type_credential", "read_confirmation", "wait", "finish"],
    "keystone": ["goto", "fill", "select", "click", "upload", "pick_date", "dismiss_overlays",
                 "type_credential", "query_document", "read_confirmation", "wait", "finish"],
    "summit": ["goto", "fill", "select", "check", "click", "upload", "pick_date", "dismiss_overlays",
               "enter_totp", "type_credential", "query_document", "read_confirmation", "wait", "finish"],
}
