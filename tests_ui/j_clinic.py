import re
import time

from harness import Journey, enter

with Journey("3_clinic_team") as j:
    pg = j.pg
    enter(j, 1)
    j.say("Clinic team: today's board, built from this clinic's own requests")
    need0, ready0, wait0, clear0 = (j.tile(x) for x in ("need you today", "ready to send", "waiting on a payor", "cleared for care"))
    j.check("dashboard tiles load", min(need0, ready0, wait0) >= 0, f"need {need0}, ready {ready0}, waiting {wait0}, clear {clear0}")
    j.check("Next up suggests the most urgent work", "NEXT UP" in j.text().upper())
    j.shot("today")

    # ---- fix and send one request, starting from the board
    j.say("Open a patient whose plan is unsigned, straight from the board")
    pg.get_by_text("Unsigned treatment plan").first.click()
    j.wait_idle(4)
    name = pg.locator("h3, .ao-big, h2").filter(has_text=re.compile(r"^[A-Z][a-z]+ [A-Z][a-z]+$")).first
    j.check("the board card opened that patient at the readiness step", "Readiness check" in j.text()
            and "Unsigned treatment plan" in j.text())
    j.shot("readiness")
    j.btn("Get the provider's signature").click()
    j.wait_idle(3)
    j.check("fixing the signature clears the block", "Unsigned treatment plan" not in j.text().split("Readiness check")[-1][:600]
            or j.pg.get_by_role("button", name=re.compile("^Send to")).count() > 0)
    ask = pg.get_by_role("button", name=re.compile(r"^Ask for \d+"))
    if ask.count():
        j.say("The approval outlook suggests a request size the payor approves in full")
        ask.first.click()
        j.wait_idle(3)
        j.check("recommended amount applied", "Ask for" not in " ".join(b.inner_text() for b in pg.get_by_role("button").all()[:40]))
    j.btn(re.compile("^Send to")).click()
    j.wait_idle(4)
    j.check("request sent", pg.get_by_role("button", name="Check for a decision").count() > 0)
    j.shot("sent")
    j.nav("Today")
    need1, wait1 = j.tile("need you today"), j.tile("waiting on a payor")
    j.check("Today reflects the fix and the send", need1 == need0 - 1 and wait1 == wait0 + 1,
            f"need {need0}->{need1}, waiting {wait0}->{wait1}")
    j.check("activity log records it", "Sent" in j.text())

    # ---- reauthorization from monitoring
    j.nav("Insurance monitoring")
    j.say("Insurance monitoring: authorizations about to run out")
    m = re.search(r"(\d+)\s+patients? need", j.text())
    due0 = int(m.group(1)) if m else -1
    j.shot("monitoring")
    j.btn("Start the reauthorization").click()
    j.wait_idle(3)
    m = re.search(r"(\d+)\s+patients? need", j.text())
    due1 = int(m.group(1)) if m else -1
    j.check("starting a reauth moves the patient out of 'due'", due1 == due0 - 1, f"{due0}->{due1}")

    # ---- approve a payor rule and watch it hold open requests
    j.say("A payor changed a rule: approve it")
    pg.get_by_text("Payor rule changes").first.scroll_into_view_if_needed()
    time.sleep(1)
    j.btn("Approve rule").first.click()
    j.wait_idle(3)
    t = j.text()
    j.check("rule goes live with an explanation", "Rule live" in t or "Enforced" in t or "held" in t.lower())
    j.shot("rule")
    j.nav("Today")
    need2 = j.tile("need you today")
    j.check("Today updates after the rule and the reauth", need2 != need1 or "Approved" in j.text(),
            f"need {need1}->{need2}")
    j.shot("today_after")

    # ---- every other page on the clinic menu opens cleanly
    for title in ("Benefit checks", "Check a document", "AI Ops desk", "How it was measured"):
        j.nav(title)
        j.check(f"'{title}' opens with professional wording", not j.banned() and "Error" not in j.text()[:400], j.banned())
