"""Structured extraction from OCR'd prior-auth documents.

Two extractors share one interface so they can be compared field by field:

* RuleExtractor: label-synonym parsing with validators. Free, fast, brittle on
  unseen templates. This is the baseline every LLM arm has to beat.
* ClaudeExtractor: OCR text (or page images) into a Pydantic schema, with a quoted
  evidence span required for every field. Long documents are chunked, extracted in
  parallel and merged by a synthesizer call, the pattern Silna describes for
  context degradation on long inputs. Evidence that is not found in the OCR text
  drops the field's confidence (a cheap groundedness check).

Both return per-field confidence and abstain below a threshold, because a blank
field routed to a human is cheaper than a wrong one submitted to a payor.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date as _date
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from authops.docintel.normalize import (
    DATE_PATTERN, ICD10_RE, find_dates, npi_valid, ocr_fix_digits, parse_date,
)
from authops.docintel.ocr import OCRDoc
from authops.schemas import SCHEMA_FOR, DocType, Extraction, FieldValue

ABSTAIN_BELOW = 0.55


def classify_doc(text: str) -> DocType:
    t = text.lower()
    if "treatment plan" in t:
        return DocType.TREATMENT_PLAN
    if "referral" in t and "determination" not in t:
        return DocType.REFERRAL
    if "denied" in t or "reason for denial" in t:
        return DocType.DENIAL_LETTER
    return DocType.APPROVAL_LETTER


class Extractor(Protocol):
    name: str

    def extract(self, doc_id: str, ocr: OCRDoc, doc_type: DocType,
                pages: list[str] | None = None) -> Extraction: ...


# ---------------------------------------------------------------- rule baseline

LABELS = {
    "auth_number": [r"authorization number", r"reference\s*#", r"auth id"],
    "patient_name": [r"patient name", r"member name", r"patient", r"name"],
    "patient_dob": [r"date of birth", r"birth date", r"dob"],
    "member_id": [r"member id", r"subscriber id", r"member no\.?"],
    "cpt_codes": [r"service codes \(cpt\)", r"requested services \(cpt\)", r"procedure", r"hcpcs/cpt"],
    "approved_units": [r"approved units", r"units authorized", r"qty"],
    "requested_units": [r"requested units"],
    "provider_npi": [r"rendering provider npi", r"provider npi", r"NPI_ANY"],
    "icd10_codes": [r"diagnosis \(icd-10\)", r"diagnosis"],
}
VALUE_AFTER = r"\s*[:#.]*\s*(?:\.{2,}\s*)?(.+)"


def _strip_leader(value: str) -> str:
    """Drop OCR debris left by dot leaders ('....4.4.', 'ee cee eee') before a value."""
    toks = value.split()
    while toks and (("." in toks[0] and len(re.sub(r"[^A-Za-z0-9]", "", toks[0])) <= 2)
                    or re.fullmatch(r"[ceoaw]{1,4}", toks[0])
                    or re.fullmatch(r"[.\-,:'`]+", toks[0])):
        toks.pop(0)
    return " ".join(toks)


def _find_label(lines: list[str], field: str) -> tuple[str | None, str | None]:
    for pat in LABELS[field]:
        # 'NPI' is often glued to the previous token by OCR ('ANPI:'), so no word boundary
        rx = re.compile(r"(?i)npi" + VALUE_AFTER if pat == "NPI_ANY" else r"(?i)\b" + pat + VALUE_AFTER)
        for ln in lines:
            m = rx.search(ln)
            if m:
                return _strip_leader(m.group(1).strip()), ln
    return None, None


def correct_cpt(raw: str) -> tuple[list[str], float]:
    """Map 5-digit tokens to in-scope CPT codes, allowing one OCR substitution."""
    from authops.docintel.normalize import SPECIALTY_CPT

    known = set().union(*SPECIALTY_CPT.values())
    out, penalty = [], 1.0
    for tok in re.findall(r"\b\d{5}\b", ocr_fix_digits(raw)):
        if tok in known:
            out.append(tok)
            continue
        near = [k for k in known if sum(a != b for a, b in zip(k, tok)) == 1]
        if len(near) == 1:
            out.append(near[0])
            penalty = min(penalty, 0.7)  # corrected, so route to QA unless otherwise confident
    return sorted(set(out)), penalty


def _cut(value: str) -> str:
    """Stop a value at the next inline label (e.g. 'Name  DOB: ...')."""
    return re.split(r"\s{2,}|\s(?=(?:DOB|Member ID|Frequency|Date|NPI)\b)", value)[0].strip()


class RuleExtractor:
    name = "rules"

    def extract(self, doc_id, ocr: OCRDoc, doc_type: DocType, pages=None) -> Extraction:
        t0 = time.perf_counter()
        text = ocr.text
        lines = [ln for ln in text.splitlines() if ln.strip()]
        f: dict[str, FieldValue] = {}

        def put(name, value, evidence, validity=1.0):
            if value in (None, "", []):
                f[name] = FieldValue(value=None, confidence=0.0, abstained=True)
                return
            src = " ".join(value) if isinstance(value, list) else value
            if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                # score a date by the tokens OCR actually read, in whichever format the page used
                d = _date.fromisoformat(value)
                for cand in (d.strftime("%m/%d/%Y"), value, f"{d.strftime('%B')} {d.day}, {d.year}"):
                    if all(tok.strip(".,:;").upper() in ocr.word_conf for tok in cand.replace(",", " ").split()):
                        src = cand
                        break
            conf = min(1.0, ocr.conf_for(src)) * validity
            f[name] = FieldValue(value=value, confidence=round(conf, 3), evidence=evidence,
                                 abstained=conf < ABSTAIN_BELOW)

        raw, ev = _find_label(lines, "patient_name")
        name = _cut(raw) if raw else None
        if name and doc_type == DocType.TREATMENT_PLAN:
            name = re.sub(r"(?i)^name\s*:\s*", "", name)
        put("patient_name", name, ev)

        raw, ev = _find_label(lines, "patient_dob")
        dob = find_dates(raw)[0] if raw and find_dates(raw) else None
        put("patient_dob", dob.isoformat() if dob else None, ev)

        raw, ev = _find_label(lines, "member_id")
        member = None
        if raw:
            m2 = re.search(r"([A-Z]{3})([0-9OoIlSB]{8})", raw.replace(" ", ""))
            member = m2.group(1) + ocr_fix_digits(m2.group(2)) if m2 else None
        put("member_id", member, ev)

        raw, ev = _find_label(lines, "cpt_codes")
        cpts, cpt_pen = correct_cpt(raw) if raw else ([], 1.0)
        put("cpt_codes", cpts, ev, validity=cpt_pen)

        raw, ev = _find_label(lines, "provider_npi")
        npi_m = re.search(r"\d{10}", ocr_fix_digits(raw.replace(" ", ""))) if raw else None
        npi = npi_m.group(0) if npi_m else None
        put("provider_npi", npi, ev, validity=1.0 if npi_valid(npi) else 0.4)

        if doc_type == DocType.TREATMENT_PLAN:
            raw, ev = _find_label(lines, "icd10_codes")
            put("icd10_codes", sorted(set(ICD10_RE.findall(raw or ""))), ev)
            raw, ev = _find_label(lines, "requested_units")
            units = re.search(r"\d+", ocr_fix_digits(raw.split()[0])) if raw else None
            put("requested_units", int(units.group(0)) if units else None, ev)
            plan = next((ln for ln in lines if re.search(r"(?i)plan period", ln)), None)
            ds = find_dates(plan or "")
            put("plan_start", ds[0].isoformat() if len(ds) >= 1 else None, plan)
            put("plan_end", ds[1].isoformat() if len(ds) >= 2 else None, plan)
            sig = next((ln for ln in lines if re.search(r"(?i)signature", ln)), None)
            present = bool(sig and re.search(r"/s/|\b[A-Z][a-z]+ [A-Z][a-z]+", sig.split(":", 1)[-1]))
            f["signature_present"] = FieldValue(value=present if sig else None,
                                                confidence=0.9 if sig else 0.0,
                                                evidence=sig, abstained=sig is None)
            sd = find_dates(sig.split("Date", 1)[-1]) if sig and "Date" in sig else []
            put("signature_date", sd[0].isoformat() if sd else None, sig)
        else:
            raw, ev = _find_label(lines, "auth_number")
            auth = raw.split()[0].strip(".") if raw else None
            put("auth_number", auth, ev)
            low = text.lower()
            decision = ("denied" if "denied" in low else "partial" if "partially" in low
                        else "approved" if "approved" in low else None)
            f["decision"] = FieldValue(value=decision, confidence=0.95 if decision else 0.0,
                                       abstained=decision is None)
            raw, ev = _find_label(lines, "approved_units")
            units = re.search(r"\d+", ocr_fix_digits(raw.split()[0])) if raw else None
            put("approved_units", int(units.group(0)) if units else None, ev)
            period = next((ln for ln in lines if re.search(
                r"(?i)effective dates|authorization period", ln)), None)
            ds = find_dates(period or "")
            if not ds:  # template c: FROM / TO on separate lines
                frm = next((ln for ln in lines if re.match(r"(?i)from\b", ln)), "")
                to = next((ln for ln in lines if re.match(r"(?i)to\b", ln)), "")
                ds = find_dates(frm) + find_dates(to)
                period = f"{frm} | {to}" if ds else period
            put("start_date", ds[0].isoformat() if len(ds) >= 1 else None, period)
            put("end_date", ds[1].isoformat() if len(ds) >= 2 else None, period)
            if decision == "denied":
                m = re.search(r"(?is)reason for denial:\s*(.+?)(?:\n\n|You may)", text)
                put("denial_reason", " ".join(m.group(1).split()) if m else None, None)

        return Extraction(doc_id=doc_id, doc_type=doc_type, extractor=self.name, fields=f,
                          ocr_mean_conf=round(ocr.mean_conf, 1),
                          latency_ms=(time.perf_counter() - t0) * 1000 + ocr.latency_ms)


# ---------------------------------------------------------------- Claude extractor

EXTRACT_PROMPT = """Extract fields from this {doc_type} for a prior authorization workflow.

Return ONLY a JSON object. For each field give an object:
  {{"value": <value or null>, "evidence": "<exact substring copied from the document>", "confidence": 0.0-1.0}}
Use null when the field is absent or unreadable. Never guess. Dates as YYYY-MM-DD.
Names as "First Last". Code lists as JSON arrays of strings.

Fields and types:
{schema}

Document text (from OCR, may contain errors):
<<<
{text}
>>>"""

SYNTH_PROMPT = """Several extractions were made from different chunks of the same {doc_type}.
Merge them into one JSON object with the same per-field shape. Prefer values with evidence;
if chunks disagree, keep the higher-confidence value and lower its confidence to at most 0.5.

Chunk extractions:
{chunks}"""


def _schema_desc(doc_type: DocType) -> str:
    model = SCHEMA_FOR[doc_type]
    return "\n".join(f"- {k}: {v.annotation}".replace("typing.", "")
                     for k, v in model.model_fields.items())


def chunk_text(text: str, max_chars: int = 2500, overlap: int = 200) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + max_chars])
        i += max_chars - overlap
    return out


class ClaudeExtractor:
    def __init__(self, llm, use_images: bool = False):
        self.llm = llm
        self.use_images = use_images
        self.name = f"claude:{llm.model}{':vision' if use_images else ''}"

    def _call(self, doc_type, text, pages):
        r = self.llm.complete(EXTRACT_PROMPT.format(doc_type=doc_type.value.replace("_", " "),
                                                    schema=_schema_desc(doc_type), text=text),
                              images=pages if self.use_images else None, max_tokens=1500)
        return r, _parse(r.text)

    def extract(self, doc_id, ocr: OCRDoc, doc_type: DocType, pages=None) -> Extraction:
        from authops.llm import parse_json  # noqa: F401  (kept for readers)

        t0 = time.perf_counter()
        tin = tout = 0
        chunks = chunk_text(ocr.text)
        if len(chunks) == 1 or self.use_images:
            r, raw = self._call(doc_type, ocr.text, pages)
            tin, tout = r.tokens_in, r.tokens_out
        else:
            with ThreadPoolExecutor(max_workers=4) as ex:
                parts = list(ex.map(lambda c: self._call(doc_type, c, None), chunks))
            tin = sum(p[0].tokens_in for p in parts)
            tout = sum(p[0].tokens_out for p in parts)
            r = self.llm.complete(SYNTH_PROMPT.format(
                doc_type=doc_type.value, chunks=json.dumps([p[1] for p in parts], default=str)),
                max_tokens=1500)
            tin, tout = tin + r.tokens_in, tout + r.tokens_out
            raw = _parse(r.text)

        fields: dict[str, FieldValue] = {}
        norm_text = re.sub(r"\s+", " ", ocr.text).lower()
        for name in SCHEMA_FOR[doc_type].model_fields:
            item = raw.get(name) if isinstance(raw, dict) else None
            if not isinstance(item, dict):
                item = {"value": item, "confidence": 0.5 if item is not None else 0.0}
            value = item.get("value")
            conf = float(item.get("confidence") or 0.0)
            evidence = item.get("evidence")
            # groundedness: evidence must appear in what OCR actually read
            if value is not None and evidence:
                if re.sub(r"\s+", " ", str(evidence)).lower()[:40] not in norm_text:
                    conf = min(conf, 0.5)
            if name.endswith(("dob", "date", "start", "end")) and value:
                d = parse_date(str(value))
                value = d.isoformat() if d else None
            if name == "provider_npi" and value and not npi_valid(str(value)):
                conf = min(conf, 0.4)
            fields[name] = FieldValue(value=value, confidence=round(conf, 3), evidence=evidence,
                                      abstained=value is None or conf < ABSTAIN_BELOW)
        return Extraction(doc_id=doc_id, doc_type=doc_type, extractor=self.name, fields=fields,
                          ocr_mean_conf=round(ocr.mean_conf, 1), tokens_in=tin, tokens_out=tout,
                          latency_ms=(time.perf_counter() - t0) * 1000 + ocr.latency_ms)


def _parse(text: str) -> dict:
    from authops.llm import parse_json

    out = parse_json(text)
    return out if isinstance(out, dict) else {}


__all__ = ["RuleExtractor", "ClaudeExtractor", "classify_doc", "chunk_text", "DATE_PATTERN"]
