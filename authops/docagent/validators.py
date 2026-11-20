"""Four ways to validate a long chart against payor rules.

offline_oneshot  - one regex pass over the text, first match wins, inside a real-time context
                   budget. Deterministic stand-in for a single fast call.
offline_agent    - finds each document by type, then checks rules on the right pages.
                   Deterministic stand-in for a tool-using agent.
claude_oneshot   - one Claude call over the whole chart (what real-time validation can afford).
claude_agent     - multi-turn Claude loop with search / read / record tools, run in the background.

Every verdict must cite a page and a quote. A quote that is not on the cited page is not
trusted: the verdict becomes needs_human. That is the same guard the extractor uses.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime

from authops.docagent.longdoc import RULES, LongChart

DATE = r"(\d{2}/\d{2}/\d{4})"


def _d(s: str) -> date:
    return datetime.strptime(s, "%m/%d/%Y").date()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


@dataclass
class Finding:
    rule: str
    verdict: str  # pass | fail | needs_human
    pages: list[int] = field(default_factory=list)
    quote: str = ""
    reason: str = ""


@dataclass
class ChartResult:
    chart_id: str
    arm: str
    findings: dict[str, Finding]
    seconds: float
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    turns: int = 0


def grounded(chart: LongChart, f: Finding) -> Finding:
    """Downgrade a verdict whose quote is not on any cited page."""
    if f.verdict == "needs_human":
        return f
    q = _norm(f.quote)
    if len(q) < 4 or not f.pages:
        return Finding(f.rule, "needs_human", f.pages, f.quote, "no usable evidence: " + f.reason)
    for p in f.pages:
        if 1 <= p <= chart.n_pages and q[:120] in _norm(chart.pages[p - 1]):
            return f
    return Finding(f.rule, "needs_human", f.pages, f.quote, "quote not found on cited page: " + f.reason)


# ---------------------------------------------------------------- deterministic checks

def _check_plan_and_friends(req: date, specialty: str, cover: str, plan: str, evaluation: str, assess: str,
                            hep: str | None) -> dict[str, tuple[str, str]]:
    """Return rule -> (verdict, quote) from the four deciding pages."""
    out: dict[str, tuple[str, str]] = {}
    m = re.search(r"Date signed: " + DATE, plan)
    sig_ok = bool(m and re.search(r"Signature: /s/", plan) and 0 <= (req - _d(m.group(1))).days <= 30)
    out["R1_signature"] = ("pass" if sig_ok else "fail", m.group(0) if m else "Signature: ____")
    pdx = re.search(r"Diagnosis \(ICD-10\): (\S+)", plan)
    edx = re.search(r"Diagnosis: (\S+)", evaluation)
    out["R2_dx_consistent"] = ("pass" if pdx and edx and pdx.group(1) == edx.group(1) else "fail",
                               pdx.group(0) if pdx else "")
    cu = re.search(r"Units requested: (\d+)", cover)
    pu = re.search(r"Requested: (\d+)", plan)
    out["R3_units_consistent"] = ("pass" if cu and pu and cu.group(1) == pu.group(1) else "fail",
                                  pu.group(0) if pu else "")
    ad = re.search(r"Date administered: " + DATE, assess)
    out["R4_assessment_current"] = ("pass" if ad and 0 <= (req - _d(ad.group(1))).days <= 180 else "fail",
                                    ad.group(0) if ad else "")
    goals = re.findall(r"Goal \d+: .*", plan)
    clinical = [g for g in goals if "Caregiver training" not in g]
    measurable = all("Baseline:" in g and "Target:" in g for g in goals)
    out["R5_measurable_goals"] = ("pass" if len(clinical) >= 3 and measurable else "fail",
                                  goals[-1] if goals else "")
    if specialty == "aba":
        cg = re.search(r"Goal \d+: Caregiver training.*", plan)
        out["R6_specialty_requirement"] = ("pass" if cg else "fail", cg.group(0) if cg else goals[-1] if goals else "")
    else:
        wk = re.search(r"continued for (\d+) weeks", hep or "")
        out["R6_specialty_requirement"] = ("pass" if wk and int(wk.group(1)) >= 4 else "fail",
                                           wk.group(0) if wk else "")
    cm = re.search(r"Member ID: (\S+)", cover)
    pm = re.search(r"Member ID: (\S+)", plan)
    out["R7_member_id_consistent"] = ("pass" if cm and pm and cm.group(1) == pm.group(1) else "fail",
                                      pm.group(0) if pm else "")
    nec = re.search(r"Medical necessity: .*", plan)
    findings = re.search(r"Findings: (.*)\.", evaluation)
    linked = False
    if nec and findings and pu:
        defs = [x.strip() for x in findings.group(1).split(";")]
        linked = sum(d in nec.group(0) for d in defs) >= 1 and pu.group(1) in nec.group(0)
    out["R8_medical_necessity"] = ("pass" if linked else "fail", nec.group(0) if nec else "")
    return out


def _page_of(chart: LongChart, header: str, exclude: str | None = None) -> int | None:
    for i, p in enumerate(chart.pages):
        if p.startswith(header) and not (exclude and exclude in p.split("\n")[0]):
            return i + 1
    return None


def offline_agent(chart: LongChart) -> ChartResult:
    t0 = time.perf_counter()
    pp = {k: _page_of(chart, h, ex) for k, h, ex in [
        ("plan", "TREATMENT PLAN", None), ("eval", "DIAGNOSTIC EVALUATION", None),
        ("assess", "STANDARDIZED ASSESSMENT", "prior episode"), ("hep", "CONSERVATIVE CARE HISTORY", None)]}
    get = lambda k: chart.pages[pp[k] - 1] if pp[k] else ""  # noqa: E731
    res = _check_plan_and_friends(chart.request_date, chart.specialty, chart.pages[0], get("plan"), get("eval"),
                                  get("assess"), get("hep") or None)
    where = {"R1_signature": ["plan"], "R2_dx_consistent": ["plan", "eval"], "R3_units_consistent": ["plan"],
             "R4_assessment_current": ["assess"], "R5_measurable_goals": ["plan"],
             "R6_specialty_requirement": ["plan" if chart.specialty == "aba" else "hep"],
             "R7_member_id_consistent": ["plan"], "R8_medical_necessity": ["plan"]}
    findings = {}
    for r, (v, q) in res.items():
        pages = [pp[k] for k in where[r] if pp[k]] + ([1] if r in ("R3_units_consistent", "R7_member_id_consistent") else [])
        findings[r] = grounded(chart, Finding(r, v, pages, q))
    return ChartResult(chart.chart_id, "offline_agent", findings, time.perf_counter() - t0)


def offline_oneshot(chart: LongChart, budget_chars: int = 24_000) -> ChartResult:
    """First match wins inside a fixed context budget (head + tail of the chart)."""
    t0 = time.perf_counter()
    text = chart.text()
    if len(text) > budget_chars:
        text = text[: budget_chars * 3 // 4] + "\n" + text[-budget_chars // 4:]

    def first_block(header: str) -> str:
        m = re.search(r"=== Page \d+ ===\n(" + re.escape(header) + r".*?)(?==== Page|\Z)", text, re.S)
        return m.group(1) if m else ""

    # a single pass grabs the first signature / assessment block it sees, including distractors
    plan = first_block("TREATMENT PLAN")
    sig_any = re.search(r"Signature: [^\n]*\nDate signed: [^\n]*", text)
    if plan and sig_any:
        plan = re.sub(r"Signature: [^\n]*\nDate signed: [^\n]*", sig_any.group(0), plan)
    res = _check_plan_and_friends(chart.request_date, chart.specialty, chart.pages[0], plan,
                                  first_block("DIAGNOSTIC EVALUATION"), first_block("STANDARDIZED ASSESSMENT"),
                                  first_block("CONSERVATIVE CARE HISTORY") or None)
    findings = {}
    for r, (v, q) in res.items():
        if not plan and r not in ("R4_assessment_current",):
            findings[r] = Finding(r, "needs_human", [], "", "plan not inside the context budget")
            continue
        pages = [i + 1 for i, p in enumerate(chart.pages) if q and _norm(q)[:120] in _norm(p)][:1]
        findings[r] = grounded(chart, Finding(r, v, pages, q))
    return ChartResult(chart.chart_id, "offline_oneshot", findings, time.perf_counter() - t0)


# ---------------------------------------------------------------- Claude arms

RULE_TEXT = "\n".join(f"- {k}: {v}" for k, v in RULES.items())
SYSTEM = ("You validate prior-authorization charts against payor rules. Decide each rule as pass or fail. "
          "Cite the page number(s) and copy an exact quote (5 to 25 words) from the page that decides it. "
          "Beware of distractors: consent forms, prior-episode assessments, ruled-out diagnoses and early "
          "discussions are not the treatment plan. If you cannot find the deciding evidence, use needs_human.")


def _parse_findings(chart: LongChart, items) -> dict[str, Finding]:
    out = {}
    for it in items or []:
        r = str(it.get("rule", ""))
        if r in RULES:
            pages = it.get("pages") or ([it["page"]] if it.get("page") else [])
            v = str(it.get("verdict", "needs_human")).lower()
            v = v if v in ("pass", "fail", "needs_human") else "needs_human"
            out[r] = grounded(chart, Finding(r, v, [int(p) for p in pages if str(p).isdigit()],
                                             str(it.get("quote", "")), str(it.get("reason", ""))[:300]))
    for r in RULES:
        out.setdefault(r, Finding(r, "needs_human", [], "", "no answer"))
    return out


def claude_oneshot(chart: LongChart, llm) -> ChartResult:
    from authops.llm import parse_json
    t0 = time.perf_counter()
    prompt = (f"Specialty: {chart.specialty}. Request date: {chart.request_date:%m/%d/%Y}.\nRules:\n{RULE_TEXT}\n\n"
              f"CHART ({chart.n_pages} pages):\n{chart.text()}\n\nReturn only a JSON array with one object per rule: "
              '{"rule": id, "verdict": "pass|fail|needs_human", "pages": [n], "quote": "...", "reason": "..."}')
    before = (llm.meter.tokens_in, llm.meter.tokens_out, llm.meter.cost_usd)
    r = llm.complete(prompt, system=SYSTEM, max_tokens=2500)
    findings = _parse_findings(chart, parse_json(r.text))
    return ChartResult(chart.chart_id, "claude_oneshot", findings, time.perf_counter() - t0,
                       llm.meter.tokens_in - before[0], llm.meter.tokens_out - before[1],
                       llm.meter.cost_usd - before[2], 1)


TOOLS = [
    {"name": "search_chart", "description": "Keyword search. Returns up to 8 pages with the first line and a snippet.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "read_pages", "description": "Read the full text of up to 3 pages.",
     "input_schema": {"type": "object", "properties": {"pages": {"type": "array", "items": {"type": "integer"}}},
                      "required": ["pages"]}},
    {"name": "record_finding", "description": "Record the verdict for one rule with page(s) and an exact quote.",
     "input_schema": {"type": "object", "properties": {
         "rule": {"type": "string"}, "verdict": {"type": "string", "enum": ["pass", "fail", "needs_human"]},
         "pages": {"type": "array", "items": {"type": "integer"}}, "quote": {"type": "string"},
         "reason": {"type": "string"}}, "required": ["rule", "verdict", "pages", "quote"]}},
    {"name": "finish", "description": "Call when every rule has a recorded finding.",
     "input_schema": {"type": "object", "properties": {}}},
]


def _search(chart: LongChart, q: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9\-\.]+", q.lower()) if len(w) > 2]
    scored = []
    for i, p in enumerate(chart.pages):
        low = p.lower()
        s = sum(low.count(w) for w in words) + (5 if words and all(w in low for w in words) else 0)
        if s:
            scored.append((s, i + 1, p))
    scored.sort(key=lambda x: -x[0])
    lines = []
    for s, n, p in scored[:8]:
        first = p.split("\n")[0][:80]
        hit = next((ln for ln in p.split("\n") if any(w in ln.lower() for w in words)), "")[:140]
        lines.append(f"page {n}: [{first}] ... {hit}")
    return "\n".join(lines) or "no matches"


def claude_agent(chart: LongChart, llm, max_turns: int = 30) -> ChartResult:
    t0 = time.perf_counter()
    client, model = llm.client, llm.model
    recorded: list[dict] = []
    tin = tout = 0
    msgs = [{"role": "user", "content": (
        f"Specialty: {chart.specialty}. Request date: {chart.request_date:%m/%d/%Y}. The chart has "
        f"{chart.n_pages} pages; page 1 is the request cover page.\nRules:\n{RULE_TEXT}\n\n"
        "Use search_chart to locate documents, read_pages to read them, then record_finding once per rule. "
        "Call finish when all 8 rules are recorded.")}]
    turns = 0
    for turns in range(1, max_turns + 1):
        from authops.llm import create_message
        resp = create_message(client, model=model, max_tokens=1200, temperature=0.0, system=SYSTEM,
                                      tools=TOOLS, messages=msgs)
        tin += resp.usage.input_tokens
        tout += resp.usage.output_tokens
        msgs.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if not uses:
            break
        results, done = [], False
        for u in uses:
            a = u.input or {}
            if u.name == "search_chart":
                out = _search(chart, str(a.get("query", "")))
            elif u.name == "read_pages":
                ps = [int(p) for p in (a.get("pages") or [])][:3]
                out = "\n\n".join(f"=== Page {p} ===\n{chart.pages[p - 1]}" for p in ps if 1 <= p <= chart.n_pages)
            elif u.name == "record_finding":
                recorded.append(a)
                out = "recorded"
            else:
                done, out = True, "ok"
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": out or "empty"})
        msgs.append({"role": "user", "content": results})
        if done:
            break
    from authops.llm import PRICE_PER_MTOK
    pin, pout = PRICE_PER_MTOK.get(model, (3.0, 15.0))
    llm.meter.calls += turns
    llm.meter.tokens_in += tin
    llm.meter.tokens_out += tout
    cost = (tin * pin + tout * pout) / 1e6
    llm.meter.cost_usd += cost
    latest = {}
    for a in recorded:  # last finding per rule wins
        latest[a.get("rule")] = a
    return ChartResult(chart.chart_id, "claude_agent", _parse_findings(chart, list(latest.values())),
                       time.perf_counter() - t0, tin, tout, cost, turns)
