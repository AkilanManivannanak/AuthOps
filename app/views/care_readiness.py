import streamlit as st

from app.floor import operations_floor
from app.ui import asset_json, setup
from app.widgets.pulse import pulse
from authops.sim.floor import build as build_floor

setup("Prior auths, cleared before care starts")


@st.cache_data(show_spinner="Running 26 weeks of requests through the pipeline")
def _floor():
    return asset_json("floor.json") or build_floor()  # precomputed by scripts/build_app_assets.py


floor = _floor()
pulse(floor)
st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)
operations_floor(floor, compact=True)

c1, c2, c3 = st.columns(3)
c1.page_link("app/views/try_it.py", label="Try it on your own letter or plan", icon=":material/arrow_forward:")
c2.page_link("app/views/prior_authorizations.py", label="Follow one patient from fax to approval", icon=":material/arrow_forward:")
c3.page_link("app/views/measured.py", label="How these numbers were measured", icon=":material/arrow_forward:")
