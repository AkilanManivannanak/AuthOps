"""Read a real document a person brings: a payor letter or a treatment plan.

Two layers, and the output says which one produced each line:
- rules: OCR plus deterministic checks that never guess (NPI checksum, ICD-10 shape, CPT shape, dates, keywords)
- AI: Claude reads the page images and the OCR text and answers in a fixed JSON shape; every quote it returns must
  be found in the OCR text, or that line is marked unverified.
Nothing is stored. Without an API key only the rules layer runs.
"""
from __future__ import annotations

import io
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from authops.docagent.validators import _found
from authops.docintel.normalize import KNOWN_ICD10, npi_valid, parse_date

ICD = re.compile(r"\b([A-TV-Z][0-9][0-9AB](?:\.[0-9A-TV-Z]{1,4})?)\b")
CPT = re.compile(r"\b(9[0-9]{4}|0[0-9]{3}T|[A-V][0-9]{4})\b")
NPI = re.compile(r"\b(\d{10})\b")
DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4})\b")
UNITS = re.compile(r"(?:(?:approved|authorized)\s+(?:units|visits|hours|sessions)|(?:units|visits|hours|sessions)\s+"
                   r"(?:approved|authorized)|^\s*QTY\b[^\d\n]*)\s*[:.\-]*\s*(\d{1,4})\b", re.I | re.M)
APPEAL = re.compile(r"within\s+(\d{1,3})\s+(?:calendar\s+|business\s+)?days", re.I)
REASON = re.compile(r"reason(?:\s+for\s+(?:the\s+)?(?:denial|decision))?\s*[:\-]\s*\n?\s*([^\n]{8,200})", re.I)


# ------------------------------------------------------------------ input

def to_pages(data: bytes, name: str, max_pages: int = 3) -> list[Path]:
    """PNG, JPG or PDF bytes -> up to `max_pages` PNG files on disk (deleted with the temp dir by the OS)."""
    d = Path(tempfile.mkdtemp(prefix="assist_"))
    out = []
    if name.lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        for i in range(min(len(pdf), max_pages)):
            img = pdf[i].render(scale=2.0).to_pil()
            p = d / f"p{i + 1}.png"
            img.convert("RGB").save(p)
            out.append(p)
    else:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        if max(img.size) > 2400:
            img.thumbnail((2400, 2400))
        p = d / "p1.png"
        img.save(p)
        out.append(p)
    return out


def _photo(img: Image.Image) -> Image.Image:
    """Phone photos: uneven light breaks a fixed black/white threshold. Upscale and stretch contrast instead."""
    from PIL import ImageOps
    g = ImageOps.grayscale(img)
    if g.width < 1800:
        g = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
    return ImageOps.autocontrast(g, cutoff=2)


def ocr_text(pages: list[Path]) -> str:
    """Read each page two ways (scan cleanup and phone-photo cleanup) and keep the one OCR is more sure of."""
    import pytesseract

    from authops.docintel.ocr import ocr_image
    out = []
    for p in pages:
        img = Image.open(p).convert("RGB")
        scan = ocr_image(img)
        d = pytesseract.image_to_data(_photo(img), config="--psm 4", output_type=pytesseract.Output.DICT)
        conf = [float(c) for c, t in zip(d["conf"], d["text"]) if t.strip() and float(c) >= 0]
        lines: dict = {}
        for i, t in enumerate(d["text"]):
            if t.strip():
                lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(t.strip())
        photo_conf = sum(conf) / len(conf) if conf else 0.0
        out.append("\n".join(" ".join(v) for v in lines.values()) if photo_conf > scan.mean_conf else scan.text)
    return "\n\n".join(out)


# ------------------------------------------------------------------ referrals, insurance order, visit logs
# Learned from a real outpatient PT clinic's paperwork (de-identified): a referral lists the reason for the
# visit next to a long problem list, the patient can have three insurances, and the clinic's visit log uses
# its own modality shorthand rather than billing codes.

REF_REASON = re.compile(r"referral\s+reason\s*[:\-]?\s*\n?\s*([^\n]{3,160})", re.I)
INSURANCE = re.compile(r"\b(first|primary|secondary|second|third|tertiary)\s+insurance\s*[:\-]\s*([^\n(]{3,60})", re.I)
ORDER = {"first": 1, "primary": 1, "secondary": 2, "second": 2, "third": 3, "tertiary": 3}
# Empire BlueCross BlueShield became Anthem Blue Cross and Blue Shield in New York on Jan 1, 2024 (same member IDs).
PAYOR_ALIASES = [(r"\b(bcbs|blue\s*cross|empire|anthem)\b", "Anthem Blue Cross and Blue Shield"),
                 (r"\bvns\b|vnsny|vns\s*health", "VNS Health"), (r"\bmedicaid\b", "Medicaid"),
                 (r"\bmedicare\b", "Medicare")]
PT_MODALITIES = {  # clinic shorthand -> (what it is, CPT code, note)
    "CP": ("cold packs", "97010", "usually bundled, not paid on its own"),
    "HP": ("hot packs", "97010", "usually bundled, not paid on its own"),
    "US": ("ultrasound", "97035", "timed, 15-minute units"),
    "ES": ("electrical stimulation", "97014", "unattended; Medicare plans usually want G0283; 97032 if attended"),
    "AE": ("active assisted exercise", "97110", "therapeutic exercise, timed"),
    "TE": ("therapeutic exercise", "97110", "timed, 15-minute units"),
    "TM": ("treadmill", "97110", "97116 if documented as gait training"),
    "MR": ("myofascial release", "97140", "manual therapy, timed"),
    "TX": ("traction", "97012", "mechanical traction"),
    "PB": ("paraffin bath", "97018", ""),
    "IE": ("initial evaluation", "97161-97163", "low, moderate or high complexity"),
}


def _icd_fix(code: str) -> str:
    """OCR repairs inside an ICD-10 code: a letter first, then digits (MS4.50 -> M54.50)."""
    c = code.upper().replace("}", "").replace(")", "")
    head, tail = c[:1], c[1:]
    return head + tail.translate(str.maketrans({"S": "5", "O": "0", "I": "1", "L": "1", "B": "8", "Z": "2"}))


def payor_name(raw: str) -> str:
    for pat, name in PAYOR_ALIASES:
        if re.search(pat, raw, re.I):
            return name
    return raw.strip()


def insurances(text: str) -> list[dict]:
    out = []
    for order, raw in INSURANCE.findall(text):
        raw = re.sub(r"\s*insured\b.*$", "", raw, flags=re.I).strip(" :")
        out.append({"order": ORDER[order.lower()], "as_written": raw, "payor": payor_name(raw),
                    "medicare_advantage": bool(re.search(r"advantage|dual|\bmapd?\b|d-?snp", raw, re.I))})
    return sorted(out, key=lambda r: r["order"])


def send_auth_to(ins: list[dict]) -> dict | None:
    """Which plan gets the prior-auth request, and what to know about the others."""
    if not ins:
        return None
    first = ins[0]
    names = {i["payor"] for i in ins}
    notes = []
    dual = "Medicaid" in names and ("Medicare" in names or any(i["medicare_advantage"] for i in ins))
    if first["medicare_advantage"]:
        notes.append("The primary plan is a Medicare Advantage plan, so it manages these visits. Original Medicare, "
                     "if listed, does not pay while the patient is enrolled in it.")
    if dual:
        notes.append("Medicare and Medicaid both apply (dual eligible). Medicaid is billed after the primary plan, "
                     "so the request goes to the primary plan first.")
    if first["payor"] == "Anthem Blue Cross and Blue Shield" and re.search(r"bcbs|blue|empire", first["as_written"], re.I):
        notes.append("BCBS and Empire plans in New York are now Anthem Blue Cross and Blue Shield; member IDs did not change.")
    return {"payor": first["payor"], "as_written": first["as_written"], "dual_eligible": dual, "notes": notes}


def referral(text: str) -> dict | None:
    """A doctor's referral, not a plan of care: find the reason for this referral among everything else."""
    if not re.search(r"referral\s+reason|please evaluate|referral\s+date|referred\s+(?:to|for)", text, re.I):
        return None
    m = REF_REASON.search(text)
    reason, code = (m.group(1).strip() if m else None), None
    if reason:
        cm = re.search(r"\(?\s*([A-TV-Z][0-9OSIL][0-9A-Z]\.?[0-9A-Z}]{0,4})\s*[)}]?\s*$", reason)
        if cm:
            code = _icd_fix(cm.group(1))
            reason = reason[:cm.start()].strip(" ,(")
    discipline = "physical therapy" if re.search(r"^\s*PT\s*$|physical therap", text, re.I | re.M) else None
    others = sorted({c for c in ICD.findall(text) if c != code})
    return {"reason": reason, "code": code, "discipline": discipline, "other_codes": len(others)}


LEGEND = {"CP": r"cold\s*pack", "HP": r"h\w{1,2}t\s*pack", "US": r"ultra\s*s", "ES": r"electric|e-?stim",
          "AE": r"active\s*assist", "TE": r"thera?\s*p?\s*eutic|therd\s*peutic", "TM": r"tread\s*mill",
          "MR": r"myo\s*fascial", "TX": r"traction|^TX\b", "PB": r"paraffin", "IE": r"initial\s+eval"}


def modality_codes(text: str) -> list[dict]:
    """A clinic visit log (treatment record): map its column legend to billing codes.
    Matched on the legend wording, which survives OCR better than the two-letter column heads."""
    hits = [k for k, pat in LEGEND.items() if re.search(pat, text, re.I | re.M)]
    if len(hits) < 3 and not re.search(r"treatment\s+record|visit\s+log|flow\s*sheet", text, re.I):
        return []
    return [{"column": k, "means": PT_MODALITIES[k][0], "cpt": PT_MODALITIES[k][1], "note": PT_MODALITIES[k][2]}
            for k in hits]


# ------------------------------------------------------------------ rules layer

def facts(text: str) -> dict:
    icd = sorted(set(ICD.findall(text)))
    cpt = sorted({c for c in CPT.findall(text) if not c.startswith(("19", "20"))})
    npis = sorted(set(NPI.findall(text)))
    dates = []
    for s in DATE.findall(text):
        d = parse_date(s)
        if d and 1990 < d.year < 2100:
            dates.append(d)
    low = text.lower()
    decision = ("partially approved" if re.search(r"partial(ly)?\s+approv", low) else
                "denied" if re.search(r"\b(denied|not approved|adverse determination|deny)\b", low) else
                "approved" if re.search(r"\bapproved\b", low) else None)
    um = UNITS.search(text)
    am, rm = APPEAL.search(text), REASON.search(text)
    period = [d for d in dates if d.year >= date.today().year - 1]
    return {"period": sorted(set(period)), "appeal_days": int(am.group(1)) if am else None,
            "reason": rm.group(1).strip() if rm else None,"icd10": icd, "icd10_known": [c for c in icd if c in KNOWN_ICD10], "cpt": cpt,
            "npis": [{"npi": n, "valid": npi_valid(n)} for n in npis], "dates": sorted(set(dates)),
            "decision": decision, "units": int(um.group(1)) if um else None,
            "signed": bool(re.search(r"/s/|electronically signed|signed by|signature\s*[:\-]\s*[A-Za-z]", text, re.I)),
            "has_goals": bool(re.search(r"\bgoal", low)), "has_baseline": "baseline" in low,
            "has_necessity": "necess" in low}


# ------------------------------------------------------------------ AI layer

LETTER_PROMPT = """This is a letter from a health insurer (a payor) about a prior authorization, or a similar
insurance letter. Read it for the patient or family, who are not experts.

Return only JSON with these keys:
{"decision": "approved" | "partially approved" | "denied" | "more information needed" | "not a decision letter",
 "service": short name of the care, "approved_amount": e.g. "24 visits" or null, "requested_amount": or null,
 "start": "YYYY-MM-DD" or null, "end": "YYYY-MM-DD" or null, "reason": the payor's reason in plain words or null,
 "letter_date": "YYYY-MM-DD" or null, "appeal_days": number of days the letter gives to appeal, or null if not stated,
 "summary": two short sentences in plain English for the patient,
 "next_steps": three short actions the patient or family can take, most useful first,
 "questions": two or three questions to ask the clinic or the insurer,
 "quotes": up to three exact short phrases copied from the letter that support the decision and dates}
Do not invent anything that is not in the letter. If something is not stated, use null."""

PLAN_PROMPT = """This is a treatment plan or a prior authorization request that a clinic is about to send to a
health insurer. Check it the way an experienced authorization specialist would, so it is approved the first time.

Return only JSON: {"service": short name, "checks": [{"name": short check name, "status": "pass" | "fix" | "unclear",
 "detail": one plain sentence, "quote": exact short phrase copied from the document, or null}],
 "missing": short list of things a payor usually asks for that are not in the document,
 "summary": one sentence on whether it is ready to send}
Always include these checks, in this order: provider signature and date; diagnosis codes; service codes;
requested amount and frequency; plan dates; measurable goals with baselines; medical necessity tied to the
patient's specific deficits; standardized assessment named and dated; caregiver or home program (if ABA or therapy).
Do not invent anything that is not in the document."""


def _ask(prompt: str, text: str, pages: list[Path], llm) -> tuple[dict | None, dict]:
    from authops.llm import parse_json
    r = llm.complete(prompt + "\n\nOCR text of the document (may contain errors):\n" + text[:12000],
                     images=pages[:3], max_tokens=1500)
    out = parse_json(r.text)
    return (out if isinstance(out, dict) else None), {"model": r.model, "seconds": round(r.latency_ms / 1000, 1),
                                                      "cost_usd": round(r.cost_usd, 4)}


def _grounded(quote: str | None, text: str) -> bool | None:
    if not quote:
        return None
    return _found(quote[:160], text)


# ------------------------------------------------------------------ patient: read a letter

def read_letter(pages: list[Path], llm=None, text: str | None = None) -> dict:
    text = text if text is not None else ocr_text(pages)
    f = facts(text)
    res = {"layer": "rules", "text_chars": len(text), "facts": f, "decision": f["decision"],
           "approved_amount": f"{f['units']} units" if f["units"] else None,
           "start": f["period"][0].isoformat() if len(f["period"]) >= 2 else None,
           "end": f["period"][-1].isoformat() if len(f["period"]) >= 2 else None,
           "reason": f["reason"], "appeal_days": f["appeal_days"], "summary": None, "next_steps": [], "questions": [], "quotes": []}
    if llm is not None:
        try:
            ai, meta = _ask(LETTER_PROMPT, text, pages, llm)
        except Exception as e:  # network, quota or key problems: keep the rules answer
            ai, res["ai_error"] = None, type(e).__name__
        if ai:
            res.update({k: ai.get(k) for k in ("decision", "service", "approved_amount", "requested_amount", "start", "end",
                                               "reason", "letter_date", "appeal_days", "summary") if k in ai})
            res["next_steps"] = [s for s in (ai.get("next_steps") or []) if isinstance(s, str)][:3]
            res["questions"] = [s for s in (ai.get("questions") or []) if isinstance(s, str)][:3]
            res["quotes"] = [{"text": q, "found": _grounded(q, text)} for q in (ai.get("quotes") or []) if isinstance(q, str)][:3]
            res["layer"], res["ai"] = "AI", meta
            # the rules layer is the referee: a decision word the AI reports must appear on the page
            if res["decision"] in ("approved", "partially approved", "denied") and f["decision"] and \
                    f["decision"] != res["decision"]:
                res["conflict"] = f"The page says '{f['decision']}' but the AI read '{res['decision']}'. Check the letter."
    else:
        res["summary"] = {"approved": "The letter appears to approve the request.",
                          "partially approved": "The letter appears to approve only part of what was asked for.",
                          "denied": "The letter appears to deny the request."}.get(f["decision"] or "", None)
    res["deadline"] = _deadline(res)
    res["next_steps"] = res["next_steps"] or _default_steps(res.get("decision"))
    return res


def _deadline(res: dict) -> str | None:
    days = res.get("appeal_days")
    base = parse_date(res.get("letter_date")) if res.get("letter_date") else None
    if isinstance(days, (int, float)) and days > 0 and base:
        return f"by {(base + timedelta(days=int(days))):%b %d, %Y}"
    if isinstance(days, (int, float)) and days > 0:
        return f"within {int(days)} days of the letter's date"
    return None


def _default_steps(decision: str | None) -> list[str]:
    if decision == "denied":
        return ["Ask the clinic whether they will appeal or resubmit, and by when.",
                "Find the appeal deadline in the letter and put it on your calendar.",
                "Ask your doctor for a letter of medical necessity if an appeal is filed."]
    if decision == "partially approved":
        return ["Schedule care within the approved amount and dates.",
                "Ask the clinic to request the rest before the approved visits run out.",
                "Check your plan's copay or coinsurance for these visits."]
    if decision == "approved":
        return ["Schedule visits inside the approved dates.",
                "Keep count of visits used against the approved amount.",
                "Ask the clinic to start the renewal two to three weeks before it ends."]
    return ["Call the number on the letter and ask what decision was made.",
            "Ask the clinic whether anything is missing from the request.",
            "Write down the reference number for every call."]


# ------------------------------------------------------------------ clinic: check a plan before sending

RULE_CHECKS = ["Provider signature and date", "Diagnosis codes", "Service codes", "Provider NPI", "Plan dates"]


def check_referral(r: dict, ins: list[dict], f: dict) -> dict:
    """A referral starts a PT authorization but is not the request: say what it gives and what is still missing."""
    checks = [{"name": "Reason for this referral", "layer": "rules", "status": "pass" if r["code"] else "fix",
               "detail": (f"{r['reason']} ({r['code']}). Use this code on the request." if r["code"] else
                          "No diagnosis code next to the referral reason; ask the referring office for it.")
               + (f" The other {r['other_codes']} codes on the page are the patient's history, not this referral."
                  if r["other_codes"] else "")}]
    to = send_auth_to(ins)
    if to:
        checks.append({"name": "Which plan gets the request", "layer": "rules", "status": "pass",
                       "detail": f"Send it to the primary plan: {to['payor']} (written as \"{to['as_written']}\"). "
                       + " ".join(to["notes"])})
    else:
        checks.append({"name": "Which plan gets the request", "layer": "rules", "status": "unclear",
                       "detail": "No insurance listed on the referral; confirm the primary plan on the insurance card."})
    if f["npis"]:
        ok = any(n["valid"] for n in f["npis"])
        checks.append({"name": "Referring provider NPI", "layer": "rules", "status": "pass" if ok else "fix",
                       "detail": "NPI passes the checksum." if ok else "NPI fails the checksum; check for a typo."})
    missing = ["Initial evaluation by the physical therapist (CPT 97161-97163)",
               "Plan of care with measurable goals, frequency and duration, signed by the therapist",
               "Visit codes for the planned treatment (for example 97110, 97140, 97035)",
               "Rendering therapist NPI"]
    return {"layer": "rules", "kind": "referral", "facts": f, "referral": r, "insurances": ins, "send_to": to,
            "checks": checks, "missing": missing,
            "summary": "This is a referral. It gives the reason and the insurance; the payor also needs the evaluation "
                       "and a signed plan of care before visits are approved."}


def check_plan(pages: list[Path], llm=None, text: str | None = None, today: date | None = None) -> dict:
    text = text if text is not None else ocr_text(pages)
    f = facts(text)
    today = today or date.today()
    ref = referral(text)
    if ref:
        res = check_referral(ref, insurances(text), f)
        n = len(res["checks"]) + len(res["missing"])   # a referral alone is not ready to send
        res["score"] = round(100 * sum(c["status"] == "pass" for c in res["checks"]) / n)
        res["to_fix"] = sum(c["status"] == "fix" for c in res["checks"]) + len(res["missing"])
        return res
    log = modality_codes(text)
    if log and not (f["has_goals"] or f["icd10"] or f["cpt"]):
        return {"layer": "rules", "kind": "visit_log", "facts": f, "modalities": log, "score": 100, "to_fix": 0,
                "checks": [{"name": "Visit log columns as billing codes", "status": "pass", "layer": "rules",
                            "detail": "; ".join(f"{m['column']} = {m['means']}, {m['cpt']}"
                                                + (f" ({m['note']})" if m["note"] else "") for m in log) + "."}],
                "missing": ["The authorization number, approved visit count and end date, kept with this log so "
                            "each visit is counted against the approval"],
                "summary": "This is a visit log. Each column maps to a billing code; count visits against the approval."}
    checks = []
    checks.append({"name": "Provider signature and date", "status": "pass" if f["signed"] else "fix", "layer": "rules",
                   "detail": "A signature line was found." if f["signed"] else "No signature found. Unsigned plans are a top denial reason."})
    checks.append({"name": "Diagnosis codes", "status": "pass" if f["icd10"] else "fix", "layer": "rules",
                   "detail": (f"ICD-10 codes found: {', '.join(f['icd10'][:5])}." if f["icd10"] else
                              "No ICD-10 diagnosis code found.")})
    checks.append({"name": "Service codes", "status": "pass" if f["cpt"] else "unclear", "layer": "rules",
                   "detail": (f"Service codes found: {', '.join(f['cpt'][:6])}." if f["cpt"] else
                              "No CPT or HCPCS codes found. Most payors need them on the request.")})
    if f["npis"]:
        bad = [n["npi"] for n in f["npis"] if not n["valid"]]
        checks.append({"name": "Provider NPI", "status": "fix" if bad and len(bad) == len(f["npis"]) else "pass", "layer": "rules",
                       "detail": (f"NPI {', '.join(bad)} fails the NPI checksum; check for a typo." if bad else
                                  "NPI passes the checksum.")})
    else:
        checks.append({"name": "Provider NPI", "status": "unclear", "layer": "rules", "detail": "No 10-digit NPI found."})
    ds = f["period"]
    if len(ds) >= 2:
        expired = ds[-1] < today
        checks.append({"name": "Plan dates", "status": "fix" if expired else "pass", "layer": "rules",
                       "detail": f"Latest date on the plan is {ds[-1]:%b %d, %Y}" + (", which has passed." if expired else ".")})
    else:
        checks.append({"name": "Plan dates", "status": "unclear", "layer": "rules", "detail": "Could not find a start and end date."})
    if log:
        checks.append({"name": "Visit log columns as billing codes", "status": "pass", "layer": "rules",
                       "detail": "; ".join(f"{m['column']} = {m['means']}, {m['cpt']}" for m in log) + "."})
    res = {"layer": "rules", "facts": f, "checks": checks, "missing": [], "summary": None, "modalities": log}
    if llm is not None:
        try:
            ai, meta = _ask(PLAN_PROMPT, text, pages, llm)
        except Exception as e:
            ai, res["ai_error"] = None, type(e).__name__
        if ai:
            have = {c["name"].lower() for c in checks}
            for c in ai.get("checks") or []:
                if not isinstance(c, dict) or not c.get("name"):
                    continue
                q = c.get("quote")
                st_ = str(c.get("status", "")).lower()
                st_ = ("pass" if st_ in ("pass", "ok", "present", "yes", "complete") else
                       "fix" if st_ in ("fix", "fail", "failed", "missing", "no", "error") else "unclear")
                item = {"name": c["name"], "status": st_, "detail": c.get("detail", ""),
                        "quote": q, "found": _grounded(q, text), "layer": "AI"}
                if item["status"] == "pass" and q and item["found"] is False:
                    item["status"], item["detail"] = "unclear", item["detail"] + " (The quote could not be found on the page.)"
                if c["name"].lower() not in have:
                    res["checks"].append(item)
            res["missing"] = [m for m in (ai.get("missing") or []) if isinstance(m, str)][:6]
            res["summary"], res["service"] = ai.get("summary"), ai.get("service")
            res["layer"], res["ai"] = "AI", meta
    if res["layer"] == "rules":
        for name, ok in (("Measurable goals with baselines", f["has_goals"] and f["has_baseline"]),
                         ("Medical necessity", f["has_necessity"])):
            res["checks"].append({"name": name, "status": "pass" if ok else "unclear", "layer": "rules",
                                  "detail": "Mentioned on the page." if ok else "Not found by keyword; a person should check."})
    n = len(res["checks"])
    res["score"] = round(100 * sum(c["status"] == "pass" for c in res["checks"]) / n) if n else 0
    res["to_fix"] = sum(c["status"] == "fix" for c in res["checks"])
    return res
