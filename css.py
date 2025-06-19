import streamlit as st

def hide_anchor_links():
    st.html("<style>[data-testid='stHeaderActionElements'] {display: none;}</style>")
    
def hide_fullscreen_buttons():
    st.html("<style>button[title='View fullscreen'] {visibility: hidden;}</style>")