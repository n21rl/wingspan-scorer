import streamlit as st
from data_manager import load_players, load_config, save_config

# Page title
st.title("Settings")

# Load current config
config = load_config()
players = load_players()

# Settings Form
st.header("Default Game Settings")
selected_players = st.multiselect("Select Players", players['Player'], default=config["selected_players"])
cards_used = st.multiselect("Cards Used", ["Base Game", "Europe", "Oceania", "Asia"], default=config["cards_used"])
duet_enabled = st.checkbox("Duet", value=config["duet_enabled"])
nectar_enabled = st.checkbox("Nectar", value=config["nectar_enabled"])
entry_mode = st.radio("Default Score Entry Mode", ["Player-by-Player", "Rubric-by-Rubric"], index=0 if config.get("entry_mode") == "Player-by-Player" else 1)

# Button to save selected settings as default in config.csv
if st.button("Save as Default"):
    save_config({
        "selected_players": selected_players,
        "cards_used": cards_used,
        "duet_enabled": duet_enabled,
        "nectar_enabled": nectar_enabled,
        "entry_mode": entry_mode
    })
    st.success("Default settings saved.")
