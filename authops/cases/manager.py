"""Clinical case management for payor requests that need a clinician.

Silna's engineering listing describes pulling an email-based process into proper case
management: sometimes the payor needs the clinician (more records, a peer-to-peer review,
a corrected signature), and in an inbox those requests get buried. A missed peer-to-peer
window or an unanswered records request ends as a denial.

This is a small state machine with SLA clocks, routing to the clinician who owns the
patient, reminders at 50% and 80% of the window, escalation to the clinic lead, and an
audit trail of every transition.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


REQUEST_TYPES = {  # type -> (SLA hours, who must act, what the payor asked for)
    "peer_to_peer": (48, "rendering clinician", "Schedule and complete a peer-to-peer call with the payor's medical director."),
    "additional_info": (14 * 24, "rendering clinician", "Send the clinical information the payor listed."),
    "medical_records": (10 * 24, "front desk", "Upload the requested session notes and assessments."),
    "signature_correction": (5 * 24, "rendering clinician", "Sign and date the treatment plan and resubmit."),
}
STATES = ("open", "assigned", "awaiting_clinician", "responded", "closed", "expired")
TRANSITIONS = {
    "open": {"assigned", "expired"},
    "assigned": {"awaiting_clinician", "responded", "expired"},
    "awaiting_clinician": {"responded", "expired"},
    "responded": {"closed"},
    "closed": set(), "expired": set(),
}
_ids = itertools.count(1)


@dataclass
class ClinicalCase:
    case_id: str
    auth_id: str
    request_type: str
    opened_at: datetime
    due_at: datetime
    specialty: str
    patient_ref: str
    state: str = "open"
    assignee: str | None = None
    reminders_sent: list[str] = field(default_factory=list)
    escalated: bool = False
    response: str | None = None
    history: list[tuple[str, str, str]] = field(default_factory=list)  # (when, from->to, note)

    def sla_used(self, now: datetime) -> float:
        total = (self.due_at - self.opened_at).total_seconds()
        return min(1.5, max(0.0, (now - self.opened_at).total_seconds() / total))

    def as_dict(self, now: datetime | None = None) -> dict:
        now = now or _utcnow()
        return {"case_id": self.case_id, "auth_id": self.auth_id, "request_type": self.request_type,
                "state": self.state, "assignee": self.assignee, "specialty": self.specialty,
                "patient_ref": self.patient_ref, "opened_at": self.opened_at.isoformat(),
                "due_at": self.due_at.isoformat(), "hours_left": round((self.due_at - now).total_seconds() / 3600, 1),
                "sla_used": round(self.sla_used(now), 2), "reminders_sent": self.reminders_sent,
                "escalated": self.escalated, "action": REQUEST_TYPES[self.request_type][2],
                "history": self.history}


class CaseManager:
    def __init__(self, clinicians: dict[str, list[str]] | None = None, on_event=None):
        # specialty -> clinicians; the patient's own clinician is preferred when known
        self.clinicians = clinicians or {"aba": ["Dana Whitfield, BCBA", "Jon Pryor, BCBA"],
                                         "physical_therapy": ["Samuel Ortiz, DPT"],
                                         "behavioral_health": ["Alicia Moreno, LCSW"]}
        self.cases: dict[str, ClinicalCase] = {}
        self.on_event = on_event or (lambda kind, payload: None)

    def _move(self, c: ClinicalCase, to: str, now: datetime, note: str = "") -> None:
        if to not in TRANSITIONS[c.state]:
            raise ValueError(f"cannot move {c.case_id} from {c.state} to {to}")
        c.history.append((now.isoformat(timespec="minutes"), f"{c.state}->{to}", note))
        c.state = to
        self.on_event(f"case.{to}", c.as_dict(now))

    def open(self, auth_id: str, request_type: str, specialty: str, patient_ref: str, now: datetime,
             owner: str | None = None) -> ClinicalCase:
        if request_type not in REQUEST_TYPES:
            raise ValueError(f"unknown request type {request_type}")
        hours = REQUEST_TYPES[request_type][0]
        c = ClinicalCase(f"CC-{next(_ids):05d}", auth_id, request_type, now, now + timedelta(hours=hours),
                         specialty, patient_ref)
        c.history.append((now.isoformat(timespec="minutes"), "->open", f"payor requested {request_type}"))
        self.cases[c.case_id] = c
        self.on_event("case.open", c.as_dict(now))
        self.assign(c, now, owner)
        return c

    def load(self, specialty: str) -> dict[str, int]:
        active = [c for c in self.cases.values() if c.state in ("assigned", "awaiting_clinician")]
        return {n: sum(c.assignee == n for c in active) for n in self.clinicians.get(specialty, [])}

    def assign(self, c: ClinicalCase, now: datetime, owner: str | None = None) -> None:
        who = REQUEST_TYPES[c.request_type][1]
        if who == "front desk":
            c.assignee = "Front desk"
        elif owner:
            c.assignee = owner
        else:
            load = self.load(c.specialty) or {"Clinic lead": 0}
            c.assignee = min(load, key=load.get)
        self._move(c, "assigned", now, f"routed to {c.assignee}")
        if who != "front desk":
            self._move(c, "awaiting_clinician", now, "notified clinician")

    def respond(self, case_id: str, response: str, now: datetime) -> ClinicalCase:
        c = self.cases[case_id]
        c.response = response
        self._move(c, "responded", now, response[:120])
        return c

    def close(self, case_id: str, now: datetime, note: str = "payor accepted") -> ClinicalCase:
        c = self.cases[case_id]
        self._move(c, "closed", now, note)
        return c

    def tick(self, now: datetime) -> list[dict]:
        """Advance clocks: reminders at 50% and 80%, escalation at 80%, expiry at 100%."""
        actions = []
        for c in self.cases.values():
            if c.state not in ("open", "assigned", "awaiting_clinician"):
                continue
            used = c.sla_used(now)
            if used >= 1.0:
                self._move(c, "expired", now, "SLA missed: the payor will decide without the response")
                actions.append({"case_id": c.case_id, "action": "expired"})
                continue
            for mark in ("50%", "80%"):
                if used >= int(mark[:-1]) / 100 and mark not in c.reminders_sent:
                    c.reminders_sent.append(mark)
                    c.history.append((now.isoformat(timespec="minutes"), "reminder", f"{mark} of SLA used"))
                    actions.append({"case_id": c.case_id, "action": f"reminder {mark}", "to": c.assignee})
                    self.on_event("case.reminder", c.as_dict(now))
                    if mark == "80%" and not c.escalated:
                        c.escalated = True
                        c.history.append((now.isoformat(timespec="minutes"), "escalated", "clinic lead notified"))
                        actions.append({"case_id": c.case_id, "action": "escalated", "to": "Clinic lead"})
        return actions

    def queue(self, now: datetime) -> list[dict]:
        live = [c for c in self.cases.values() if c.state in ("open", "assigned", "awaiting_clinician")]
        return [c.as_dict(now) for c in sorted(live, key=lambda c: c.due_at)]

    def stats(self) -> dict:
        cs = list(self.cases.values())
        done = [c for c in cs if c.state in ("responded", "closed")]
        return {"cases": len(cs), "open": sum(c.state in ("open", "assigned", "awaiting_clinician") for c in cs),
                "responded_in_sla": len(done), "expired": sum(c.state == "expired" for c in cs),
                "escalated": sum(c.escalated for c in cs)}
