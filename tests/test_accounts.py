import time

import pytest

from authops.ops.userstore import UserStore


@pytest.fixture
def s(tmp_path):
    return UserStore(f"sqlite:///{tmp_path / 'a.db'}")


def test_create_sign_in_and_wrong_password(s):
    a = s.create_account("Ana@Example.com", "Ana", "longpassword")
    assert s.sign_in("ana@example.com", "longpassword")["id"] == a["id"]
    assert s.sign_in("ana@example.com", "wrong-password") is None
    with pytest.raises(ValueError):
        s.create_account("ana@example.com", "Ana 2", "longpassword")
    with pytest.raises(ValueError):
        s.create_account("bad", "x", "short")


def test_sign_in_is_rate_limited(s):
    s.create_account("b@example.com", "B", "longpassword")
    for _ in range(5):
        assert s.sign_in("b@example.com", "nope") is None
    with pytest.raises(PermissionError):
        s.sign_in("b@example.com", "longpassword")   # even the right password waits out the minute
    s.FAIL_WINDOW = 0.01
    time.sleep(0.02)
    assert s.sign_in("b@example.com", "longpassword")


def test_signing_key_is_random_and_kept(s, tmp_path):
    k = s.signing_key()
    assert len(k) == 64 and k == s.signing_key()
    assert UserStore(f"sqlite:///{tmp_path / 'other.db'}").signing_key() != k


def test_delete_account_removes_its_data(s):
    a = s.create_account("c@example.com", "C", "longpassword")
    s.use("x", "acct:" + a["id"], "clinic", "p", "assist")
    s.feedback("x", "acct:" + a["id"], "clinic", "plan", "wrong", what="dates")
    s.ai_calls("acct:" + a["id"], "2026-11-25", add=1)
    v0 = s.token_version(a["id"])
    s.delete_account(a["id"])
    assert s.account(a["id"]) is None and s.sign_in("c@example.com", "longpassword") is None
    assert not [r for r in s.rows(__import__("authops.ops.userstore", fromlist=["usage"]).usage) if r["who"].endswith(a["id"])]
    assert s.ai_calls("acct:" + a["id"], "2026-11-25") == 0 and s.token_version(a["id"]) > v0


def test_feedback_columns_are_added_to_an_old_table(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE feedback (id INTEGER PRIMARY KEY, ts FLOAT, day VARCHAR(10), session_id VARCHAR(32),"
                " who VARCHAR(40), role VARCHAR(20), kind VARCHAR(20), verdict VARCHAR(10), what VARCHAR(80),"
                " layer VARCHAR(10), comment TEXT)")
    con.commit()
    con.close()
    s = UserStore(f"sqlite:///{db}")
    s.feedback("x", "", "", "letter", "right", doc_id="abc", is_sample=True, result="{}")
    assert s.rows(__import__("authops.ops.userstore", fromlist=["feedback"]).feedback)[0]["doc_id"] == "abc"
