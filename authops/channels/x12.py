"""X12 278 health care services review (HIPAA 5010, 005010X217): the EDI request clinics and clearinghouses
send to payors for prior authorization, and the response that comes back.

`build_278_request` turns a case into an interchange (ISA/GS/ST ... SE/GE/IEA): payor, requester, subscriber,
the patient event (diagnoses, dates) and one service line per CPT code. `parse_278_response` reads a payor's
answer with the delimiters that file declares in its ISA, and returns the decision for the event and for each
service line (HCR action code, authorization number, approved quantity, dates). `validate_x12` checks what a
clearinghouse checks before accepting a file: the envelope, counts and control numbers, and element values
such as SV1 units. A working subset of the implementation guide: enough to exchange real-shaped files, not a
certified implementation.
"""
from __future__ import annotations

import re
from datetime import date, datetime

SEG, EL, SUB = "~", "*", ":"          # what this project writes; reading uses what the file declares
SERVICE_TYPE = {"aba": "MH", "behavioral_health": "MH", "physical_therapy": "PT"}
HCR = {"A1": "approved", "A2": "approved with changes", "A3": "denied", "A4": "pended", "A6": "partial",
       "C": "cancelled", "CT": "contact payor", "NA": "no action required"}
HCR_FROM = {"approved": "A1", "denied": "A3", "partial": "A6", "pended": "A4"}
VISIT_SPECIALTIES = {"physical_therapy", "behavioral_health"}   # requested as visits: HSD*VS at the service level


def _d8(d) -> str:
    return (d if isinstance(d, date) else date.fromisoformat(str(d))).strftime("%Y%m%d")


def clean(v) -> str:
    """Data must never contain a delimiter: O*NEIL would shift every element after it."""
    return re.sub(r"[*~:^|>]", " ", str(v)).strip()


def _provider_name(prov: dict) -> tuple[str, str]:
    """(last, first) without credentials: 'Samuel Ortiz, DPT' -> ('ORTIZ', 'SAMUEL')."""
    if prov.get("last_name"):
        return clean(prov["last_name"]).upper(), clean(prov.get("first_name", "")).upper()
    name = re.sub(r",\s*[A-Z][A-Za-z.\-]{1,8}$", "", prov.get("name", "PROVIDER")).strip()
    parts = name.split()
    return (clean(parts[-1]).upper(), clean(" ".join(parts[:-1])).upper()) if len(parts) > 1 else (clean(name).upper(), "")


def _isa(sender: str, receiver: str, ctrl: int, now: datetime) -> str:
    f = ["ISA", "00", " " * 10, "00", " " * 10, "ZZ", sender[:15].ljust(15), "ZZ", receiver[:15].ljust(15),
         now.strftime("%y%m%d"), now.strftime("%H%M"), "^", "00501", f"{ctrl:09d}", "0", "P", SUB]
    return EL.join(f)


def _wrap(body: list[str], sender: str, receiver: str, ctrl: int, now: datetime, impl="005010X217") -> str:
    st = [f"ST*278*{ctrl % 10000:04d}*{impl}"] + body
    st.append(f"SE*{len(st) + 1}*{ctrl % 10000:04d}")
    segs = [_isa(sender, receiver, ctrl, now), f"GS*HI*{sender}*{receiver}*{now:%Y%m%d}*{now:%H%M}*{ctrl}*X*{impl}"]
    segs += st + [f"GE*1*{ctrl}", f"IEA*1*{ctrl:09d}"]
    return SEG.join(segs) + SEG


def build_278_request(case: dict, ctrl: int = 1, now: datetime | None = None, sender: str = "AUTHOPS") -> str:
    """case: the dict form of a request (patient, provider, payor, codes, dates, units, specialty)."""
    now = now or datetime.now()
    p, prov, pay = case["patient"], case["provider"], case["payor"]
    spec = case.get("specialty", "")
    icd = [clean(c).replace(".", "") for c in case["icd10_codes"]]
    hi = "HI*" + EL.join([f"ABK{SUB}{icd[0]}"] + [f"ABF{SUB}{c}" for c in icd[1:]])
    last, first = _provider_name(prov)
    body = [f"BHT*0007*13*{clean(case.get('case_id', 'REQ'))}*{now:%Y%m%d}*{now:%H%M}",
            "HL*1**20*1", f"NM1*X3*2*{clean(pay['name'])[:60].upper()}*****PI*{clean(pay['payor_id'])}",
            "HL*2*1*21*1", f"NM1*1P*1*{last}*{first}****XX*{clean(prov['npi'])}",
            "HL*3*2*22*1",
            f"NM1*IL*1*{clean(p['last_name']).upper()}*{clean(p['first_name']).upper()}****MI*{clean(p['member_id'])}",
            f"DMG*D8*{_d8(p['dob'])}",
            "HL*4*3*EV*1", f"UM*HS*I*{SERVICE_TYPE.get(spec, 'MH')}", hi,
            f"DTP*AAH*RD8*{_d8(case['start_date'])}-{_d8(case['end_date'])}"]
    units = int(case["requested_units"])
    for k, cpt in enumerate(case["cpt_codes"]):
        body += [f"HL*{5 + k}*4*SS*0", f"SV1*HC{SUB}{clean(cpt)}**UN*{units}"]   # SV103: UN (units) or MJ (minutes)
        if spec in VISIT_SPECIALTIES:
            body.append(f"HSD*VS*{units}")                                     # visits go in HSD, not SV1
    return _wrap(body, sender, clean(pay["payor_id"]), ctrl, now)


def build_278_response(request: str, decision: str, approved: int | None = None, auth: str = "",
                       reason: str = "", now: datetime | None = None, lines: dict[str, str] | None = None) -> str:
    """The payor side, for the sandbox: answer a request with an HCR decision for the event and, when `lines`
    maps a CPT code to a decision, a separate HCR on that service line (as real responses do)."""
    now = now or datetime.now()
    req = segments(request)
    get = lambda tag: next((s for s in req if s[0] == tag), None)  # noqa: E731
    gs = get("GS")
    body = [f"BHT*0007*11*{get('BHT')[3]}*{now:%Y%m%d}*{now:%H%M}"]
    for s in req:
        if s[0] in ("HL", "NM1", "DMG"):
            body.append(EL.join(s))
        if s[0] == "HL" and s[3] == "EV":
            body.append(f"HCR*{HCR_FROM[decision]}*{auth}" + (f"*{reason}" if reason else ""))
            if auth:
                body.append(f"REF*BB*{auth}")
            body.append(EL.join(get("DTP")))
            if approved is not None and decision in ("approved", "partial"):
                body.append(f"HSD*VS*{approved}")
        if s[0] == "SV1" and lines:
            cpt = s[1].split(SUB)[-1]
            d = lines.get(cpt)
            if d:
                body.append(EL.join(s))
                body.append(f"HCR*{HCR_FROM[d]}*{auth if d in ('approved', 'partial') else ''}"
                            + ("*NME" if d == "denied" else ""))
    return _wrap(body, gs[3], gs[2], int(gs[6]) + 1, now, impl="005010X217")


# ------------------------------------------------------------------ reading

def delimiters(x12: str) -> tuple[str, str, str]:
    """(element, sub-element, segment) as this file declares them in its fixed-width ISA."""
    t = x12.lstrip()
    if t.startswith("ISA") and len(t) >= 106:
        return t[3], t[104], t[105]
    return EL, SUB, SEG


def segments(x12: str) -> list[list[str]]:
    el, _, seg = delimiters(x12)
    return [s.strip().split(el) for s in x12.strip().split(seg) if s.strip()]


def _hcr(s: list[str]) -> dict:
    return {"action_code": s[1], "decision": HCR.get(s[1], "unknown"),
            "auth_number": s[2] if len(s) > 2 and s[2] else None,
            "reason_code": s[3] if len(s) > 3 and s[3] else None}


def parse_278_response(x12: str) -> dict:
    """Event-level decision plus one entry per service line. A mix of approved and denied lines is 'partial'."""
    _, sub, _ = delimiters(x12)
    out = {"decision": None, "action_code": None, "auth_number": None, "approved_quantity": None,
           "start": None, "end": None, "reason_code": None, "member_id": None, "payor_id": None, "lines": []}
    level, line = None, None
    for s in segments(x12):
        tag = s[0]
        if tag == "HL":
            level = s[3] if len(s) > 3 else None
            line = None
        elif tag == "SV1" and level == "SS":
            line = {"cpt": s[1].split(sub)[-1], "decision": None, "action_code": None, "auth_number": None,
                    "reason_code": None, "quantity": int(s[4]) if len(s) > 4 and s[4].isdigit() else None}
            out["lines"].append(line)
        elif tag == "HCR":
            h = _hcr(s)
            if level == "SS" and line is not None:
                line.update({k: v for k, v in h.items()})
            else:
                out.update(h)
        elif tag == "REF" and len(s) > 2 and s[1] == "BB" and level != "SS":
            out["auth_number"] = s[2]
        elif tag == "HSD" and len(s) > 2 and s[2].isdigit() and level != "SS":
            out["approved_quantity"] = int(s[2])
        elif tag == "DTP" and len(s) > 3 and s[2] == "RD8" and level != "SS":
            a, b = s[3].split("-")
            out["start"], out["end"] = f"{a[:4]}-{a[4:6]}-{a[6:]}", f"{b[:4]}-{b[4:6]}-{b[6:]}"
        elif tag == "NM1" and s[1] == "IL":
            out["member_id"] = s[-1]
        elif tag == "NM1" and s[1] == "X3":
            out["payor_id"] = s[-1]
    decided = {ln["decision"] for ln in out["lines"] if ln["decision"]}
    if "approved" in decided and "denied" in decided:
        out["decision"] = "partial"
        out["action_code"] = out["action_code"] or "A6"
    elif decided and out["decision"] is None:
        out["decision"] = decided.pop() if len(decided) == 1 else "partial"
    return out


def validate_x12(x12: str) -> list[str]:
    """Checks a clearinghouse runs before accepting a file. Empty list means it passes."""
    t = x12.lstrip()
    if not t.startswith("ISA"):
        return ["file must start with an ISA segment"]
    if len(t) < 106:
        return ["ISA must be 106 characters"]
    el, sub, segch = delimiters(t)
    errs, segs = [], segments(t)
    if len(segs[0]) != 17:
        errs.append(f"ISA must have 16 elements, found {len(segs[0]) - 1}")
    if t.index(segch) != 105:
        errs.append(f"ISA must be 106 characters, found {t.index(segch) + 1}")
    tags = [s[0] for s in segs]
    for need in ("GS", "ST", "BHT", "SE", "GE", "IEA"):
        if need not in tags:
            errs.append(f"missing {need}")
    if errs:
        return errs
    st, se = tags.index("ST"), tags.index("SE")
    if int(segs[se][1]) != se - st + 1:
        errs.append(f"SE count {segs[se][1]} does not match {se - st + 1} segments")
    if segs[st][2] != segs[se][2]:
        errs.append("ST and SE control numbers differ")
    gs, ge, iea = segs[tags.index("GS")], segs[tags.index("GE")], segs[tags.index("IEA")]
    if gs[6] != ge[2]:
        errs.append("GS and GE control numbers differ")
    if segs[0][13] != iea[2]:
        errs.append("ISA and IEA control numbers differ")
    if segs[st][1] != "278":
        errs.append("not a 278 transaction")
    for s in segs:
        if s[0] == "HI":
            for c in s[1:]:
                if not re.fullmatch(rf"AB[KF]{re.escape(sub)}[A-Z][0-9][0-9A-Z]{{1,5}}", c):
                    errs.append(f"bad diagnosis element {c}")
        if s[0] == "NM1" and s[1] == "1P":
            if not re.fullmatch(r"\d{10}", s[-1]):
                errs.append("requester NPI must be 10 digits")
            if len(s) != 10:
                errs.append(f"NM1*1P must have 9 elements, found {len(s) - 1} (a delimiter in a name?)")
        if s[0] == "NM1" and s[1] == "IL" and len(s) != 10:
            errs.append(f"NM1*IL must have 9 elements, found {len(s) - 1} (a delimiter in a name?)")
        if s[0] == "SV1":
            if len(s) < 5 or s[3] not in ("UN", "MJ"):
                errs.append(f"SV103 must be UN or MJ, found {s[3] if len(s) > 3 else 'nothing'}")
            if len(s) > 4 and not re.fullmatch(r"\d+(\.\d+)?", s[4]):
                errs.append("SV104 quantity must be a number")
        if s[0] == "HSD" and len(s) > 1 and s[1] not in ("VS", "DY", "FL", "HS", "MN", "WK"):
            errs.append(f"HSD01 quantity qualifier {s[1]} is not allowed")
    return errs
