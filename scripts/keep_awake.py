"""Open the live app in a real browser so Streamlit Community Cloud counts a visit.

Community Cloud puts an app to sleep after 12 hours without traffic, and a plain HTTP request
does not count. This loads the page in headless Chromium, clicks the wake-up button if the app
is already asleep, and waits until the app itself renders. Run by .github/workflows/keep_awake.yml.

    python scripts/keep_awake.py https://akilan-silna-pa-agent.streamlit.app
"""
from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://akilan-silna-pa-agent.streamlit.app"
# Text that is on the sign-in page whatever its headline says (the headline changed once and broke this check).
MARKERS = ("Continue without an account", "Create account")


def rendered(html: str) -> bool:
    return any(m in html for m in MARKERS)


def main() -> int:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        time.sleep(5)
        wake = page.get_by_role("button", name="Yes, get this app back up!")
        if wake.count():
            print("app was asleep: waking it")
            wake.first.click()
        for _ in range(36):   # up to 6 minutes for a cold start
            if rendered(page.content()):
                print("app is up")
                b.close()
                return 0
            for fr in page.frames:   # the app renders inside an iframe on streamlit.app
                try:
                    if fr != page.main_frame and rendered(fr.content()):
                        print("app is up")
                        b.close()
                        return 0
                except Exception:
                    pass
            time.sleep(10)
        print("app did not render in time")
        b.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
