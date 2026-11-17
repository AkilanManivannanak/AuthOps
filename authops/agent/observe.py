"""Page observation: a compact, model-readable snapshot of interactive elements.

The snapshot walks every frame (Keystone's form lives in an iframe), labels each
interactive element the way a human would read it, and marks elements that are
visible but covered by something else, which is how hidden pop-ups show up before
they eat a click. A state hash over the snapshot feeds loop detection.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

SNAPSHOT_JS = r"""
() => {
  const out = [];
  const labelFor = (el) => {
    if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`); if (l) return l.innerText.trim(); }
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const wrap = el.closest('label'); if (wrap) return wrap.innerText.trim();
    if (el.placeholder) return el.placeholder;
    if (['BUTTON','A'].includes(el.tagName)) return el.innerText.trim();
    return el.name || el.id || '';
  };
  const els = document.querySelectorAll('input,select,textarea,button,a[href],[role=button],.cal-day');
  els.forEach((el, i) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'
                    && !(el.type === 'hidden');
    let occluded = false;
    if (visible && r.top >= 0 && r.top < innerHeight) {
      const t = document.elementFromPoint(r.left + r.width/2, r.top + Math.min(r.height/2, 8));
      occluded = !!t && t !== el && !el.contains(t) && !t.contains(el) && !(t.tagName==='LABEL' && t.contains(el));
    }
    if (!visible && el.type !== 'file') return;
    const o = {i, tag: el.tagName.toLowerCase(), type: el.type || '', id: el.id || '', name: el.name || '',
               label: labelFor(el).slice(0, 80), value: (el.type==='password' ? (el.value?'***':'') : (el.value||'')).slice(0,60),
               occluded};
    if (el.tagName === 'SELECT') o.options = [...el.options].map(x => x.value || x.text).slice(0, 40);
    if (el.type === 'checkbox') o.checked = el.checked;
    if (el.classList.contains('cal-day')) o.day = el.dataset.day;
    out.push(o);
  });
  const dialogs = [...document.querySelectorAll('[role=dialog],.modal')]
     .filter(d => getComputedStyle(d).display !== 'none' && d.getBoundingClientRect().width > 0)
     .map(d => ({id: d.id, text: d.innerText.slice(0, 160)}));
  const errs = [...document.querySelectorAll('.err,#form-error,#login-error')].map(e => e.innerText.trim()).filter(Boolean);
  const heading = (document.querySelector('h1,h2,h3')||{}).innerText || '';
  return {elements: out, dialogs, errors: errs, heading, text: document.body ? document.body.innerText.slice(0, 1500) : ''};
}
"""


@dataclass
class FrameSnap:
    frame_index: int
    url: str
    heading: str
    elements: list[dict]
    dialogs: list[dict]
    errors: list[str]
    text: str


@dataclass
class Observation:
    url: str
    title: str
    status: int | None
    frames: list[FrameSnap] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        return [e for f in self.frames for e in f.errors]

    @property
    def dialogs(self) -> list[dict]:
        return [d for f in self.frames for d in f.dialogs]

    @property
    def heading(self) -> str:
        return " | ".join(f.heading for f in self.frames if f.heading)

    @property
    def text(self) -> str:
        return "\n".join(f.text for f in self.frames)

    def state_hash(self) -> str:
        sig = [(f.url, f.heading, [(e["id"], e["value"]) for e in f.elements], f.errors) for f in self.frames]
        return hashlib.md5(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:12]

    def for_model(self, max_elements: int = 60) -> str:
        """Text rendering the LLM policy reads (no raw HTML, no PHI beyond form values)."""
        lines = [f"URL: {self.url}", f"Title: {self.title}", f"Heading: {self.heading}"]
        if self.status and self.status >= 400:
            lines.append(f"HTTP status: {self.status}")
        if self.errors:
            lines.append("Errors on page: " + " / ".join(self.errors))
        if self.dialogs:
            lines.append("Open dialogs: " + " / ".join(f"#{d['id']}: {d['text'][:80]}" for d in self.dialogs))
        n = 0
        for f in self.frames:
            lines.append(f"-- frame {f.frame_index} ({f.url})")
            for e in f.elements:
                if e.get("day") and n > 20:
                    continue  # calendar days: summarized, the tool handles picking
                desc = f"[{e['tag']}{':' + e['type'] if e['type'] else ''}] id={e['id'] or '-'} label=\"{e['label']}\""
                if e.get("value"):
                    desc += f" value=\"{e['value']}\""
                if e.get("options"):
                    desc += f" options={e['options'][:12]}"
                if e.get("occluded"):
                    desc += " (COVERED by another element)"
                lines.append(desc)
                n += 1
                if n >= max_elements:
                    break
        return "\n".join(lines)


def observe(page, status: int | None = None) -> Observation:
    obs = Observation(url=page.url, title=page.title(), status=status)
    for i, fr in enumerate(page.frames):
        try:
            snap = fr.evaluate(SNAPSHOT_JS)
        except Exception:
            continue
        obs.frames.append(FrameSnap(i, fr.url, snap["heading"], snap["elements"], snap["dialogs"],
                                    snap["errors"], snap["text"]))
    return obs
