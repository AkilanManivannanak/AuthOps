"""Run and step persistence (SQLite).

Every inference call and every tool execution is one row in `steps`, so a failed run
can be replayed and queried with SQL: which tool failed, after how many retries,
with what error class. Silna does this on Postgres with Dramatiq; SQLite keeps the
repo dependency-free and the schema ports directly.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, case_id TEXT, portal TEXT, channel TEXT, arm TEXT, policy TEXT,
  model TEXT, started REAL, ended REAL, status TEXT, outcome TEXT, ref TEXT, steps INTEGER,
  retries INTEGER, smoothness REAL, verified INTEGER, qa_routed INTEGER, error_class TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, notes TEXT
);
CREATE TABLE IF NOT EXISTS steps (
  run_id TEXT, idx INTEGER, kind TEXT, tool TEXT, args TEXT, ok INTEGER, error_class TEXT,
  detail TEXT, url TEXT, duration_ms REAL, ts REAL
);
CREATE TABLE IF NOT EXISTS qa_reviews (
  run_id TEXT, case_id TEXT, field TEXT, submitted TEXT, expected TEXT, severity TEXT, comment TEXT
);
CREATE TABLE IF NOT EXISTS ops_events (ts REAL, kind TEXT, subject TEXT, detail TEXT);
"""


class Store:
    def __init__(self, path: str | Path = "reports/authops.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)

    def start_run(self, run_id: str, **kw) -> None:
        self.db.execute("INSERT OR REPLACE INTO runs (run_id, started) VALUES (?, ?)", (run_id, time.time()))
        self.update_run(run_id, **kw)

    def update_run(self, run_id: str, **kw) -> None:
        if not kw:
            return
        cols = ", ".join(f"{k}=?" for k in kw)
        self.db.execute(f"UPDATE runs SET {cols} WHERE run_id=?", (*kw.values(), run_id))
        self.db.commit()

    def step(self, run_id: str, idx: int, kind: str, tool: str, args: dict, ok: bool,
             error_class: str = "", detail: str = "", url: str = "", duration_ms: float = 0.0) -> None:
        self.db.execute("INSERT INTO steps VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (run_id, idx, kind, tool, json.dumps(args, default=str)[:2000], int(ok),
                         error_class, detail[:2000], url, duration_ms, time.time()))
        self.db.commit()

    def qa(self, run_id, case_id, field, submitted, expected, severity, comment) -> None:
        self.db.execute("INSERT INTO qa_reviews VALUES (?,?,?,?,?,?,?)",
                        (run_id, case_id, field, json.dumps(submitted), json.dumps(expected), severity, comment))
        self.db.commit()

    def event(self, kind: str, subject: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO ops_events VALUES (?,?,?,?)", (time.time(), kind, subject, detail))
        self.db.commit()

    def query(self, sql: str, params=()) -> list[dict]:
        cur = self.db.execute(sql, params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]
