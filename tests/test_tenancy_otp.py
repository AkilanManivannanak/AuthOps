from authops.agent.credentials import EmailOtpLock
from authops.ops.store import Store


def test_tenant_view_never_returns_another_providers_rows(tmp_path):
    s = Store(tmp_path / "t.db")
    s.start_run("r1", tenant="clinic-a", status="submitted", portal="northwind")
    s.start_run("r2", tenant="clinic-b", status="submitted", portal="northwind")
    s.step("r2", 1, "tool", "fill", {"target": "member_id"}, True)
    a, b = s.for_tenant("clinic-a"), s.for_tenant("clinic-b")
    assert [r["run_id"] for r in a.runs()] == ["r1"]
    assert [r["run_id"] for r in b.runs(status="submitted")] == ["r2"]
    assert a.steps("r2") == []            # knowing another tenant's run id is not enough
    assert len(b.steps("r2")) == 1
    try:
        a.runs(tenant="clinic-b")         # cannot widen the filter
        raise AssertionError("filter on tenant accepted")
    except ValueError:
        pass


def test_old_databases_get_a_tenant_column(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, started REAL, status TEXT)")
    con.commit()
    con.close()
    s = Store(p)
    s.start_run("x")
    assert s.for_tenant("default").runs()[0]["run_id"] == "x"


def test_email_otp_is_serialized_and_expires():
    now = [0.0]
    lock = EmailOtpLock(ttl_s=300, clock=lambda: now[0])
    assert lock.acquire("ops@clinic.test", "agent-1")
    assert not lock.acquire("ops@clinic.test", "agent-2")    # must wait: it would read agent-1's code
    assert lock.acquire("ops@other.test", "agent-2")          # a different inbox is free
    now[0] = 301                                              # agent-1 crashed and never released
    assert lock.acquire("ops@clinic.test", "agent-2")
    lock.release("ops@clinic.test", "agent-1")                # a stale holder cannot release it
    assert lock.holder("ops@clinic.test") == "agent-2"
    lock.release("ops@clinic.test", "agent-2")
    assert lock.holder("ops@clinic.test") is None
