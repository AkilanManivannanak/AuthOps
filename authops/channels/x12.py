"""X12 278 health care services review (HIPAA 5010, 005010X217): the EDI request clinics and clearinghouses
send to payors for prior authorization, and the response that comes back.

`build_278_request` turns a case into an interchange (ISA/GS/ST ... SE/GE/IEA) with the payor, requester,
subscriber, patient event (diagnoses, dates) and service lines. `parse_278_response` reads the payor's answer:
the HCR action code (certified, modified, denied, pended), the authorization number, approved quantity and dates.
`validate_x12` checks the envelope the way a clearinghouse would before accepting a file. A working subset of
the implementation guide: enough to exchange real-shaped files, not a certified implementation.
"""
from __future__ import annotations

import re
from datetime import date, datetime

SEG, EL, SUB = "~", "*", ":"
# X12 service type codes (element 1365) for the services in this project
SERVICE_TYPE = {"aba": "MH", "behavioral_health": "MH", "physical_therapy": "PT"}
HCR = {"A1": "approved", "A3": "denied", "A4": "pended", "A6": "partial", "CT": "contact payor", "NA": "no action required"}
HCR_FROM = {"approved": "A1", "denied": "A3", "partial": "A6", "pended": "A4"}
UNIT = {"aba": "UN", "physical_therapy": "VS", "behavioral_health": "VS"}   # units / visits


def _d8(d) -> str:
    return (d if isinstance(d, date) else date.fromisoformat(str(d))).strftime("%Y%m%d")


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
    icd = [c.replace(".", "") for c in case["icd10_codes"]]
    hi = "HI*" + EL.join([f"ABK{SUB}{icd[0]}"] + [f"ABF{SUB}{c}" for c in icd[1:]])
    stc = SERVICE_TYPE.get(case.get("specialty", ""), "MH")
    body = [f"BHT*0007*13*{case.get('case_id', 'REQ')}*{now:%Y%m%d}*{now:%H%M}",
            "HL*1**20*1", f"NM1*X3*2*{pay['name'][:60].upper()}*****PI*{pay['payor_id']}",
            "HL*2*1*21*1", f"NM1*1P*1*{prov.get('last_name', prov.get('name', 'PROVIDER')).upper()}*"
            f"{prov.get('first_name', '').upper()}****XX*{prov['npi']}",
            "HL*3*2*22*1", f"NM1*IL*1*{p['last_name'].upper()}*{p['first_name'].upper()}****MI*{p['member_id']}",
            f"DMG*D8*{_d8(p['dob'])}",
            "HL*4*3*EV*1", f"UM*HS*I*{stc}", hi,
            f"DTP*AAH*RD8*{_d8(case['start_date'])}-{_d8(case['end_date'])}"]
    for k, cpt in enumerate(case["cpt_codes"]):
        body += [f"HL*{5 + k}*4*SS*0", f"SV1*HC{SUB}{cpt}**{UNIT.get(case.get('specialty', ''), 'UN')}*{case['requested_units']}"]
    return _wrap(body, sender, pay["payor_id"], ctrl, now)


def build_278_response(request: str, decision: str, approved: int | None = None, auth: str = "",
                       reason: str = "", now: datetime | None = None) -> str:
    """The payor side, for the sandbox: answer a request with an HCR decision."""
    now = now or datetime.now()
    req = segments(request)
    get = lambda tag: next((s for s in req if s[0] == tag), None)  # noqa: E731
    gs = get("GS")
    body = [f"BHT*0007*11*{get('BHT')[3]}*{now:%Y%m%d}*{now:%H%M}"]
    for s in req:
        if s[0] in ("HL", "NM1", "DMG"):
            body.append(EL.join(s))
        if s[0] == "HL" and s[3] == "EV":
            hcr = f"HCR*{HCR_FROM[decision]}*{auth}" + (f"*{reason}" if reason else "")
            body += [hcr, f"REF*BB*{auth}" if auth else "", EL.join(get("DTP"))]
            if approved is not None and decision in ("approved", "partial"):
                body.append(f"HSD*VS*{approved}")
    body = [b for b in body if b]
    return _wrap(body, gs[3], gs[2], int(gs[6]) + 1, now, impl="005010X217")


# ------------------------------------------------------------------ reading

def segments(x12: str) -> list[list[str]]:
    return [s.strip().split(EL) for s in x12.strip().split(SEG) if s.strip()]


def parse_278_response(x12: str) -> dict:
    segs = segments(x12)
    out = {"decision": None, "action_code": None, "auth_number": None, "approved_quantity": None,
           "start": None, "end": None, "reason_code": None, "member_id": None, "payor_id": None}
    for s in segs:
        if s[0] == "HCR":
            out["action_code"] = s[1]
            out["decision"] = HCR.get(s[1], "unknown")
            out["auth_number"] = (s[2] if len(s) > 2 and s[2] else None)
            out["reason_code"] = s[3] if len(s) > 3 else None
        elif s[0] == "REF" and s[1] == "BB":
            out["auth_number"] = s[2]
        elif s[0] == "HSD" and len(s) > 2 and s[2]:
            out["approved_quantity"] = int(s[2])
        elif s[0] == "DTP" and s[2] == "RD8":
            a, b = s[3].split("-")
            out["start"] = f"{a[:4]}-{a[4:6]}-{a[6:]}"
            out["end"] = f"{b[:4]}-{b[4:6]}-{b[6:]}"
        elif s[0] == "NM1" and s[1] == "IL":
            out["member_id"] = s[-1]
        elif s[0] == "NM1" and s[1] == "X3":
            out["payor_id"] = s[-1]
    return out


def validate_x12(x12: str) -> list[str]:
    """Envelope checks a clearinghouse runs before accepting a file. Empty list means it passes."""
    errs, segs = [], segments(x12)
    if not segs or segs[0][0] != "ISA":
        return ["file must start with an ISA segment"]
    isa = EL.join(segs[0])
    if len(isa) != 105:   # 106 with the segment terminator
        errs.append(f"ISA must be 106 characters, found {len(isa) + 1}")
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
                if not re.fullmatch(r"AB[KF]:[A-Z][0-9][0-9A-Z]{1,5}", c):
                    errs.append(f"bad diagnosis element {c}")
        if s[0] == "NM1" and s[1] == "1P" and not re.fullmatch(r"\d{10}", s[-1]):
            errs.append("requester NPI must be 10 digits")
    return errs
