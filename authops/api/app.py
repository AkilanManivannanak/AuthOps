"""External API: how a customer's EHR or scheduling system talks to AuthOps.

Silna's engineering listing mentions building an external-facing API. This one covers the
loop a clinic integration needs:

  POST /v1/authorizations              create a request; validation runs before anything is sent
  GET  /v1/authorizations/{id}         status, issues, channel, payor decision
  POST /v1/authorizations/{id}/events  payor updates (approved, denied, info requested, P2P)
  GET  /v1/cases                       clinician work queue (opened by payor requests)
  POST /v1/cases/{id}/respond          clinician answers a payor request
  POST /v1/benefit-estimates           patient cost for the next N visits
  POST /v1/auth-forecast               when to start the reauthorization
  POST /v1/webhooks                    subscribe to events; deliveries are HMAC-SHA256 signed

API keys come from AUTHOPS_API_KEYS (comma separated); "demo-key" works when unset.
POST /v1/authorizations honors an Idempotency-Key header so EHR retries never create
duplicates. Storage is in memory: this is the contract and the behavior, not a database.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from authops.benefits.calls import estimate
from authops.cases.manager import REQUEST_TYPES, CaseManager
from authops.monitor.panel import forecast
from authops.schemas import Case, Patient, Provider
from authops.synth.generate import PAYOR_BY_ID
from authops.validation.rules import validate_case


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuthIn(BaseModel):
    patient_first: str
    patient_last: str
    dob: date
    member_id: str
    payor_id: str
    specialty: Literal["aba", "physical_therapy", "behavioral_health"]
    icd10_codes: list[str]
    cpt_codes: list[str]
    units: int = Field(gt=0)
    frequency: str = "weekly"
    start_date: date
    end_date: date
    provider_name: str
    provider_npi: str
    practice: str = "Practice"
    tax_id: str = "00-0000000"
    signature_date: Optional[date] = None


class EventIn(BaseModel):
    type: Literal["approved", "partially_approved", "denied", "peer_to_peer", "additional_info",
                  "medical_records", "signature_correction"]
    units_approved: Optional[int] = None
    note: str = ""


class RespondIn(BaseModel):
    response: str


class EstimateIn(BaseModel):
    plan_active: bool = True
    in_network: bool = True
    deductible: int = 0
    deductible_met: int = 0
    coinsurance_pct: int = 0
    copay: int = 0
    oop_max: int = 0
    oop_met: int = 0
    visit_limit: Optional[int] = None
    visits_used: int = 0
    carve_out_vendor: Optional[str] = None
    allowed_per_visit: float = Field(gt=0)
    visits: int = Field(gt=0, le=520)


class ForecastIn(BaseModel):
    units_left: int
    weekly_units: float
    days_left: int
    payor_p90_business_days: int = 12
    buffer_days: int = 7


class WebhookIn(BaseModel):
    url: str
    events: list[str] = ["*"]


def create_app(today: date | None = None, sender=None) -> FastAPI:
    app = FastAPI(title="AuthOps external API", version="1.0")
    keys = {k.strip() for k in os.environ.get("AUTHOPS_API_KEYS", "demo-key").split(",") if k.strip()}
    store: dict[str, dict] = {}
    idem: dict[tuple[str, str], str] = {}
    hooks: dict[str, dict] = {}
    deliveries: list[dict] = []
    send = sender or (lambda url, body, headers: None)

    def emit(kind: str, payload: dict) -> None:
        for h in hooks.values():
            if "*" in h["events"] or kind in h["events"]:
                body = json.dumps({"event": kind, "data": payload, "sent_at": _utcnow().isoformat()},
                                  default=str, sort_keys=True)
                sig = hmac.new(h["secret"].encode(), body.encode(), hashlib.sha256).hexdigest()
                headers = {"X-AuthOps-Event": kind, "X-AuthOps-Signature": f"sha256={sig}"}
                deliveries.append({"hook": h["id"], "event": kind, "signature": headers["X-AuthOps-Signature"],
                                   "body": body})
                send(h["url"], body, headers)

    cases = CaseManager(on_event=emit)
    app.state.store, app.state.cases, app.state.deliveries, app.state.hooks = store, cases, deliveries, hooks

    def auth(x_api_key: str = Header(default="")) -> str:
        if x_api_key not in keys:
            raise HTTPException(401, "invalid API key")
        return x_api_key

    @app.get("/v1/health")
    def health():
        return {"ok": True}

    @app.post("/v1/authorizations", status_code=201)
    def create_auth(body: AuthIn, key: str = Depends(auth), idempotency_key: str = Header(default="")):
        if idempotency_key and (key, idempotency_key) in idem:
            return store[idem[(key, idempotency_key)]]
        payor = PAYOR_BY_ID.get(body.payor_id)
        if not payor:
            raise HTTPException(422, f"unknown payor {body.payor_id}")
        aid = "AU-" + uuid.uuid4().hex[:10]
        case = Case(case_id=aid, specialty=body.specialty, payor=payor,
                    patient=Patient(patient_id="EXT", first_name=body.patient_first, last_name=body.patient_last,
                                    dob=body.dob, member_id=body.member_id),
                    provider=Provider(name=body.provider_name, npi=body.provider_npi, practice=body.practice,
                                      tax_id=body.tax_id),
                    icd10_codes=body.icd10_codes, cpt_codes=body.cpt_codes, requested_units=body.units,
                    frequency=body.frequency, start_date=body.start_date, end_date=body.end_date,
                    signature_present=body.signature_date is not None, signature_date=body.signature_date)
        rep = validate_case(case, today or date.today(), include_custom=False)
        rec = {"id": aid, "status": "ready_to_submit" if rep.ready else "needs_fixes",
               "channel": payor.channel, "payor": payor.name, "specialty": body.specialty,
               "issues": [{"rule": r.rule, "fix": r.message} for r in rep.blocking],
               "needs_human": [r.rule for r in rep.needs_human], "decision": None, "units_approved": None,
               "open_cases": [], "created_at": _utcnow().isoformat()}
        store[aid] = rec
        if idempotency_key:
            idem[(key, idempotency_key)] = aid
        emit("authorization.created", rec)
        return rec

    @app.get("/v1/authorizations/{aid}")
    def get_auth(aid: str, key: str = Depends(auth)):
        if aid not in store:
            raise HTTPException(404, "not found")
        return store[aid]

    @app.post("/v1/authorizations/{aid}/events")
    def payor_event(aid: str, ev: EventIn, key: str = Depends(auth)):
        rec = store.get(aid)
        if not rec:
            raise HTTPException(404, "not found")
        now = _utcnow()
        if ev.type in REQUEST_TYPES:
            c = cases.open(aid, ev.type, rec["specialty"], aid, now, owner=None)
            rec["status"] = "action_required"
            rec["open_cases"].append(c.case_id)
            return {"authorization": rec, "case": c.as_dict(now)}
        rec["decision"] = ev.type
        rec["units_approved"] = ev.units_approved
        rec["status"] = {"approved": "approved", "partially_approved": "partially_approved", "denied": "denied"}[ev.type]
        emit(f"authorization.{ev.type}", rec)
        return {"authorization": rec}

    @app.get("/v1/cases")
    def list_cases(key: str = Depends(auth)):
        now = _utcnow()
        cases.tick(now)
        return {"queue": cases.queue(now), "stats": cases.stats()}

    @app.post("/v1/cases/{cid}/respond")
    def respond(cid: str, body: RespondIn, key: str = Depends(auth)):
        if cid not in cases.cases:
            raise HTTPException(404, "not found")
        try:
            c = cases.respond(cid, body.response, _utcnow())
        except ValueError as e:
            raise HTTPException(409, str(e))
        rec = store.get(c.auth_id)
        if rec and all(cases.cases[x].state in ("responded", "closed") for x in rec["open_cases"]):
            rec["status"] = "pending_payor"
        return c.as_dict()

    @app.post("/v1/benefit-estimates")
    def benefit_estimate(body: EstimateIn, key: str = Depends(auth)):
        b = body.model_dump()
        allowed, visits = b.pop("allowed_per_visit"), b.pop("visits")
        return estimate(b, allowed, visits)

    @app.post("/v1/auth-forecast")
    def auth_forecast(body: ForecastIn, key: str = Depends(auth)):
        return forecast(body.units_left, body.weekly_units, body.days_left, body.payor_p90_business_days,
                        body.buffer_days)

    @app.post("/v1/webhooks", status_code=201)
    def add_hook(body: WebhookIn, key: str = Depends(auth)):
        hid = "WH-" + uuid.uuid4().hex[:8]
        secret = uuid.uuid4().hex
        hooks[hid] = {"id": hid, "url": body.url, "events": body.events, "secret": secret}
        return {"id": hid, "secret": secret, "events": body.events}

    return app


def verify_signature(secret: str, body: str, header: str) -> bool:
    """What a customer runs on their side to trust a webhook."""
    want = "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header)


app = create_app()
