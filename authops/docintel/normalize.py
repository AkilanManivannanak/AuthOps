"""Normalizers and validators for healthcare identifiers.

Validators matter as much as extraction: a value that fails its check (NPI Luhn,
ICD-10 shape, date order) lowers confidence and can trigger abstention instead of
flowing silently into a portal form.
"""
from __future__ import annotations

import re
from datetime import date, datetime

ICD10_RE = re.compile(r"\b([A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?)\b")
CPT_RE = re.compile(r"\b(9\d{4})\b")  # the services in scope are all 9xxxx
NPI_RE = re.compile(r"\b(\d{10})\b")

# Billable codes in scope. A real system would load the full CMS ICD-10 file.
KNOWN_ICD10 = {"F84.0", "F84.5", "F88", "M54.50", "M25.561", "S83.511A", "M17.11",
               "F41.1", "F32.1", "F43.10"}
SPECIALTY_CPT = {
    "aba": {"97151", "97153", "97155", "97156"},
    "physical_therapy": {"97110", "97140", "97530", "97161"},
    "behavioral_health": {"90837", "90834", "90847"},
}

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}


def npi_valid(npi: str | None) -> bool:
    if not npi or not re.fullmatch(r"\d{10}", npi):
        return False
    digits = [int(d) for d in "80840" + npi]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def icd10_valid(code: str) -> bool:
    return code in KNOWN_ICD10


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip().strip(".,")
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1).lower() in MONTHS:
        try:
            return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None
    return None


DATE_PATTERN = (r"(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}|"
                r"(?:January|February|March|April|May|June|July|August|September|October|"
                r"November|December)\s+\d{1,2},\s+\d{4})")


def find_dates(s: str) -> list[date]:
    return [d for d in (parse_date(m) for m in re.findall(DATE_PATTERN, s)) if d]


def norm_name(s: str | None) -> str | None:
    """'FUJIMOTO, CALEB' and 'Caleb Fujimoto' both become 'caleb fujimoto'."""
    if not s:
        return None
    s = re.sub(r"\s+", " ", s.strip())
    if "," in s:
        last, first = [x.strip() for x in s.split(",", 1)]
        s = f"{first} {last}"
    return s.lower()


def norm_id(s: str | None) -> str | None:
    if s is None:
        return None
    return re.sub(r"[^A-Z0-9-]", "", str(s).upper())


def ocr_fix_digits(s: str) -> str:
    """Common OCR confusions inside fields that must be numeric."""
    return s.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"}))
