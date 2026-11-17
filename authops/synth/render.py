"""Render synthetic cases into document images with ground truth.

Three payor letter templates (different labels, date formats and layouts) and three
image conditions (clean, scanned, fax) so extraction is tested against the variation
a real prior-auth inbox has. Each document is saved as PNG pages plus a PDF, with a
ground-truth JSON next to it.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from authops.schemas import Case, DocType
from authops.synth.generate import PAYOR_BY_ID, payor_decision

PAGE_W, PAGE_H = 1700, 2200  # ~200 dpi letter
MARGIN = 120

FONT_DIR = Path(__file__).resolve().parent / "fonts"
# Bundled fonts first: rendering must be identical across machines or OCR numbers drift.
FONT_CANDIDATES = [
    str(FONT_DIR / "DejaVuSans.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arial.ttf",
]
MONO_CANDIDATES = [
    str(FONT_DIR / "DejaVuSansMono.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]


def _font(size: int, mono: bool = False) -> ImageFont.FreeTypeFont:
    for path in (MONO_CANDIDATES if mono else FONT_CANDIDATES):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def fmt_date(d: date | None, template: str) -> str:
    if d is None:
        return "__________"
    if template == "a":
        return d.strftime("%m/%d/%Y")
    if template == "b":
        return f"{d.strftime('%B')} {d.day}, {d.year}"
    return d.isoformat()


@dataclass
class Page:
    img: Image.Image
    draw: ImageDraw.ImageDraw
    y: int = MARGIN


class DocWriter:
    def __init__(self, mono: bool = False):
        self.pages: list[Page] = []
        self.body = _font(34, mono)
        self.bold = _font(40, mono)
        self.title = _font(54, mono)
        self.new_page()

    def new_page(self) -> None:
        img = Image.new("L", (PAGE_W, PAGE_H), 255)
        self.pages.append(Page(img, ImageDraw.Draw(img)))

    @property
    def p(self) -> Page:
        return self.pages[-1]

    def line(self, text: str, font=None, gap: int = 14, x: int = MARGIN) -> None:
        font = font or self.body
        h = font.getbbox("Ag")[3] + gap
        if self.p.y + h > PAGE_H - MARGIN:
            self.new_page()
        self.p.draw.text((x, self.p.y), text, fill=0, font=font)
        self.p.y += h

    def para(self, text: str, width_chars: int = 78) -> None:
        words, cur = text.split(), ""
        for w in words:
            if len(cur) + len(w) + 1 > width_chars:
                self.line(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            self.line(cur)
        self.space(10)

    def space(self, px: int = 24) -> None:
        self.p.y += px

    def rule(self) -> None:
        self.p.draw.line((MARGIN, self.p.y, PAGE_W - MARGIN, self.p.y), fill=0, width=3)
        self.p.y += 20

    def signature(self, present: bool, rng: random.Random) -> None:
        if not present:
            return
        x0, y0 = MARGIN + 420, self.p.y - 70
        pts = [(x0 + i * 18, y0 + int(22 * rng.uniform(-1, 1))) for i in range(18)]
        self.p.draw.line(pts, fill=0, width=4)


NARRATIVE = [
    "Clinical history: The patient was evaluated at intake with a standardized assessment. "
    "Caregiver interview and direct observation were completed across two sessions.",
    "Functional limitations were observed in daily routines, including transitions, "
    "task initiation and sustained participation. Baseline data were collected over ten sessions.",
    "Goals target measurable improvement over the authorization period. Each goal has a "
    "baseline, a mastery criterion and a review date. Progress is reviewed every thirty days.",
    "Medical necessity: Without the requested services the patient is expected to regress. "
    "The requested intensity is consistent with published practice guidelines for this condition.",
    "Coordination of care: The plan was shared with the primary care physician and the family. "
    "Discharge criteria are documented and will be revisited at each reauthorization.",
]


def render_treatment_plan(case: Case, rng: random.Random, long: bool) -> DocWriter:
    w = DocWriter()
    w.line(case.provider.practice, w.title)
    w.line("Individualized Treatment Plan", w.bold)
    w.rule()
    t = "a"
    w.line(f"Patient Name: {case.patient.full_name}")
    w.line(f"Date of Birth: {fmt_date(case.patient.dob, t)}")
    w.line(f"Insurance: {case.payor.name}    Member ID: {case.patient.member_id}")
    w.line(f"Diagnosis (ICD-10): {', '.join(case.icd10_codes)}")
    w.line(f"Requested Services (CPT): {', '.join(case.cpt_codes)}")
    w.line(f"Requested Units: {case.requested_units}    Frequency: {case.frequency}")
    w.line(f"Plan Period: {fmt_date(case.start_date, t)} to {fmt_date(case.end_date, t)}")
    w.space()
    for para in (NARRATIVE * (3 if long else 1)):
        w.para(para)
    w.space(40)
    w.line(f"Rendering Provider: {case.provider.name}    NPI: {case.provider.npi}")
    sig = (f"/s/ {case.provider.name}" if case.signature_present else "____________________")
    w.line(f"Provider Signature: {sig}    Date: {fmt_date(case.signature_date, t)}")
    w.signature(case.signature_present, rng)
    return w


def render_referral(case: Case, rng: random.Random) -> DocWriter:
    w = DocWriter()
    w.line("Physician Referral", w.title)
    w.rule()
    w.line(f"Patient: {case.patient.full_name}    DOB: {fmt_date(case.patient.dob, 'a')}")
    w.line(f"Diagnosis: {', '.join(case.icd10_codes)}")
    w.line(f"Referred to: {case.provider.practice}")
    ref_npi = case.provider.npi[::-1]
    w.line(f"Referring Physician NPI: {ref_npi}")
    w.line(f"Referral Date: {fmt_date(case.signature_date, 'a')}")
    w.space()
    w.para("Please evaluate and treat. Records from the most recent visit are attached.")
    return w


def make_auth_number(case: Case, rng: random.Random) -> str:
    t = case.payor.letter_template
    if t == "a":
        return f"{case.payor.payor_id}-A-{rng.randint(100000, 999999)}"
    if t == "b":
        return f"R{rng.randint(10_000_000, 99_999_999)}"
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789O0I1"  # O/0 and I/1 on purpose
    return "".join(rng.choice(alphabet) for _ in range(10))


def render_letter(case: Case, rng: random.Random) -> tuple[DocWriter, dict, DocType]:
    payor = PAYOR_BY_ID[case.payor.payor_id]
    t = payor.letter_template
    decision, units, reason = payor_decision(case, rng)
    auth = make_auth_number(case, rng)
    dtype = DocType.DENIAL_LETTER if decision == "denied" else DocType.APPROVAL_LETTER
    w = DocWriter(mono=(t == "c"))
    w.line(payor.name, w.title)
    w.line("Utilization Management Department", w.bold)
    w.rule()
    head = {"approved": "APPROVED", "partial": "PARTIALLY APPROVED", "denied": "DENIED"}[decision]
    if t == "a":
        w.line(f"Notice of Prior Authorization Determination: {head}", w.bold)
        w.space()
        w.line(f"Authorization Number: {auth}")
        w.line(f"Patient: {case.patient.full_name}")
        w.line(f"Date of Birth: {fmt_date(case.patient.dob, t)}")
        w.line(f"Member ID: {case.patient.member_id}")
        w.line(f"Service Codes (CPT): {', '.join(case.cpt_codes)}")
        if decision != "denied":
            w.line(f"Approved Units: {units}")
            w.line(f"Effective Dates: {fmt_date(case.start_date, t)} through {fmt_date(case.end_date, t)}")
        w.line(f"Rendering Provider NPI: {case.provider.npi}")
    elif t == "b":
        w.line(f"Dear {case.provider.name},", w.body)
        w.space(10)
        w.para(f"We have completed our review of the request for {case.patient.full_name}. "
               f"The determination is: {head}.")
        w.line(f"Reference # {auth}")
        w.line(f"Member Name: {case.patient.full_name}    DOB: {fmt_date(case.patient.dob, t)}")
        w.line(f"Subscriber ID: {case.patient.member_id}")
        w.line(f"Procedure: {' / '.join(case.cpt_codes)}")
        if decision != "denied":
            w.line(f"Units Authorized: {units}")
            w.line(f"Authorization Period: {fmt_date(case.start_date, t)} - {fmt_date(case.end_date, t)}")
        w.line(f"Provider NPI: {case.provider.npi}")
    else:
        w.line(f"DETERMINATION ......... {head}", w.bold)
        w.space()
        w.line(f"AUTH ID ............... {auth}")
        w.line(f"NAME .................. {case.patient.last_name.upper()}, {case.patient.first_name.upper()}")
        w.line(f"BIRTH DATE ............ {fmt_date(case.patient.dob, t)}")
        w.line(f"MEMBER NO. ............ {case.patient.member_id}")
        w.line(f"HCPCS/CPT ............. {' '.join(case.cpt_codes)}")
        if decision != "denied":
            w.line(f"QTY ................... {units}")
            w.line(f"FROM .................. {fmt_date(case.start_date, t)}")
            w.line(f"TO .................... {fmt_date(case.end_date, t)}")
        w.line(f"NPI ................... {case.provider.npi}")
    if decision == "denied":
        w.space()
        w.line("Reason for denial:", w.bold)
        w.para(reason or "")
        w.para("You may submit additional documentation or request a peer-to-peer review "
               "within 30 days of this notice.")
    w.space()
    w.para("This determination is not a guarantee of payment. Benefits are subject to "
           "eligibility on the date of service.")
    truth = {
        "auth_number": auth, "decision": decision, "patient_name": case.patient.full_name,
        "patient_dob": case.patient.dob.isoformat(), "member_id": case.patient.member_id,
        "cpt_codes": case.cpt_codes, "approved_units": units if decision != "denied" else None,
        "start_date": case.start_date.isoformat() if decision != "denied" else None,
        "end_date": case.end_date.isoformat() if decision != "denied" else None,
        "provider_npi": case.provider.npi, "denial_reason": reason,
    }
    return w, truth, dtype


# ---- image degradation ----------------------------------------------------

def degrade(img: Image.Image, condition: str, rng: random.Random) -> Image.Image:
    if condition == "clean":
        return img
    if condition == "scan":
        out = img.rotate(rng.uniform(-1.5, 1.5), expand=False, fillcolor=255)
        out = out.filter(ImageFilter.GaussianBlur(0.9))
        px = out.load()
        for _ in range(4000):
            x, y = rng.randrange(PAGE_W), rng.randrange(PAGE_H)
            px[x, y] = rng.randint(120, 255)
        return out
    if condition == "fax":
        small = img.rotate(rng.uniform(-2.5, 2.5), fillcolor=255).resize((PAGE_W // 2, PAGE_H // 2))
        small = small.filter(ImageFilter.GaussianBlur(0.6)).point(lambda v: 0 if v < 150 else 255)
        px = small.load()
        for _ in range(2500):
            px[rng.randrange(PAGE_W // 2), rng.randrange(PAGE_H // 2)] = 0
        return small.resize((PAGE_W, PAGE_H), Image.NEAREST)
    raise ValueError(condition)


def save_doc(w: DocWriter, out_dir: Path, doc_id: str, condition: str, rng: random.Random) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = [degrade(p.img, condition, rng) for p in w.pages]
    paths = []
    for i, pg in enumerate(pages):
        path = out_dir / f"{doc_id}_p{i + 1}.png"
        pg.save(path)
        paths.append(str(path))
    pages[0].save(out_dir / f"{doc_id}.pdf", save_all=True, append_images=pages[1:])
    return paths


def render_corpus(cases: list[Case], out_dir: Path, seed: int = 11,
                  conditions=("clean", "scan", "fax")) -> list[dict]:
    """Render every case's documents. Returns a manifest with ground truth."""
    rng = random.Random(seed)
    manifest = []
    for i, case in enumerate(cases):
        cond = conditions[i % len(conditions)]
        long = i % 4 == 0
        tp = render_treatment_plan(case, rng, long)
        tp_truth = {
            "patient_name": case.patient.full_name, "patient_dob": case.patient.dob.isoformat(),
            "member_id": case.patient.member_id, "icd10_codes": case.icd10_codes,
            "cpt_codes": case.cpt_codes, "requested_units": case.requested_units,
            "plan_start": case.start_date.isoformat(), "plan_end": case.end_date.isoformat(),
            "provider_npi": case.provider.npi, "signature_present": case.signature_present,
            "signature_date": case.signature_date.isoformat() if case.signature_date else None,
        }
        letter, l_truth, l_type = render_letter(case, rng)
        for doc_type, writer, truth in [(DocType.TREATMENT_PLAN, tp, tp_truth),
                                        (l_type, letter, l_truth)]:
            doc_id = f"{case.case_id}_{doc_type.value}"
            pages = save_doc(writer, out_dir / "docs", doc_id, cond, rng)
            manifest.append({"doc_id": doc_id, "case_id": case.case_id, "doc_type": doc_type.value,
                             "payor_id": case.payor.payor_id, "template": case.payor.letter_template
                             if doc_type != DocType.TREATMENT_PLAN else "tp",
                             "condition": cond, "n_pages": len(pages), "pages": pages, "truth": truth})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (out_dir / "cases.json").write_text(json.dumps([c.model_dump(mode="json") for c in cases], indent=1))
    return manifest
