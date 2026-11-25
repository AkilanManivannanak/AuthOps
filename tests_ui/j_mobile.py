import time

from harness import BASE, Journey, enter


def no_sideways_scroll(pg):
    return pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 2")


with Journey("5_phone", viewport=(390, 844)) as j:
    pg = j.pg
    pg.goto(BASE + "/")
    j.wait_idle(5)
    j.say("Phone, 390 px wide: the sign-in page")
    j.check("preview is visible on a phone", pg.locator(".stage").first.is_visible())
    j.check("no sideways scrolling on the sign-in page", no_sideways_scroll(pg))
    time.sleep(4)
    j.shot("landing")
    pg.mouse.wheel(0, 700)
    time.sleep(1.5)
    j.check("sign-in form reachable below the preview", pg.get_by_role("button", name="Sign in").first.is_visible()
            or pg.get_by_role("button", name="Continue without an account").first.is_visible())
    enter(j, 1)
    j.say("Clinic dashboard on a phone")
    j.check("dashboard loads on a phone", pg.locator("text=need you today").count() > 0)
    j.check("no sideways scrolling on the dashboard", no_sideways_scroll(pg))
    j.shot("today")
    pg.mouse.wheel(0, 900)
    time.sleep(1.5)
    j.shot("board")
    menu = pg.locator("[data-testid=stTopNavLinkContainer] a").count()
    j.check("menu still reachable on a phone", menu > 0 or pg.locator("[data-testid=stExpandSidebarButton], [data-testid=stSidebarCollapsedControl]").count() > 0)
