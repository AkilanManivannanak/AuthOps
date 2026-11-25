import streamlit as st

from app.ui import run_view, setup, switch

setup("Prior authorizations")

TOOLS = {
    "Work a request": (None, ""),
    "Read a document": ("app/views/document_lab.py", "Fax any sample letter or plan through the reader and correct what it got wrong."),
    "Check a request": ("app/views/denial_shield.py", "Build any request and see the payor's rules and the approval outlook react."),
    "Watch the browser agent": ("app/views/agent_theater.py", "Run the agent on a test portal, or replay recorded runs."),
    "Appeal a denial": ("app/views/appeals.py", "Triage a denial, then draft the appeal only from quotes in the chart."),
    "Channels": ("app/views/channels.py", "The same request as a FHIR bundle, a portal form or a phone call."),
}
pick = switch(TOOLS, "tool")
path, purpose = TOOLS[pick]
if path is None:
    from app.journey import journey

    journey()
else:
    st.caption(purpose)
    run_view(path)
