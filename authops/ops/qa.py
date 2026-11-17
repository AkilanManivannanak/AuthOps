"""Simulated specialist QA review.

Compares what reached the payor (captured by the sandbox portal) with the intake
record and grades each difference minor or major, the way Silna's specialists flag
agent errors. The output is an error dataset: agent value next to the correct value,
which is what prompt fixes and backtests are built from.
"""
from __future__ import annotations

MAJOR = {"member_id", "cpt", "units", "start", "end", "npi", "dob"}


def expected_fields(case: dict) -> dict:
    return {
        "member_id": case["patient"]["member_id"], "dob": case["patient"]["dob"],
        "cpt": sorted(case["cpt_codes"]), "icd": sorted(case["icd10_codes"]),
        "units": str(case["requested_units"]), "start": case["start_date"], "end": case["end_date"],
        "npi": case["provider"]["npi"],
    }


def review(submission: dict, case: dict) -> list[dict]:
    exp = expected_fields(case)
    got = submission["fields"]
    issues = []
    for k, want in exp.items():
        if k not in got:
            continue
        have = got[k]
        if isinstance(want, list):
            have_n = sorted(str(x).strip().upper() for x in (have if isinstance(have, list) else [have]))
            ok = have_n == [w.upper() for w in want]
        else:
            ok = str(have).strip() == str(want)
        if not ok:
            loose = str(have).replace(" ", "").lower() == str(want).replace(" ", "").lower()
            issues.append({"field": k, "submitted": have, "expected": want,
                           "severity": "minor" if loose or k not in MAJOR else "major",
                           "comment": "formatting only" if loose else "wrong value reached the payor"})
    if not submission.get("files"):
        issues.append({"field": "attachments", "submitted": [], "expected": ["treatment_plan"],
                       "severity": "major", "comment": "no clinical documents attached"})
    return issues
