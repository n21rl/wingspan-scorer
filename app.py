import streamlit as st

# Set the overall page configuration for the app
st.set_page_config(page_title="Wingspan Score Tracker", page_icon="🐦")

# Define pages with st.Page
players_page = st.Page("players.py", title="Players", icon=":material/group:")
enter_scores_page = st.Page("enter_scores.py", title="Enter scores", icon=":material/edit_note:") 
stats_page = st.Page("stats.py", title="Stats", icon=":material/bar_chart:")
settings_page = st.Page("settings.py", title="Settings", icon=":material/settings:")


# Create navigation
pg = st.navigation([enter_scores_page, stats_page, players_page, settings_page])

# Run the selected page
pg.run()
