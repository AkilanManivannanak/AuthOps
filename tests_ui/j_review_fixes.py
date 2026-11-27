"""Replays what the two code reviews and the walkthroughs found, each now expected to work."""
import time

from harness import Journey, enter


def has(pg, *parts):
    return all(pg.get_by_text(x, exact=False).count() > 0 for x in parts)


with Journey("8_review_fixes") as j:
    pg = j.pg
    enter(j, 1, account={"name": "Review Tester", "email": f"review{int(time.time())}@example.com", "password": "longpassword"})
    j.nav("Check a document")

    j.say("Review: switching modes used to show the previous document's result")
    pg.get_by_role("radio", name="A payor's letter came back").click()
    j.wait_idle(2)
    j.btn("Use a sample letter").click()
    j.wait_idle(8)
    pg.get_by_role("radio", name="Before we send a prior auth").click()
    j.wait_idle(3)
    j.check("a new mode starts empty instead of re-reading the letter", has(pg, "Drop a letter or a plan above"))
    j.btn("Use a sample plan").click()
    j.wait_idle(8)
    j.say("Review: the unsigned sample plan used to score 100")
    j.check("blank signature line is flagged", has(pg, "No signature found"))
    j.check("plan dates read from the plan's own range", has(pg, "Plan runs"))
    pg.mouse.wheel(0, 400)
    time.sleep(1)
    j.shot("unsigned_plan")

    j.say("Walkthrough: rule-only answers now show the line they came from")
    pg.mouse.wheel(0, -400)
    pg.get_by_role("radio", name="A payor's letter came back").click()
    j.wait_idle(2)
    j.btn("Try another sample").click()     # the first letter sample was used above
    j.wait_idle(8)
    j.check("evidence from the page is shown", has(pg, "on the page"))
    j.check("no dead-end 'turn on the AI reader' hint", not has(pg, "Turn on the AI reader"))
    j.check("insurance terms explained in plain words", has(pg, "In plain words"))
    j.shot("letter_evidence")

    j.say("Review: an account and its data can be deleted")
    pg.locator(".st-key-acct_chip button").first.click()
    time.sleep(1)
    j.check("account menu offers sign out on all devices", has(pg, "Sign out on all devices"))
    pg.get_by_text("Delete my account").first.click()
    time.sleep(0.8)
    pg.get_by_text("I understand").first.click()
    time.sleep(0.5)
    j.btn("Delete everything").click()
    j.wait_idle(4)
    j.check("back at sign-in after deleting", pg.get_by_role("button", name="Sign in").count() > 0)
    j.check("no page errors", "Traceback" not in j.text())
