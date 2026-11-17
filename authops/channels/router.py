"""Channel router: FHIR API first, portal agent second, phone agent third.

CMS-0057-F requires impacted payors to run a FHIR Prior Authorization API by
January 1, 2027. Coverage will be uneven for years (commercial plans outside the
rule, payors that ship late, services like drugs that are out of scope), so the
durable design is a router: use the structured API where it exists, fall back to the
browser agent, and to the phone agent where there is neither.

`build_pas_bundle` emits a Da Vinci PAS shaped Bundle: a Claim with
use=preauthorization, the patient, the provider, diagnoses and service lines. It is
a teaching subset of the IG, not a conformant implementation.
"""
from __future__ import annotations

import time
import uuid

import httpx


def build_pas_bundle(case: dict) -> dict:
    p, prov = case["patient"], case["provider"]
    claim = {
        "resourceType": "Claim", "status": "active", "use": "preauthorization",
        "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type",
                             "code": "professional"}]},
        "patient": {"identifier": {"system": f"urn:payor:{case['payor']['payor_id']}:member",
                                   "value": p["member_id"]},
                    "display": f"{p['first_name']} {p['last_name']}"},
        "provider": {"identifier": {"system": "http://hl7.org/fhir/sid/us-npi", "value": prov["npi"]}},
        "priority": {"coding": [{"code": "normal"}]},
        "created": time.strftime("%Y-%m-%d"),
        "diagnosis": [{"sequence": i + 1, "diagnosisCodeableConcept": {"coding": [
            {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": d}]}}
            for i, d in enumerate(case["icd10_codes"])],
        "item": [{"sequence": i + 1, "productOrService": {"coding": [
            {"system": "http://www.ama-assn.org/go/cpt", "code": c}]},
            "quantity": {"value": case["requested_units"]},
            "servicedPeriod": {"start": case["start_date"], "end": case["end_date"]}}
            for i, c in enumerate(case["cpt_codes"])],
    }
    patient = {"resourceType": "Patient", "identifier": [{"value": p["member_id"]}],
               "name": [{"family": p["last_name"], "given": [p["first_name"]]}], "birthDate": p["dob"]}
    return {"resourceType": "Bundle", "type": "collection", "id": uuid.uuid4().hex,
            "entry": [{"resource": claim}, {"resource": patient}]}


def submit_fhir(base_url: str, case: dict) -> dict:
    t0 = time.perf_counter()
    r = httpx.post(f"{base_url}/fhir/Claim/$submit", json=build_pas_bundle(case), timeout=10)
    body = r.json()
    ok = r.status_code == 200 and body.get("resourceType") == "ClaimResponse"
    return {"status": "submitted" if ok else "needs_human", "ref": body.get("preAuthRef"),
            "http": r.status_code, "duration_s": round(time.perf_counter() - t0, 3),
            "error_class": "" if ok else "fhir_" + str(r.status_code)}


def choose_channel(case: dict, requirements: dict) -> str:
    return requirements["payors"][case["payor"]["payor_id"]].get("channel", "portal")
