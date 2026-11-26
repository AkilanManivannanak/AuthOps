"""Channel router: FHIR API first, portal agent second, phone agent third.

CMS-0057-F requires impacted payors to run a FHIR Prior Authorization API by
January 1, 2027. Coverage will be uneven for years (commercial plans outside the
rule, payors that ship late, services like drugs that are out of scope), so the
durable design is a router: use the structured API where it exists, fall back to the
browser agent, and to the phone agent where there is neither.

`build_pas_bundle` emits a FHIR R4 Bundle (valid against the base spec) in the shape of
Da Vinci PAS: a Claim with use=preauthorization and its Patient, Coverage, payor and
provider. It is not validated against the PAS profiles themselves.
"""
from __future__ import annotations

import time
import uuid

import httpx


def _uid(case: dict, kind: str) -> str:
    """Stable urn:uuid per case and resource, so the same request always gives the same bundle."""
    return "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"authops/{case.get('case_id', '')}/{kind}"))


def build_pas_bundle(case: dict, now: str | None = None) -> dict:
    """A FHIR R4 Bundle that validates against the base spec (checked with fhir.resources in the tests):
    Claim (use=preauthorization) with patient, provider, insurer and insurance all pointing at resources in
    the bundle, plus Patient, Coverage, the payor Organization and the Practitioner. It follows the shape of
    Da Vinci PAS but is not validated against the PAS profiles."""
    p, prov, pay = case["patient"], case["provider"], case["payor"]
    pid, cid, oid, prid, clid = (_uid(case, k) for k in ("patient", "coverage", "payor", "provider", "claim"))
    now = now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    member = {"system": f"urn:payor:{pay['payor_id']}:member", "value": p["member_id"]}
    claim = {
        "resourceType": "Claim", "status": "active", "use": "preauthorization",
        "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type", "code": "professional"}]},
        "patient": {"reference": pid}, "created": now[:10],
        "insurer": {"reference": oid}, "provider": {"reference": prid},
        "priority": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/processpriority", "code": "normal"}]},
        "insurance": [{"sequence": 1, "focal": True, "coverage": {"reference": cid}}],
        "diagnosis": [{"sequence": i + 1, "diagnosisCodeableConcept": {"coding": [
            {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": d}]}}
            for i, d in enumerate(case["icd10_codes"])],
        "item": [{"sequence": i + 1, "productOrService": {"coding": [
            {"system": "http://www.ama-assn.org/go/cpt", "code": c}]},
            "quantity": {"value": case["requested_units"]},
            "servicedPeriod": {"start": case["start_date"], "end": case["end_date"]}}
            for i, c in enumerate(case["cpt_codes"])],
    }
    patient = {"resourceType": "Patient", "identifier": [member],
               "name": [{"family": p["last_name"], "given": [p["first_name"]]}], "birthDate": str(p["dob"])}
    coverage = {"resourceType": "Coverage", "status": "active", "subscriberId": p["member_id"],
                "beneficiary": {"reference": pid}, "payor": [{"reference": oid}]}
    payor = {"resourceType": "Organization", "identifier": [{"system": "urn:authops:payor", "value": pay["payor_id"]}],
             "name": pay["name"]}
    practitioner = {"resourceType": "Practitioner",
                    "identifier": [{"system": "http://hl7.org/fhir/sid/us-npi", "value": prov["npi"]}]}
    if prov.get("last_name") or prov.get("name"):
        practitioner["name"] = [{"family": prov.get("last_name") or prov.get("name"),
                                 **({"given": [prov["first_name"]]} if prov.get("first_name") else {})}]
    entries = [(clid, claim), (pid, patient), (cid, coverage), (oid, payor), (prid, practitioner)]
    return {"resourceType": "Bundle", "type": "collection", "timestamp": now,
            "identifier": {"system": "urn:authops:request", "value": str(case.get("case_id", ""))},
            "entry": [{"fullUrl": u, "resource": r} for u, r in entries]}


def submit_fhir(base_url: str, case: dict, retries: int = 2, client=None) -> dict:
    """Send the bundle. Never raises on a bad answer: a gateway error page or a timeout becomes needs_human
    with an error class, after retrying 502/503/504 and timeouts with a short backoff."""
    t0 = time.perf_counter()
    post = (client or httpx).post
    r, err = None, ""
    for attempt in range(retries + 1):
        try:
            r = post(f"{base_url}/fhir/Claim/$submit", json=build_pas_bundle(case), timeout=10)
            err = ""
            if r.status_code not in (502, 503, 504):
                break
        except httpx.HTTPError as e:
            r, err = None, "fhir_" + type(e).__name__.lower()
        if attempt < retries:
            time.sleep(0.5 * (2 ** attempt))
    try:
        body = r.json() if r is not None else {}
    except ValueError:
        body = {}
    ok = r is not None and r.status_code == 200 and body.get("resourceType") == "ClaimResponse"
    return {"status": "submitted" if ok else "needs_human", "ref": body.get("preAuthRef"),
            "http": r.status_code if r is not None else None, "duration_s": round(time.perf_counter() - t0, 3),
            "error_class": "" if ok else (err or "fhir_" + str(r.status_code if r is not None else "error"))}


def choose_channel(case: dict, requirements: dict) -> str:
    """The payor's channel from the requirements file; a payor not in the file goes to the browser agent."""
    return requirements.get("payors", {}).get(case["payor"]["payor_id"], {}).get("channel", "portal")
