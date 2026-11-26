from datetime import date

from authops import workspace as W

T = date(2026, 11, 25)


def ws():
    return W.new_workspace("clinic", "Test clinic", seed=7, today=T)


def test_seeded_workspace_has_every_stage_and_real_issues():
    w = ws()
    stages = {p["stage"] for p in w["patients"]}
    assert {"intake", "check", "ready", "submitted", "denied"} <= stages
    for p in w["patients"]:
        if p["stage"] == "check":
            assert W.issues(p, w, T), p["id"]


def test_fix_then_send_then_decision_moves_the_same_record():
    w = ws()
    p = next(p for p in w["patients"] if p["stage"] == "check")
    for i in W.issues(p, w, T):
        W.fix(w, p["id"], i["code"], T, value=W.outlook(p)["recommended"])
    assert W.status(p, w, T)["label"] == "Ready to send"
    W.submit(w, p["id"], T)
    assert W.metrics(w, T)["waiting"] >= 1
    W.receive(w, p["id"], T)
    assert W.status(p, w, T)["label"] in ("Clear for care", "Reauth due", "Denied")
    assert w["activity"][0]["text"].startswith(p["payor_name"])


def test_approving_a_payor_rule_holds_open_requests_it_affects():
    w = ws()
    msg = W.approve_rule(w, "kcm-pt", "KCM", "physical_therapy", 20, "PT limited to 20 visits", T)
    held = [p for p in w["patients"] if p["payor"] == "KCM" and p["spec"] == "physical_therapy" and p["units"] > 20
            and p["stage"] == "check"]
    assert held and "held" in msg
    assert any(i["code"] == "rule" for i in W.issues(held[0], w, T))


def test_suggestions_put_lapsing_care_first_and_follow_state():
    w = ws()
    s = W.suggestions(w, T, 10)
    assert s[0]["title"].startswith("Start") and s[0]["page"] == "insurance_monitoring"
    W.start_reauth(w, s[0]["pid"], T)
    assert all(x.get("pid") != s[0]["pid"] for x in W.suggestions(w, T, 10))


def test_patient_workspace_suggests_reading_a_letter_first():
    w = W.new_workspace("patient", "Mamata", today=T)
    assert W.suggestions(w, T)[0]["page"] == "try_it"


def test_operations_people_see_their_own_work_first():
    from datetime import date
    from authops import workspace as W
    w = W.new_workspace("ops", "Ops", seed=3, today=date(2026, 11, 25))
    top = W.suggestions(w, date(2026, 11, 25), 3)
    assert top[0]["title"] == "Review what the AI read" and top[1]["title"] == "Approve a payor rule change"


def test_payor_limit_fix_uses_the_payors_limit_and_keeps_the_rest():
    """Chrisen 8: the button must apply the payor's rule, never quietly lower care to the model's number."""
    from datetime import date

    from authops import workspace as W
    t = date(2026, 11, 25)
    ws = W.new_workspace("clinic", "T", seed=1, today=t)
    over = None
    for p in ws["patients"]:
        if p["stage"] in ("check", "ready"):
            p["units"] = W.payor_limit(p) + 57
            if any(i["code"] == "units_within_payor_limit" for i in W.issues(p, ws, t)):
                over = p
                break
    assert over is not None
    it = next(i for i in W.issues(over, ws, t) if i["code"] == "units_within_payor_limit")
    cap = W.payor_limit(over)
    assert it["cap"] == cap
    W.split(ws, over["id"], t)
    assert over["units"] == cap and over["remainder"] == 57
    assert not any(i["code"] == "units_within_payor_limit" for i in W.issues(over, ws, t))
