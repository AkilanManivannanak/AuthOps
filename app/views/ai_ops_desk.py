import streamlit as st

from app.ui import run_view, setup, switch

setup("AI Ops desk", "Where the automations are reviewed, repaired and given more autonomy only when they earn it.")

TOOLS = {
    "Review": ("app/views/qa_console.py", "Swipe through what the AI read. Your verdicts are scored against the truth."),
    "Playbooks": ("app/views/playbook_studio.py", "The plain-English playbook, the path the agent walks, and repairs after a portal redesign."),
    "Prompt changes": ("app/views/config_lab.py", "Every prompt change runs the regression gate before it ships."),
    "Autonomy": ("app/views/autonomy_ramp.py", "Human review drops only while results hold, and comes back when a portal changes."),
    "Long charts": ("app/views/long_charts.py", "Check a 12 to 150 page chart against the payor's rules, page by page."),
}
pick = switch(TOOLS, "desk")
path, purpose = TOOLS[pick]
st.caption(purpose)
run_view(path)
