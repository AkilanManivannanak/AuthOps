"""Persistent store for real-user activity in the app.

Every claim about real usage ("N testers, M reviews, inter-rater kappa K") must be
computable from rows in this store, with timestamps. Nothing is seeded or simulated
here: if nobody used the app, every count is zero.

Backend: DATABASE_URL (Postgres, e.g. Neon or Supabase free tier) when set, so data
survives Streamlit Cloud restarts; otherwise a local SQLite file (fine for local use,
wiped on Streamlit Cloud redeploys).
"""
from __future__ import annotations

import hashlib
from hmac import compare_digest as hmac_eq
import json
import os
import time
import uuid
from pathlib import Path

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table, Text, create_engine, func,
                        insert, select)

meta = MetaData()

testers = Table("testers", meta,
                Column("tester_id", String(32), primary_key=True),
                Column("display_name", String(80)), Column("role", String(80)),
                Column("experience", String(40)), Column("consented_at", Float), Column("created_at", Float))
sessions = Table("sessions", meta,
                 Column("session_id", String(32), primary_key=True), Column("tester_id", String(32)),
                 Column("started_at", Float), Column("user_agent", String(200)))
events = Table("events", meta,
               Column("id", Integer, primary_key=True, autoincrement=True),
               Column("session_id", String(32)), Column("tester_id", String(32)), Column("ts", Float),
               Column("page", String(60)), Column("action", String(60)), Column("payload", Text))
doc_labels = Table("doc_labels", meta,
                   Column("id", Integer, primary_key=True, autoincrement=True),
                   Column("tester_id", String(32)), Column("ts", Float), Column("doc_id", String(80)),
                   Column("field", String(40)), Column("model_value", Text), Column("human_value", Text),
                   Column("truth_value", Text), Column("model_conf", Float), Column("seconds_on_doc", Float))
qa_labels = Table("qa_labels", meta,
                  Column("id", Integer, primary_key=True, autoincrement=True),
                  Column("tester_id", String(32)), Column("ts", Float), Column("item_id", String(80)),
                  Column("field", String(40)), Column("verdict", String(10)), Column("comment", Text),
                  Column("auto_verdict", String(10)), Column("seconds_on_item", Float))
task_results = Table("task_results", meta,
                     Column("id", Integer, primary_key=True, autoincrement=True),
                     Column("tester_id", String(32)), Column("ts", Float), Column("task", String(40)),
                     Column("success", Integer), Column("seconds", Float), Column("detail", Text))
surveys = Table("surveys", meta,
                Column("id", Integer, primary_key=True, autoincrement=True),
                Column("tester_id", String(32)), Column("ts", Float), Column("sus_score", Float),
                Column("answers", Text), Column("comment", Text))
agent_runs = Table("agent_runs", meta,
                   Column("id", Integer, primary_key=True, autoincrement=True),
                   Column("tester_id", String(32)), Column("ts", Float), Column("portal", String(20)),
                   Column("case_id", String(20)), Column("status", String(20)), Column("error_class", String(40)),
                   Column("steps", Integer), Column("smoothness", Float), Column("settings", Text))
accounts = Table("accounts", meta,
                 Column("account_id", String(32), primary_key=True), Column("email", String(160), unique=True),
                 Column("name", String(80)), Column("pw_hash", String(128)), Column("salt", String(32)),
                 Column("role", String(20)), Column("workspace", Text), Column("created_at", Float),
                 Column("updated_at", Float))

# Real usage of the app by role, and people's verdicts on AI answers. Read by authops/analytics/queries/*.sql.
usage = Table("usage", meta,
              Column("id", Integer, primary_key=True, autoincrement=True), Column("ts", Float),
              Column("day", String(10)), Column("session_id", String(32)), Column("who", String(40)),
              Column("role", String(20)), Column("page", String(60)), Column("action", String(60)))
feedback = Table("feedback", meta,
                 Column("id", Integer, primary_key=True, autoincrement=True), Column("ts", Float),
                 Column("day", String(10)), Column("session_id", String(32)), Column("who", String(40)),
                 Column("role", String(20)), Column("kind", String(20)), Column("verdict", String(10)),
                 Column("what", String(80)), Column("layer", String(10)), Column("comment", Text))


def _url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            import streamlit as st

            url = st.secrets.get("DATABASE_URL")  # type: ignore[attr-defined]
        except Exception:
            url = None
    if url:
        url = url.strip()
        # Pin the psycopg2 driver: SQLAlchemy 2.1+ defaults plain postgresql:// to psycopg (v3).
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg2://" + url[len(prefix):]
        return url
    path = Path(os.environ.get("AUTHOPS_USERDB", Path(__file__).resolve().parents[2] / "data" / "userstudy.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


class UserStore:
    def __init__(self, url: str | None = None):
        self.url = url or _url()
        self.engine = create_engine(self.url, pool_pre_ping=True)
        meta.create_all(self.engine)

    @property
    def persistent(self) -> bool:
        return not self.url.startswith("sqlite")

    @staticmethod
    def tester_id(display_name: str, salt: str = "authops") -> str:
        return hashlib.sha256(f"{salt}:{display_name.strip().lower()}".encode()).hexdigest()[:16]

    def _ins(self, table, **row):
        with self.engine.begin() as c:
            c.execute(insert(table).values(**row))

    def register(self, display_name: str, role: str, experience: str) -> str:
        tid = self.tester_id(display_name)
        with self.engine.begin() as c:
            if not c.execute(select(testers.c.tester_id).where(testers.c.tester_id == tid)).first():
                c.execute(insert(testers).values(tester_id=tid, display_name=display_name.strip()[:80],
                                                 role=role[:80], experience=experience[:40],
                                                 consented_at=time.time(), created_at=time.time()))
        return tid

    def start_session(self, tester_id: str | None, user_agent: str = "") -> str:
        sid = uuid.uuid4().hex[:16]
        self._ins(sessions, session_id=sid, tester_id=tester_id, started_at=time.time(), user_agent=user_agent[:200])
        return sid

    def event(self, session_id, tester_id, page, action, payload=None):
        self._ins(events, session_id=session_id, tester_id=tester_id, ts=time.time(), page=page, action=action,
                  payload=json.dumps(payload or {}, default=str)[:4000])

    def use(self, session_id: str, who: str, role: str, page: str, action: str) -> None:
        now = time.time()
        self._ins(usage, ts=now, day=time.strftime("%Y-%m-%d", time.gmtime(now)), session_id=session_id,
                  who=(who or "")[:40], role=(role or "")[:20], page=(page or "")[:60], action=action[:60])

    def feedback(self, session_id: str, who: str, role: str, kind: str, verdict: str, what: str = "",
                 layer: str = "", comment: str = "") -> None:
        if verdict not in ("right", "wrong"):
            raise ValueError("verdict must be right or wrong")
        now = time.time()
        self._ins(feedback, ts=now, day=time.strftime("%Y-%m-%d", time.gmtime(now)), session_id=session_id,
                  who=(who or "")[:40], role=(role or "")[:20], kind=kind[:20], verdict=verdict,
                  what=(what or "")[:80], layer=(layer or "")[:10], comment=(comment or "")[:2000])

    def doc_label(self, **row):
        self._ins(doc_labels, ts=time.time(), **row)

    def qa_label(self, **row):
        self._ins(qa_labels, ts=time.time(), **row)

    def task(self, **row):
        self._ins(task_results, ts=time.time(), **row)

    def survey(self, **row):
        self._ins(surveys, ts=time.time(), **row)

    def agent_run(self, **row):
        self._ins(agent_runs, ts=time.time(), **row)

    # ------------------------------------------------------------ accounts
    @staticmethod
    def _hash(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()

    def create_account(self, email: str, name: str, password: str) -> dict:
        email = email.strip().lower()
        if "@" not in email or len(password) < 8:
            raise ValueError("Use a valid email and a password of at least 8 characters.")
        with self.engine.begin() as c:
            if c.execute(select(accounts.c.account_id).where(accounts.c.email == email)).first():
                raise ValueError("An account with this email already exists. Sign in instead.")
            salt, aid = uuid.uuid4().hex[:16], uuid.uuid4().hex[:16]
            c.execute(insert(accounts).values(account_id=aid, email=email, name=name.strip()[:80] or email.split("@")[0],
                                              pw_hash=self._hash(password, salt), salt=salt, role="",
                                              workspace="", created_at=time.time(), updated_at=time.time()))
        return self.account(aid)

    def sign_in(self, email: str, password: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(accounts).where(accounts.c.email == email.strip().lower())).first()
        if r is None or not hmac_eq(self._hash(password, r.salt), r.pw_hash):
            return None
        return self.account(r.account_id)

    def account(self, aid: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(accounts).where(accounts.c.account_id == aid)).first()
        if r is None:
            return None
        return {"id": r.account_id, "email": r.email, "name": r.name, "role": r.role or "",
                "workspace": json.loads(r.workspace) if r.workspace else None}

    def save_account(self, aid: str, role: str | None = None, workspace: dict | None = None, name: str | None = None):
        vals = {"updated_at": time.time()}
        if role is not None:
            vals["role"] = role
        if workspace is not None:
            vals["workspace"] = json.dumps(workspace, default=str)
        if name is not None:
            vals["name"] = name[:80]
        with self.engine.begin() as c:
            c.execute(accounts.update().where(accounts.c.account_id == aid).values(**vals))

    def delete_account(self, aid: str) -> None:
        with self.engine.begin() as c:
            c.execute(accounts.delete().where(accounts.c.account_id == aid))

    def rows(self, table) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(select(table))]

    def counts(self) -> dict:
        out = {}
        with self.engine.connect() as c:
            for name, t in [("testers", testers), ("sessions", sessions), ("events", events),
                            ("doc_labels", doc_labels), ("qa_labels", qa_labels), ("tasks", task_results),
                            ("surveys", surveys), ("agent_runs", agent_runs)]:
                out[name] = c.execute(select(func.count()).select_from(t)).scalar() or 0
        return out


# ---------------------------------------------------------------- study statistics

def sus_score(answers: list[int]) -> float:
    """System Usability Scale: 10 items, 1-5. Odd items positive, even items negative. 0-100."""
    if len(answers) != 10:
        raise ValueError("SUS needs 10 answers")
    s = sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))
    return s * 2.5


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    if not a or len(a) != len(b):
        return None
    cats = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(k) / n) * (b.count(k) / n) for k in cats)
    return None if pe == 1 else (po - pe) / (1 - pe)


def pairwise_kappa(labels: list[dict], key=("item_id", "field"), value="verdict") -> dict:
    """Mean Cohen's kappa over every pair of raters on the items both rated."""
    by_rater: dict[str, dict] = {}
    for r in labels:
        by_rater.setdefault(r["tester_id"], {})[tuple(r[k] for k in key)] = r[value]
    raters = sorted(by_rater)
    ks, pairs = [], 0
    for i in range(len(raters)):
        for j in range(i + 1, len(raters)):
            common = sorted(set(by_rater[raters[i]]) & set(by_rater[raters[j]]))
            if len(common) < 5:
                continue
            k = cohen_kappa([by_rater[raters[i]][c] for c in common], [by_rater[raters[j]][c] for c in common])
            if k is not None:
                ks.append(k)
                pairs += 1
    return {"pairs": pairs, "mean_kappa": round(sum(ks) / len(ks), 3) if ks else None}
