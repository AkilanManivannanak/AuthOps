"""Plan map: the executable playbook drawn as the path the agent walks, page by page, with your edits
marked against the original."""
from __future__ import annotations

import difflib
import json

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
.cnt{font:400 26px Fraunces,Georgia,serif}.cnt small{font:500 12px 'DM Sans',system-ui,sans-serif;color:var(--muted);margin-left:6px}
.flow{display:flex;gap:14px;overflow-x:auto;padding:4px 2px 12px;align-items:flex-start}
.pgc{min-width:250px;max-width:290px;flex:1;padding:12px 12px 8px;position:relative;transition:box-shadow .2s,transform .2s}
.pgc.cur{transform:translateY(-3px);box-shadow:0 14px 30px -18px rgba(30,5,37,.45);border-color:#8C5FB9}
.pgc:not(:last-child)::after{content:"→";position:absolute;right:-13px;top:18px;color:#8C5FB9;font-size:14px}
.m{font:600 11px 'DM Sans',system-ui,sans-serif;color:#5B2A86;background:#EFE7FA;border-radius:6px;padding:3px 7px;display:inline-block;margin-bottom:8px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.st{display:grid;grid-template-columns:22px 1fr;gap:6px;align-items:start;padding:5px 6px;border-radius:8px;font-size:12px;line-height:1.35;transition:background .2s}
.st i{font-style:normal;width:20px;height:20px;border-radius:6px;display:grid;place-items:center;font-size:11px;background:var(--cream);border:1px solid var(--sand)}
.st b{font-weight:600}.st span{color:var(--muted)}
.st.add{background:#EFFAF1;box-shadow:inset 3px 0 0 #3E8E5A}.st.del{opacity:.6;text-decoration:line-through;box-shadow:inset 3px 0 0 #C0446A}
.st.now{background:#FFE3D8}.st.done i{background:#5B2A86;color:#fff;border-color:#5B2A86}
.sub{margin-left:20px;border-left:2px dashed var(--sand);padding-left:6px}
.legend{display:flex;gap:12px;font-size:11.5px;color:var(--muted)}
"""

JS = r"""
export default function(component){
 const {data,parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,ICON={type_credential:"🔑",fill:"✎",select:"▾",pick_date:"▦",click:"●",upload:"⇪",wait:"◷",answer:"?",conditional:"⑂",read_confirmation:"✓",finish:"■",dismiss:"✕"};
 let id=0;const flat=[];
 const step=(a,cls)=>{const k=id++;if(cls!=="del")flat.push(k);const arg=a.args||{};const tgt=arg.target||arg.user_target||(arg.if_specialty?"if service is "+arg.if_specialty:"")||(arg.ms?arg.ms+" ms":"")||(arg.status||"");
  const val=arg.value?` = ${arg.value}`:arg.iso?` = ${arg.iso}`:"";
  return `<div class="st ${cls||""}" data-k="${k}"><i>${ICON[a.verb]||"·"}</i><div><b>${a.verb.replace(/_/g," ")}</b> ${tgt?`<span>${String(tgt).replace(/</g,"&lt;")}${val.replace(/</g,"&lt;")}</span>`:""}
   ${a.sub?`<div class="sub">${a.sub.map(s=>step(s,cls)).join("")}</div>`:""}</div></div>`};
 const pages=D.pages.map((p,i)=>`<div class="card pgc" data-p="${i}"><div class="m" title="${p.match}">${p.match}</div>${p.steps.map(s=>step(s.a,s.c)).join("")}</div>`).join("");
 const n=flat.length,diff=D.pages.flatMap(p=>p.steps).filter(s=>s.c).length;
 root.innerHTML=`<div class="top"><div class="cnt" id="cnt">${n}<small>actions · plan expects about ${D.expected} steps${diff?` · ${diff} change${diff===1?"":"s"} from the original`:""}</small></div>
  <div class="legend">${diff?`<span style="color:#3E8E5A">▍added or changed</span><span style="color:#C0446A">▍removed</span>`:""}</div>
  <button class="btn" id="walk">Walk the plan</button></div><div class="flow">${pages}</div>`;
 let t=null;root.querySelector("#walk").onclick=()=>{clearInterval(t);const els=root.querySelectorAll(".st:not(.del)");els.forEach(e=>e.classList.remove("done","now"));
  let k=0;t=setInterval(()=>{if(k>0){els[k-1].classList.remove("now");els[k-1].classList.add("done")}if(k>=els.length){clearInterval(t);root.querySelectorAll(".pgc").forEach(p=>p.classList.remove("cur"));return}
   const e=els[k];e.classList.add("now");root.querySelectorAll(".pgc").forEach(p=>p.classList.toggle("cur",p.contains(e)));
   e.closest(".pgc").scrollIntoView({block:"nearest",inline:"nearest",behavior:"smooth"});root.querySelector("#cnt").firstChild.nodeValue=(k+1)+" of "+n;k++},260)};
 return ()=>clearInterval(t);
}
"""

_component = st.components.v2.component("authops_plan_map", css=CSS, js=JS)


def _action(a):
    verb, args = (a[0], a[1] if len(a) > 1 else {}) if isinstance(a, list) else (str(a), {})
    args = args or {}
    out = {"verb": verb, "args": {k: v for k, v in args.items() if k != "actions"}}
    if verb == "conditional":
        out["sub"] = [_action(x) for x in args.get("actions", [])]
    return out


def _ordered(spec):
    pages = list(spec.get("pages", []))
    start = spec.get("start", "")
    first = [p for p in pages if (p.get("match") or {}).get("url") == start]
    last = [p for p in pages if "submitted" in str((p.get("match") or {}).get("text", "")).lower()]
    mid = [p for p in pages if p not in first and p not in last]
    return first + mid + last


def _label(p):
    m = p.get("match") or {}
    return f"url {m['url']}" if "url" in m else f"text '{m.get('text', '')}'" if "text" in m else json.dumps(m)


def plan_map(spec: dict, original: dict, key: str) -> None:
    orig = {_label(p): p for p in _ordered(original)}
    pages = []
    for p in _ordered(spec):
        lab = _label(p)
        new = [_action(a) for a in p.get("actions", [])]
        old = [_action(a) for a in (orig.get(lab) or {}).get("actions", [])] if lab in orig else []
        ns, os_ = [json.dumps(a, sort_keys=True) for a in new], [json.dumps(a, sort_keys=True) for a in old]
        steps = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=os_, b=ns).get_opcodes():
            if tag == "equal":
                steps += [{"a": new[j], "c": ""} for j in range(j1, j2)]
            else:
                steps += [{"a": old[i], "c": "del"} for i in range(i1, i2)]
                steps += [{"a": new[j], "c": "add"} for j in range(j1, j2)]
        pages.append({"match": lab, "steps": steps})
    _component(data={"pages": pages, "expected": spec.get("expected_steps", "?")}, key=key)
