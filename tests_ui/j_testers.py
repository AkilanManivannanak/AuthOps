"""The exact steps sent to the testers, so the messages are known to work before anyone follows them."""
import time

from harness import Journey, enter


def has(pg, *parts):
    return all(pg.get_by_text(x, exact=False).count() > 0 for x in parts)


def rate(j, pg, verdict="Yes"):
    pg.mouse.wheel(0, 900)
    time.sleep(1)
    pg.get_by_role("radio", name=verdict).last.click()
    j.wait_idle(2)
    if verdict == "Not quite":
        pg.get_by_label("What should it have said? (optional)").fill("Test note")
    j.btn("Send", exact=True).click()
    j.wait_idle(3)
    pg.mouse.wheel(0, -2000)
    time.sleep(0.8)


with Journey("9_tester_steps") as j:
    pg = j.pg
    enter(j, 0, account={"name": "Patient Tester", "email": f"pt{int(time.time())}@example.com", "password": "longpassword"})
    j.say("Patient steps: three different sample letters, three ratings")
    j.nav("Read a letter")
    j.btn("Use a sample letter").click()
    j.wait_idle(8)
    j.check("sample 1 is a partial approval in visits", has(pg, "14 visits"))
    rate(j, pg, "Yes")
    for n, want in ((2, "DENIED"), (3, "APPROVED")):
        j.btn("Try another sample").click()
        j.wait_idle(8)
        j.check(f"sample {n} is a different letter ({want.lower()})", has(pg, want))
        rate(j, pg, "Yes" if n == 3 else "Not quite")
    j.check("no page errors so far", "Traceback" not in j.text())
    j.shot("patient_third_rating")
    import os
    import sys
    sys.path.insert(0, "..")
    from authops.ops.userstore import UserStore, feedback
    rows = UserStore(f"sqlite:///{os.environ.get('AUTHOPS_USERDB', '/tmp/ui.db')}").rows(feedback)
    mine = [r for r in rows if r["role"] == "patient" and r["is_sample"] == 1]
    j.check("three ratings stored, on three different documents", len({r["doc_id"] for r in mine[-3:]}) == 3, len(mine))
