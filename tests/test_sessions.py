"""Saved sign-ins: no key that can be worked out from the code, an expiry, and signing out ends them."""
import hashlib
import hmac
import time

import pytest


@pytest.fixture
def acc(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTHOPS_USERDB", str(tmp_path / "s.db"))
    monkeypatch.delenv("AUTHOPS_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import app.account as A
    from authops.ops.userstore import UserStore
    store = UserStore(f"sqlite:///{tmp_path / 's.db'}")
    monkeypatch.setattr(A, "_store", lambda: store)
    return A, store, store.create_account("t@example.com", "T", "longpassword")["id"]


def test_good_token_round_trips(acc):
    A, _, aid = acc
    assert A.token_account(A._token(aid)) == aid


def test_the_old_repo_constant_key_no_longer_works(acc):
    A, _, aid = acc
    old_key = hashlib.sha256(b"authops:local").digest()
    forged_old = aid + "." + hmac.new(old_key, aid.encode(), hashlib.sha256).hexdigest()[:32]
    msg = f"{aid}.0.{int(time.time()) + 999}"
    forged_new = msg + "." + hmac.new(old_key, msg.encode(), hashlib.sha256).hexdigest()
    assert A.token_account(forged_old) is None and A.token_account(forged_new) is None


def test_expired_and_signed_out_tokens_are_refused(acc):
    A, store, aid = acc
    assert A.token_account(A._token(aid, exp=int(time.time()) - 1)) is None
    tok = A._token(aid)
    store.revoke_sessions(aid)
    assert A.token_account(tok) is None and A.token_account(A._token(aid)) == aid


def test_tampered_tokens_are_refused(acc):
    A, _, aid = acc
    t = A._token(aid)
    assert A.token_account(t[:-1] + ("0" if t[-1] != "0" else "1")) is None
    assert A.token_account("other." + t.split(".", 1)[1]) is None
    assert A.token_account("garbage") is None and A.token_account("") is None
