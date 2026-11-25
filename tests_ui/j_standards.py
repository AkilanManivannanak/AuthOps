"""X12 278 exchange, 'Was this right?' feedback, and the usage reports that read it back."""
import re
import time

from harness import Journey, enter

with Journey("6_standards_and_quality") as j:
    pg = j.pg
    enter(j, 1)
    j.nav("Prior authorizations")
    pg.get_by_role("radio", name="Channels").click()
    j.wait_idle(4)
    j.say("The same request as a HIPAA X12 278 file")
    pg.get_by_text("The same request as an X12 278").scroll_into_view_if_needed()
    time.sleep(1)
    j.check("278 request passes the clearinghouse envelope check", "Envelope valid" in j.text())
    j.check("test payor approves and it is read back", "HCR A1" in j.text())
    j.shot("x12")
    pg.locator("[data-testid=stRadio] label", has_text="denied").first.click()
    j.wait_idle(3)
    j.check("a denial is read back with its reason code", "HCR A3" in j.text() and "reason code NME" in j.text())

    j.nav("Check a document")
    j.say("Check a sample letter, then tell the app it got something wrong")
    pg.get_by_role("radio", name="A payor's letter came back").click()
    j.wait_idle(2)
    j.btn("Use a sample letter").click()
    j.wait_idle(6)
    j.check("feedback asked under the result", "WAS THIS RIGHT?" in j.text().upper())
    pg.get_by_role("radio", name="Not quite").click()
    j.wait_idle(2)
    j.check("asks what was off", "What was off?" in j.text())
    pg.get_by_label("What should it have said? (optional)").fill("Deadline should be one day later")
    pg.get_by_label("What should it have said? (optional)").press("Enter")
    j.wait_idle(2)
    j.btn("Send", exact=True).click()
    j.wait_idle(3)
    j.check("rating saved", "Your answer goes into the error review" in j.text())
    j.shot("feedback")

    j.nav("AI Ops desk")
    pg.get_by_role("radio", name="Usage and quality").click()
    j.wait_idle(4)
    j.say("Usage and quality: every number is a SQL query over real use")
    t = j.text()
    m = re.search(r"Rated an AI answer\s*\n?\s*(\d+)", t)
    j.check("the funnel counts this visit's rating", m and int(m.group(1)) >= 1, m.group(0) if m else t[:200])
    import os
    import sys
    sys.path.insert(0, "..")
    from authops.analytics.reports import run
    from authops.ops.userstore import UserStore
    wrong = run("what_went_wrong", UserStore(f"sqlite:///{os.environ.get('AUTHOPS_USERDB', '/tmp/ui.db')}"))
    j.check("the wrong answer is stored for the error review", any(r["kind"] == "letter" for r in wrong), wrong[:2])
    pg.get_by_text("The SQL behind these numbers").click()
    time.sleep(1.5)
    j.check("the SQL is shown", "SELECT" in j.text())
    j.shot("usage")
    j.check("no vendor words on screen", not j.banned(), j.banned())
