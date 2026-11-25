"""Recorded end-to-end UI journeys against a running AuthOps app.

    streamlit run streamlit_app.py --server.port 8611        # in one terminal
    python tests_ui/run_all.py                               # in another

Each journey records a video and a JSON of its checks into tests_ui/runs/. AUTHOPS_URL points it at another
address (for example the deployed app)."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("AUTHOPS_URL", "http://localhost:8611")
OUT = Path(os.environ.get("AUTHOPS_UI_OUT", Path(__file__).resolve().parent / "runs"))
OUT.mkdir(parents=True, exist_ok=True)
CHROME = os.environ.get("AUTHOPS_CHROME") or ("/usr/bin/google-chrome" if Path("/usr/bin/google-chrome").exists() else None)
BAN = re.compile(r"anthropic|claude|openai|synthetic|fictional|haiku|sonnet|traceback", re.I)


class Journey:
    def __init__(self, name, viewport=(1440, 900)):
        self.name, self.viewport, self.checks, self.t0 = name, viewport, [], time.time()
        self.vid = OUT / f"video_{name}"
        self.vid.mkdir(exist_ok=True)

    def __enter__(self):
        self.p = sync_playwright().start()
        self.b = self.p.chromium.launch(args=["--no-sandbox"], slow_mo=120, **({"executable_path": CHROME} if CHROME else {}))
        w, h = self.viewport
        self.ctx = self.b.new_context(viewport={"width": w, "height": h}, record_video_dir=str(self.vid),
                                      record_video_size={"width": w, "height": h})
        self.pg = self.ctx.new_page()
        self.errors = []
        self.pg.on("pageerror", lambda e: self.errors.append(str(e)[:160]))
        self.pg.on("console", lambda m: self.errors.append("console: " + m.text[:160]) if m.type == "error"
                   and "favicon" not in m.text and "Failed to load resource" not in m.text else None)
        return self

    # -------------------------------------------------------------- narration shown in the recording
    def say(self, text):
        self.pg.evaluate("""t => {let d=document.getElementById('__cap');if(!d){d=document.createElement('div');d.id='__cap';
          d.style.cssText='position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:2147483647;background:#1E0525;color:#fff;'+
          'font:600 15px system-ui;padding:10px 18px;border-radius:999px;box-shadow:0 10px 30px rgba(0,0,0,.35);pointer-events:none;max-width:90%';
          document.body.appendChild(d)} d.textContent=t}""", text)
        time.sleep(1.1)

    def check(self, what, ok, detail=""):
        self.checks.append({"check": what, "pass": bool(ok), "detail": str(detail)[:200]})
        print(("PASS " if ok else "FAIL ") + what + (f"  ({detail})" if detail else ""), flush=True)
        try:
            self.say(("✓ " if ok else "✗ ") + what)
        except Exception:
            pass

    def shot(self, name):
        self.pg.screenshot(path=str(OUT / f"{self.name}_{name}.png"))

    def text(self):
        t = self.pg.inner_text("body")
        for f in self.pg.frames[1:]:
            try:
                t += "\n" + f.inner_text("body")
            except Exception:
                pass
        return t

    def wait_idle(self, extra=1.0, timeout=60):
        """Wait until Streamlit has stopped running the script."""
        t0 = time.time()
        time.sleep(0.6)
        while time.time() - t0 < timeout:
            if not self.pg.locator("[data-testid=stStatusWidget]").count():
                break
            time.sleep(0.4)
        time.sleep(extra)

    def btn(self, name, exact=False, nth=0):
        return self.pg.get_by_role("button", name=name, exact=exact).nth(nth)

    def nav(self, title):
        self.pg.locator("[data-testid=stTopNavLinkContainer] a", has_text=title).first.click()
        self.wait_idle(2)

    def tile(self, label):
        return int(self.pg.locator(f"text={label}").first.locator("xpath=..").inner_text().split()[0])

    def banned(self):
        return sorted(set(m.lower() for m in BAN.findall(self.text())))

    def __exit__(self, *exc):
        if exc[0]:
            self.check(f"journey ran to the end ({exc[0].__name__}: {str(exc[1])[:120]})", False)
            try:
                self.shot("failure")
            except Exception:
                pass
        self.check("no page errors", not self.errors, "; ".join(self.errors[:3]))
        time.sleep(1.5)
        self.ctx.close()
        self.b.close()
        self.p.stop()
        webm = max(self.vid.glob("*.webm"), key=lambda p: p.stat().st_mtime)
        mp4 = OUT / f"{self.name}.mp4"
        ff = shutil.which("ffmpeg")
        if not ff:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
        res = {"journey": self.name, "seconds": round(time.time() - self.t0), "checks": self.checks, "video": mp4.name}
        (OUT / f"result_{self.name}.json").write_text(json.dumps(res, indent=1))
        print(f"{self.name}: {sum(c['pass'] for c in self.checks)}/{len(self.checks)} passed -> {mp4}", flush=True)
        return True


def enter(j, role_index, account=None):
    """From the sign-in page into the app, as a guest or with a new account."""
    pg = j.pg
    pg.goto(BASE + "/")
    j.wait_idle(4)
    if account:
        pg.get_by_role("tab", name="Create account").click()
        time.sleep(0.6)
        f = pg.locator("[data-testid=stForm]").nth(1)
        f.get_by_label("Your name").fill(account["name"])
        f.get_by_label("Email").fill(account["email"])
        f.get_by_label("Password (8+ characters)").fill(account["password"])
        f.get_by_role("button", name="Create account").click()
    else:
        j.btn("Continue without an account").click()
    j.wait_idle(3)
    j.btn("Continue", exact=True, nth=role_index).click()
    j.wait_idle(4)


if __name__ == "__main__":
    print("helpers only", file=sys.stderr)
