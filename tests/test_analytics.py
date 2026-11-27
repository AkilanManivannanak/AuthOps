from authops.analytics.reports import names, run
from authops.ops.userstore import UserStore


def _store(tmp_path):
    s = UserStore(f"sqlite:///{tmp_path / 'u.db'}")
    s.use("s1", "acct:a", "", "home", "view")
    s.use("s1", "acct:a", "patient", "try_it", "assist")
    s.use("s2", "", "", "home", "view")
    s.use("s3", "acct:b", "clinic", "channels", "x12")
    s.feedback("s1", "acct:a", "patient", "letter", "wrong", what="deadline", layer="ai", comment="date off by a day")
    s.feedback("s3", "acct:b", "clinic", "letter", "right", layer="ai")
    s.feedback("s3", "acct:b", "clinic", "plan", "right", layer="rules")
    s.qa_label(tester_id="t", item_id="d1", field="npi", verdict="wrong", comment="", auto_verdict="wrong", seconds_on_item=4)
    return s


def test_every_report_runs_on_an_empty_store(tmp_path):
    s = UserStore(f"sqlite:///{tmp_path / 'e.db'}")
    for n in names():
        run(n, s)


def test_reports_count_what_happened(tmp_path):
    s = _store(tmp_path)
    funnel = {r["stage"]: r["sessions"] for r in run("funnel", s)}
    assert funnel == {"Opened the app": 3, "Picked a role": 2, "Used a tool": 2, "Rated an AI answer": 2}
    roles = {r["role"]: r["sessions"] for r in run("by_role", s)}
    assert roles == {"patient": 1, "clinic": 1, "left before choosing": 1}
    assert sum(roles.values()) == funnel["Opened the app"]      # each session counted once
    acc = {(r["kind"], r["layer"]): r["pct_right"] for r in run("ai_accuracy", s)}
    assert {r["document"] for r in run("ai_accuracy", s)} == {"real upload"}
    assert acc[("letter", "ai")] == 50.0 and acc[("plan", "rules")] == 100.0
    ww = run("what_went_wrong", s)[0]
    assert (ww["kind"], ww["what"], ww["times"]) == ("letter", "deadline", 1)
    assert run("field_errors", s)[0]["caught_by_reviewer"] == 1


def test_feedback_rejects_bad_verdicts(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        _store(tmp_path).feedback("s", "", "", "letter", "maybe")
