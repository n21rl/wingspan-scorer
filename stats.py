import streamlit as st
from data_manager import load_scores  # Import load_scores from data_manager

def show_stats():
    st.title("Game Statistics")
    scores = load_scores()
    if not scores.empty:
        st.subheader("Historical Game Data")
        st.dataframe(scores)
    else:
        st.warning("No game data available.")

show_stats()
