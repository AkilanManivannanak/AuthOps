"""Field-level evaluation of extractors against ground truth.

Reports what an ops team actually needs to decide on auto-submit vs human QA:
  accuracy      correct / all fields (abstentions count as not correct)
  precision     correct / answered fields (how much to trust what it does fill in)
  coverage      answered / all fields
  doc_ok        documents where every critical field is correct
  silent_error  answered-but-wrong rate: the number that sends bad data to a payor
"""
from __future__ import annotations

from collections import defaultdict

from authops.docintel.normalize import norm_id, norm_name, parse_date
from authops.schemas import Extraction

CRITICAL = {
    "approval_letter": ["auth_number", "decision", "member_id", "cpt_codes", "approved_units",
                        "start_date", "end_date"],
    "denial_letter": ["auth_number", "decision", "member_id"],
    "treatment_plan": ["patient_name", "patient_dob", "member_id", "icd10_codes", "cpt_codes",
                       "requested_units", "plan_start", "plan_end", "signature_present"],
}
SKIP = {"denial_reason"}  # free text, scored separately if needed


def values_match(field: str, pred, truth) -> bool:
    if truth is None:
        return pred is None
    if pred is None:
        return False
    if isinstance(truth, list):
        return sorted(map(norm_id, pred if isinstance(pred, list) else [pred])) == sorted(map(norm_id, truth))
    if field.endswith("name"):
        return norm_name(str(pred)) == norm_name(str(truth))
    if field.endswith(("dob", "date", "start", "end")):
        return parse_date(str(pred)) == parse_date(str(truth))
    if isinstance(truth, bool):
        return bool(pred) == truth
    return norm_id(str(pred)) == norm_id(str(truth))


def score(extractions: list[Extraction], manifest: list[dict]) -> dict:
    meta = {m["doc_id"]: m for m in manifest}
    tot = defaultdict(lambda: defaultdict(int))
    field_rows = []
    doc_ok = defaultdict(lambda: [0, 0])
    for ex in extractions:
        m = meta[ex.doc_id]
        truth = m["truth"]
        crit_ok = True
        for field, t in truth.items():
            if field in SKIP or field not in ex.fields:
                continue
            fv = ex.fields[field]
            answered = not fv.abstained and fv.value is not None
            # a correct "null" (field legitimately absent) counts as answered-correct
            if t is None and fv.value is None:
                answered, ok = True, True
            else:
                ok = answered and values_match(field, fv.value, t)
            for key in ("all", f"cond:{m['condition']}", f"tmpl:{m['template']}",
                        f"field:{field}", f"type:{m['doc_type']}"):
                tot[key]["n"] += 1
                tot[key]["answered"] += answered
                tot[key]["correct"] += ok
                tot[key]["silent_err"] += answered and not ok
            field_rows.append({"doc_id": ex.doc_id, "field": field, "truth": t, "pred": fv.value,
                               "conf": fv.confidence, "abstained": fv.abstained, "ok": ok,
                               "condition": m["condition"]})
            if field in CRITICAL.get(m["doc_type"], []) and not ok:
                crit_ok = False
        for key in ("all", f"cond:{m['condition']}", f"type:{m['doc_type']}"):
            doc_ok[key][0] += crit_ok
            doc_ok[key][1] += 1
    summary = {}
    for k, v in tot.items():
        n = v["n"]
        summary[k] = {
            "n": n,
            "accuracy": round(v["correct"] / n, 3),
            "precision": round(v["correct"] / v["answered"], 3) if v["answered"] else None,
            "coverage": round(v["answered"] / n, 3),
            "silent_error": round(v["silent_err"] / n, 3),
        }
        if k in doc_ok:
            summary[k]["doc_ok"] = round(doc_ok[k][0] / doc_ok[k][1], 3)
            summary[k]["docs"] = doc_ok[k][1]
    return {"summary": summary, "rows": field_rows}
