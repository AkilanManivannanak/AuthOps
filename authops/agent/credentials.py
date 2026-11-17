"""Credential pool with leases and consecutive-failure disabling.

Portals kick concurrent sessions and lock accounts after repeated bad logins. Agents
lease a credential for a session and return it. A credential that fails to log in
`threshold` times in a row is disabled and Ops is notified, instead of an agent
retrying it into a lockout.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class Credential:
    portal: str
    username: str
    password: str
    totp: str | None = None
    consecutive_failures: int = 0
    disabled: bool = False
    leased: bool = False


class CredentialPool:
    def __init__(self, creds: dict[str, list[dict]], threshold: int = 2, on_disable=None):
        self.lock = threading.Lock()
        self.threshold = threshold
        self.on_disable = on_disable or (lambda c, why: None)
        self._rr: dict[str, int] = {}
        self.pool: dict[str, list[Credential]] = {
            portal: [Credential(portal, c["username"], c["password"], c.get("totp")) for c in lst]
            for portal, lst in creds.items()
        }

    def lease(self, portal: str, exclude: set[str] | None = None) -> Credential | None:
        """Round-robin over healthy credentials so load (and bad credentials) surface evenly."""
        with self.lock:
            lst = self.pool.get(portal, [])
            start = self._rr.get(portal, 0)
            for k in range(len(lst)):
                c = lst[(start + k) % len(lst)]
                if not c.disabled and not c.leased and c.username not in (exclude or set()):
                    c.leased = True
                    self._rr[portal] = (start + k + 1) % len(lst)
                    return c
        return None  # caller queues or fails the run as "no_credential"

    def release(self, cred: Credential) -> None:
        with self.lock:
            cred.leased = False

    def report(self, cred: Credential, ok: bool, why: str = "") -> None:
        with self.lock:
            if ok:
                cred.consecutive_failures = 0
                return
            cred.consecutive_failures += 1
            if cred.consecutive_failures >= self.threshold or why == "locked":
                cred.disabled = True
                self.on_disable(cred, why)

    def status(self) -> list[dict]:
        return [{"portal": c.portal, "username": c.username, "disabled": c.disabled,
                 "failures": c.consecutive_failures} for lst in self.pool.values() for c in lst]
