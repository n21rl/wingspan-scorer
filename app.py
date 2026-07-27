"""Wingspan score tracker -- navigation shell.

Run with:  streamlit run app.py
"""

import streamlit as st

st.set_page_config(
    page_title="Wingspan Scores",
    page_icon="🐦",
    layout="centered",  # centred beats wide on a phone
    initial_sidebar_state="collapsed",
)

# Phone-first chrome. The 16px input size is not cosmetic: below 16px, iOS
# Safari zooms the viewport when a field takes focus and never zooms back out.
st.html(
    """
    <style>
      [data-testid="stHeaderActionElements"] { display: none; }
      button[title="View fullscreen"] { visibility: hidden; }

      .stTextInput input,
      .stNumberInput input,
      .stDateInput input,
      .stTextArea textarea { font-size: 16px !important; }

      /* stButtonGroup is what st.segmented_control renders as. */
      .stButton button,
      .stFormSubmitButton button,
      [data-testid="stButtonGroup"] button {
        min-height: 44px;                 /* comfortable tap target */
        font-size: 15px;
      }

      /* Placement pickers should fill the row so each option is a wide target. */
      [data-testid="stButtonGroup"] { width: 100%; }
      [data-testid="stButtonGroup"] > div { width: 100%; display: flex; }
      [data-testid="stButtonGroup"] button { flex: 1 1 0; }

      .block-container { padding-top: 2.6rem; padding-bottom: 4rem; }
    </style>
    """
)

pages = [
    st.Page(
        "views/enter_scores.py",
        title="Enter scores",
        icon=":material/edit_note:",
        default=True,
    ),
    st.Page("views/insights.py", title="Insights", icon=":material/insights:"),
    st.Page("views/history.py", title="History", icon=":material/history:"),
    st.Page("views/players.py", title="Players", icon=":material/group:"),
    st.Page("views/settings.py", title="Settings", icon=":material/settings:"),
]

st.navigation(pages, position="top").run()
