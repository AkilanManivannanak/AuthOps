import streamlit as st

from app.floor import operations_floor
from app.ui import asset_json, setup
from authops.sim.floor import build as build_floor

setup("Prior auths, cleared before care starts",
      "Every patient a clinic sends, from intake to the payor's decision. Replay 26 weeks, filter by any stage, "
      "or open a patient.")


@st.cache_data(show_spinner="Running 26 weeks of requests through the pipeline")
def _floor():
    return asset_json("floor.json") or build_floor()  # precomputed by scripts/build_app_assets.py


operations_floor(_floor())

c1, c2, c3 = st.columns(3)
c1.page_link("app/views/prior_authorizations.py", label="Follow one patient from fax to approval", icon=":material/arrow_forward:")
c2.page_link("app/views/ai_ops_desk.py", label="Review what the AI read", icon=":material/arrow_forward:")
c3.page_link("app/views/measured.py", label="How these numbers were measured", icon=":material/arrow_forward:")
