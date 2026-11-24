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


class EmailOtpLock:
    """Serialize email one-time codes per inbox.

    Several credentials often share one inbox. If two agents log in at once, each can read the
    other's code. A lease on the inbox makes code retrieval one-at-a-time; a lease expires after
    `ttl_s` (5 minutes) so a crashed agent cannot block the inbox forever."""

    def __init__(self, ttl_s: float = 300.0, clock=None):
        import time as _time

        self.ttl_s = ttl_s
        self.clock = clock or _time.monotonic
        self._lock = threading.Lock()
        self._held: dict[str, tuple[str, float]] = {}   # inbox -> (holder, expires_at)

    def acquire(self, inbox: str, holder: str) -> bool:
        with self._lock:
            now = self.clock()
            cur = self._held.get(inbox)
            if cur and cur[1] > now and cur[0] != holder:
                return False
            self._held[inbox] = (holder, now + self.ttl_s)
            return True

    def release(self, inbox: str, holder: str) -> None:
        with self._lock:
            if self._held.get(inbox, ("", 0))[0] == holder:
                del self._held[inbox]

    def holder(self, inbox: str) -> str | None:
        with self._lock:
            cur = self._held.get(inbox)
            return cur[0] if cur and cur[1] > self.clock() else None
