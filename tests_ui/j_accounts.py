import time
import uuid

from harness import BASE, Journey, enter

tag = uuid.uuid4().hex[:6]
A = {"name": "Akilan Test", "email": f"akilan.{tag}@example.com", "password": "careready123"}
B = {"name": "Mamata Test", "email": f"mamata.{tag}@example.com", "password": "careready456"}


def sign_out(j, first):
    j.pg.get_by_role("button", name=f"👤 {first}").first.click()
    time.sleep(1)
    j.btn("Sign out").click()
    j.wait_idle(4)


def sign_in(j, acc):
    pg = j.pg
    f = pg.locator("[data-testid=stForm]").first
    f.get_by_label("Email", exact=True).fill(acc["email"])
    f.get_by_label("Password", exact=True).fill(acc["password"])
    f.get_by_role("button", name="Sign in").click()
    j.wait_idle(5)


with Journey("1_accounts_and_sign_in") as j:
    pg = j.pg
    pg.goto(BASE + "/")
    j.wait_idle(4)
    j.say("Sign-in page: the animated preview speaks to patients, clinics and operations")
    j.check("sign-in page shows the three-audience preview", pg.locator(".pills button").count() == 3)
    time.sleep(6)
    j.shot("landing")

    j.say("Create account #1 and pick 'I work at a clinic'")
    enter(j, 1, A)
    j.check("account #1 created and signed in", "Akilan" in j.text())
    need0 = j.tile("need you today")
    j.btn("Start reauth →").first.click()
    j.wait_idle(4)
    j.btn("Start the reauthorization").click()
    j.wait_idle(3)
    j.nav("Today")
    need1 = j.tile("need you today")
    j.check("account #1 did some work", need1 == need0 - 1, f"{need0}->{need1}")

    j.say("Sign out, then sign back in")
    sign_out(j, "Akilan")
    j.check("signed out back to the sign-in page", pg.get_by_role("button", name="Sign in").count() > 0)
    sign_in(j, A)
    j.check("signing back in restores account #1's workspace", "Akilan" in j.text()
            and j.tile("need you today") == need1 and "Started" in j.text(), f"need {j.tile('need you today')}")
    j.shot("restored")

    j.say("A second person on the same app: Mamata, as a patient")
    sign_out(j, "Akilan")
    enter(j, 0, B)
    t = j.text()
    j.check("account #2 gets its own patient view", "Mamata" in t and "My care" in t and "No letters yet" in t)
    j.check("account #2 sees none of account #1's work", "Started" not in t and "need you today" not in t)
    j.shot("second_account")

    j.say("Wrong password is refused")
    sign_out(j, "Mamata")
    sign_in(j, {"email": A["email"], "password": "not-the-password"})
    j.check("wrong password refused with a clear message", "don't match" in j.text())
    pg.reload()
    j.wait_idle(5)
    sign_in(j, A)
    j.check("account #1 still intact after all that", "Akilan" in j.text() and "Started" in j.text())
