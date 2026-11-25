import time

from harness import Journey, enter

with Journey("2_patient_family") as j:
    pg = j.pg
    enter(j, 0)
    j.say("Patient or family member: a guest picks 'I'm a patient or family member'")
    j.check("lands on My care", "Good" in j.text() and "My care" in j.text())
    j.check("menu has only the patient pages", all(x in j.text() for x in ("Read a letter", "My costs", "How it works"))
            and "AI Ops desk" not in j.text())
    j.check("Next up suggests reading a letter", "Read your insurance letter" in j.text())
    j.shot("home_empty")
    j.btn("Upload a letter →").click()
    j.wait_idle(3)
    j.check("suggestion opens the letter reader", "Read a letter" in pg.title() or "Drop a letter" in j.text()
            or "Use a sample letter" in j.text())
    j.say("No letter at hand: use the sample payor letter")
    j.btn("Use a sample letter").click()
    j.wait_idle(6, timeout=120)
    stamp = pg.locator(".stamp").first
    stamp.wait_for(timeout=60_000)
    j.check("letter read: decision stamp shown", stamp.inner_text().strip() in ("DENIED", "APPROVED", "PARTLY APPROVED"),
            stamp.inner_text())
    j.check("next steps listed", pg.locator(".step").count() >= 3, pg.locator(".step").count())
    j.check("appeal deadline shown", "deadline" in pg.locator(".root").first.inner_text().lower())
    j.shot("letter_read")
    pg.mouse.wheel(0, 500)
    time.sleep(1.5)
    j.nav("My care")
    j.say("Back on My care: the letter is kept, and the suggestion changed")
    t = j.text()
    j.check("letter now listed under Your letters", "No letters yet" not in t and ("DENIED" in t or "APPROVED" in t))
    j.check("Next up now says plan the appeal", "Plan your appeal" in t or "Schedule" in t)
    j.shot("home_with_letter")
    j.nav("My costs")
    j.say("My costs: what will the visits cost?")
    j.check("costs page opens", "cost" in j.text().lower())
    j.shot("costs")
    j.nav("How it works")
    j.check("plain wording on How it works (no vendor or test-data words)", not j.banned(), j.banned())
    j.shot("how")
