import time

from harness import Journey, enter

with Journey("4_operations") as j:
    pg = j.pg
    enter(j, 2)
    j.say("AI operations: the review queue and the agents")
    j.check("Next up asks for a review", "Review what the AI read" in j.text())
    j.shot("today")
    j.btn("Start reviewing →").click()
    j.wait_idle(4)
    j.check("suggestion opens the review deck", pg.locator(".cardq").count() > 0 or "Swipe" in j.text())
    j.say("Review: mark extracted fields right or wrong")
    for _ in range(3):
        ok = pg.locator("button.ok, #ok, .yes").first
        if ok.count():
            ok.click()
        else:
            pg.keyboard.press("a")
        time.sleep(0.8)
    j.shot("review")
    for tab in ("Playbooks", "Prompt changes", "Autonomy", "Long charts"):
        j.say(f"AI Ops desk: {tab}")
        pg.get_by_role("radio", name=tab, exact=True).first.click()
        j.wait_idle(3)
        j.check(f"'{tab}' opens cleanly", not j.banned() and "Traceback" not in j.text(), j.banned())
        if tab == "Playbooks" and pg.get_by_role("button", name="Walk the plan").count():
            pg.get_by_role("button", name="Walk the plan").first.click()
            time.sleep(4)
        j.shot(tab.lower().replace(" ", "_"))
    j.nav("Prior authorizations")
    for tab in ("Read a document", "Check a request", "Watch the browser agent", "Appeal a denial", "Channels"):
        j.say(f"Prior authorizations: {tab}")
        pg.get_by_role("radio", name=tab, exact=True).first.click()
        j.wait_idle(4, timeout=200)
        j.check(f"'{tab}' opens cleanly", not j.banned() and "Traceback" not in j.text(), j.banned())
        time.sleep(1.5)
        j.shot(tab.lower().replace(" ", "_"))
    j.nav("How it was measured")
    j.check("measured page: four numbers with links", j.text().count("%") >= 4)
