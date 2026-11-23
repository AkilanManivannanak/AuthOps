"""Record the product demo from the real app: video, README GIF and screenshots.

    python scripts/record_demo.py              # starts the app locally, records, writes docs/media/

Everything shown is the app running for real (same code as the live deployment) in a browser driven
by Playwright. Outputs:
    docs/media/demo.mp4    full tour (H.264)
    docs/media/demo.gif    shorter loop for the README
    docs/media/*.png       stills used in the README
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs" / "media"
PORT = 8599
W, H = 1440, 900


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "imageio-ffmpeg"])
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()


def wait_port(port: int, timeout: float = 90) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError("the app did not start")


def main() -> None:
    import streamlit
    from playwright.sync_api import sync_playwright

    want = next((ln.split("==")[1].strip() for ln in (ROOT / "requirements.txt").read_text().splitlines()
                 if ln.startswith("streamlit==")), None)
    if want and streamlit.__version__ != want:
        sys.exit(f"Streamlit {streamlit.__version__} is installed but the app needs {want}. "
                 f"Run: pip install streamlit=={want}")

    MEDIA.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, AUTHOPS_USERDB=str(Path(tempfile.mkdtemp()) / "demo.db"), DATABASE_URL="")
    app = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "streamlit_app.py", "--server.headless", "true",
                            "--server.port", str(PORT), "--browser.gatherUsageStats", "false"],
                           cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    vid_dir = Path(tempfile.mkdtemp())
    try:
        wait_port(PORT)
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(vid_dir),
                                record_video_size={"width": W, "height": H}, device_scale_factor=1)
            pg = ctx.new_page()
            base = f"http://127.0.0.1:{PORT}"

            def go(path: str, settle: float = 4):
                pg.goto(base + path)
                pg.wait_for_selector("h1", timeout=60_000)
                time.sleep(settle)

            def shot(name: str):
                pg.screenshot(path=str(MEDIA / f"{name}.png"))

            def scroll_to(text: str):
                pg.get_by_text(text, exact=False).first.scroll_into_view_if_needed()
                time.sleep(1.2)

            def slow_scroll(px: int, steps: int = 12):
                for _ in range(steps):
                    pg.mouse.wheel(0, px / steps)
                    time.sleep(0.08)

            # 1. home: a request through the whole pipeline
            go("/", 5)
            try:
                pg.get_by_role("button", name="Run a request").wait_for(timeout=30_000)
            except Exception:
                pg.screenshot(path=str(MEDIA / "_debug.png"), full_page=True)
                sys.exit("The home page did not show the Run button. See docs/media/_debug.png; page text:\n"
                         + pg.inner_text("body")[:1500])
            # the care board: let weeks play, scrub past the policy change, open a care pass
            try:
                fl = pg.frame_locator("iframe").first
                fl.locator("tr.row").first.wait_for(timeout=20_000)
                time.sleep(6)
                hist = fl.locator("#hist")
                box = hist.bounding_box()
                for f in (0.45, 0.55, 0.65):  # drag the timeline forward
                    pg.mouse.click(box["x"] + box["width"] * f, box["y"] + 30)
                    time.sleep(1.2)
                fl.locator("#ribbon").click()
                time.sleep(1.5)
                fl.locator("tr.row").first.click()
                time.sleep(3)
                pg.screenshot(path=str(MEDIA / "board.png"))
            except Exception as e:
                print("board scene skipped:", e)
            pg.get_by_role("button", name="Run a request").scroll_into_view_if_needed()
            pg.get_by_role("button", name="Run a request").click()
            pg.get_by_text("Rules:", exact=False).first.wait_for(timeout=60_000)
            time.sleep(4)
            slow_scroll(500)
            time.sleep(1.5)
            shot("home")
            # same, with a documentation gap: caught before the payor
            slow_scroll(-500)
            pg.get_by_text("Inject a documentation gap").click()
            time.sleep(1)
            pg.get_by_role("button", name="Run a request").click()
            pg.get_by_text("Rules: blocked", exact=False).first.wait_for(timeout=60_000)
            time.sleep(3)
            def scene(name, fn):
                try:
                    fn()
                except Exception as e:  # keep recording; report which scene failed
                    pg.screenshot(path=str(MEDIA / f"_failed_{name}.png"))
                    print(f"scene '{name}' failed: {str(e).splitlines()[0]}  (see docs/media/_failed_{name}.png)")

            # 2. browser agent, live on a portal
            def agent():
                go("/agent_theater")
                pg.get_by_role("button", name="Run the agent").click(timeout=20_000)
                time.sleep(14)
                shot("agent")
            scene("agent", agent)
            # 3. approval outlook and policy drift
            def outlook():
                go("/denial_shield", 6)
                scroll_to("Approval outlook")
                slow_scroll(250)
                time.sleep(2)
                shot("outlook")
                scroll_to("Policy drift monitor")
                slow_scroll(600, 16)
                time.sleep(2)
                shot("drift")
            scene("outlook", outlook)
            # 4. self-healing playbook on a portal redesign
            def heal():
                go("/playbook_studio")
                scroll_to("Portal release watch")
                pg.get_by_text("Redesigned form", exact=False).first.click()
                time.sleep(1)
                pg.get_by_role("button", name="Run canary").click()
                pg.get_by_text("Candidate verified", exact=False).first.wait_for(timeout=60_000)
                slow_scroll(350)
                time.sleep(2)
                shot("heal")
            scene("heal", heal)
            # 5. appeal packet with verified citations
            def appeal():
                go("/cases_api")
                pg.get_by_role("tab", name="Appeals").click()
                time.sleep(2.5)
                slow_scroll(300)
                time.sleep(2)
                shot("appeal")
            scene("appeal", appeal)
            ctx.close()
            b.close()
        webm = next(vid_dir.glob("*.webm"))
        ff = ffmpeg()
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(MEDIA / "demo.mp4")], check=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(MEDIA / "demo.mp4"), "-vf",
                        "fps=8,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer",
                        "-t", "45", str(MEDIA / "demo.gif")], check=True)
        for f in sorted(MEDIA.iterdir()):
            print(f"{f.name:12s} {f.stat().st_size / 1e6:.1f} MB")
    finally:
        app.terminate()


if __name__ == "__main__":
    main()
