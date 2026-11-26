"""Run the .sql reports in queries/ against the usage store (SQLite locally, Postgres in production).

    python -m authops.analytics.reports            # all reports, as text tables
    python -m authops.analytics.reports funnel     # one report
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

QUERIES = Path(__file__).with_name("queries")
TITLES = {"funnel": "How far people get", "by_role": "Use by role", "daily": "Activity per day",
          "top_actions": "Most used actions", "returning": "Returning people",
          "ai_accuracy": "Answers people rated (AI and rule checks)", "what_went_wrong": "What people said was wrong",
          "field_errors": "Review queue: where the extractor was wrong"}


def names() -> list[str]:
    return [n for n in TITLES if (QUERIES / f"{n}.sql").exists()]


def sql(name: str) -> str:
    return (QUERIES / f"{name}.sql").read_text()


def run(name: str, store=None) -> list[dict]:
    if store is None:
        from authops.ops.userstore import UserStore

        store = UserStore()
    with store.engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(sql(name)))]


def _table(rows: list[dict]) -> str:
    if not rows:
        return "  (no rows yet)"
    cols = list(rows[0])
    w = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    line = lambda vals: "  " + "  ".join(str(v).ljust(w[c]) for c, v in zip(cols, vals))  # noqa: E731
    return "\n".join([line(cols), line(["-" * w[c] for c in cols])] + [line([r[c] for c in cols]) for r in rows])


if __name__ == "__main__":
    for n in sys.argv[1:] or names():
        print(f"\n{TITLES.get(n, n)}\n{_table(run(n))}")
