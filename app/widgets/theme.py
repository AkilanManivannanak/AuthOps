"""Shared CSS for the components, in Silna's palette."""
from app.tokens import css_vars

BASE_CSS = """
""" + css_vars(":host") + """
*{box-sizing:border-box}
.root{font-family:'DM Sans',system-ui,sans-serif;color:var(--ink);font-size:14px}
.serif{font-family:Fraunces,Georgia,serif;font-weight:400;letter-spacing:-.02em}
.eyebrow{font:500 10.5px 'DM Sans',sans-serif;letter-spacing:.13em;text-transform:uppercase;color:var(--muted)}
.btn{border:0;background:var(--ink);color:#fff;font:600 13px 'DM Sans',sans-serif;padding:9px 18px;border-radius:999px;cursor:pointer;
 transition:transform .15s,background .15s}
.btn:hover{transform:translateY(-1px);background:var(--plum)}.btn.ghost{background:#fff;color:var(--ink);border:1px solid var(--sand)}
.btn.ghost:hover{background:var(--cream)}
.card{background:#fff;border:1px solid var(--sand);border-radius:18px}
.pill{display:inline-flex;align-items:center;gap:6px;font:600 11px 'DM Sans',sans-serif;padding:3px 9px;border-radius:999px;white-space:nowrap}
.pill:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.kbd{font:600 10.5px ui-monospace,monospace;border:1px solid var(--sand);border-bottom-width:2px;border-radius:5px;padding:1px 5px;background:#fff}
@keyframes land{from{opacity:0;transform:scale(1.35)}to{opacity:1;transform:none}}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
"""
