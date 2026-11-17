"""Pydantic schemas shared across the platform.

Every extracted document resolves to one of these typed schemas. Strict types are
also a guard: an LLM answer that does not validate never reaches a rule or a portal.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DocType(str, Enum):
    TREATMENT_PLAN = "treatment_plan"
    REFERRAL = "referral"
    APPROVAL_LETTER = "approval_letter"
    DENIAL_LETTER = "denial_letter"


class Decision(str, Enum):
    APPROVED = "approved"
    PARTIAL = "partial"
    DENIED = "denied"


class Payor(BaseModel):
    payor_id: str
    name: str
    plan_type: str  # commercial | medicaid_mco | federal
    channel: str  # portal | fhir | phone
    portal_id: Optional[str] = None
    letter_template: str = "a"


class Patient(BaseModel):
    patient_id: str
    first_name: str
    last_name: str
    dob: date
    member_id: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Provider(BaseModel):
    name: str
    npi: str
    practice: str
    tax_id: str


class Case(BaseModel):
    """One prior authorization request: the unit of work an agent completes."""

    case_id: str
    patient: Patient
    provider: Provider
    payor: Payor
    specialty: str
    icd10_codes: list[str]
    cpt_codes: list[str]
    requested_units: int
    frequency: str
    start_date: date
    end_date: date
    signature_present: bool = True
    signature_date: Optional[date] = None
    school_schedule_attached: bool = False
    injected_gaps: list[str] = Field(default_factory=list)


# ---- extraction targets -------------------------------------------------

class TreatmentPlanFields(BaseModel):
    patient_name: Optional[str] = None
    patient_dob: Optional[date] = None
    member_id: Optional[str] = None
    icd10_codes: list[str] = Field(default_factory=list)
    cpt_codes: list[str] = Field(default_factory=list)
    requested_units: Optional[int] = None
    plan_start: Optional[date] = None
    plan_end: Optional[date] = None
    provider_npi: Optional[str] = None
    signature_present: Optional[bool] = None
    signature_date: Optional[date] = None


class ReferralFields(BaseModel):
    patient_name: Optional[str] = None
    patient_dob: Optional[date] = None
    icd10_codes: list[str] = Field(default_factory=list)
    referring_npi: Optional[str] = None
    referral_date: Optional[date] = None


class LetterFields(BaseModel):
    """Approval or denial letter returned by the payor."""

    auth_number: Optional[str] = None
    decision: Optional[Decision] = None
    patient_name: Optional[str] = None
    patient_dob: Optional[date] = None
    member_id: Optional[str] = None
    cpt_codes: list[str] = Field(default_factory=list)
    approved_units: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    provider_npi: Optional[str] = None
    denial_reason: Optional[str] = None


SCHEMA_FOR = {
    DocType.TREATMENT_PLAN: TreatmentPlanFields,
    DocType.REFERRAL: ReferralFields,
    DocType.APPROVAL_LETTER: LetterFields,
    DocType.DENIAL_LETTER: LetterFields,
}


class FieldValue(BaseModel):
    value: object = None
    confidence: float = 0.0
    evidence: Optional[str] = None  # quoted span the value came from
    abstained: bool = False


class Extraction(BaseModel):
    doc_id: str
    doc_type: DocType
    extractor: str
    fields: dict[str, FieldValue]
    ocr_mean_conf: Optional[float] = None
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
