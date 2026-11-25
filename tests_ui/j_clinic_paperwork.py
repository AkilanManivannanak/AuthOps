"""Real clinic paperwork (de-identified) through Check a document: a doctor's referral and a PT visit log.
Needs AUTHOPS_DEID_DIR with p3_referral.png and p2_treatment_record.png. The images are not in the repo."""
import os
import time

from harness import Journey, enter


def has(pg, *parts):
    return all(pg.get_by_text(x, exact=False).count() > 0 for x in parts)

DEID = os.environ.get("AUTHOPS_DEID_DIR", "/home/claude/deid")

with Journey("7_real_clinic_paperwork") as j:
    pg = j.pg
    enter(j, 1)
    j.nav("Check a document")
    j.say("A real referral from a Brooklyn PT clinic, with every patient detail blacked out")
    box = pg.locator("[data-testid=stCheckbox]", has_text="AI reader").locator("input")
    if box.count() and box.is_checked():
        pg.locator("[data-testid=stCheckbox]", has_text="AI reader").locator("label").click()
        j.wait_idle(2)
    j.check("AI reader is off: the pages are read on this machine only", not box.is_checked())
    pg.locator("input[type=file]").set_input_files(f"{DEID}/p3_referral.png")
    j.wait_idle(8)
    j.check("it knows this is a referral, not a plan", has(pg, "This is a referral"))
    j.check("finds the referral reason among the history codes", has(pg, "M54.50", "history, not this referral"))
    j.check("sends the request to the primary plan, Anthem", has(pg, "Send it to the primary plan: Anthem"))
    j.check("explains the dual-eligible order", has(pg, "dual", "Original Medicare"))
    j.check("lists what the payor still needs", has(pg, "97161", "signed by the therapist"))
    pg.mouse.wheel(0, 500)
    time.sleep(1.5)
    j.shot("referral")
    pg.mouse.wheel(0, -500)
    j.say("The clinic's visit log: its own shorthand, not billing codes")
    pg.locator("input[type=file]").set_input_files(f"{DEID}/p2_treatment_record.png")
    j.wait_idle(8)
    j.check("the visit log is recognised", has(pg, "This is a visit log"))
    j.check("columns map to billing codes", has(pg, "97035", "97140", "97012"))
    j.check("reminds to keep the authorization with the log", has(pg, "authorization number"))
    pg.mouse.wheel(0, 500)
    time.sleep(1.5)
    j.shot("visit_log")
    j.nav("Today")
    j.check("the work shows up in the activity log", "Checked a referral" in j.text())
