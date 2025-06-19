import streamlit as st
import pandas as pd
from datetime import datetime
import uuid
from data_manager import load_players, load_scores, save_scores, load_config

# Load config for defaults
config = load_config()

# Initialize session state variables
if "game_started" not in st.session_state:
    st.session_state["game_started"] = False
if "displaying_results" not in st.session_state:
    st.session_state["displaying_results"] = False
if "game_scores" not in st.session_state:
    st.session_state["game_scores"] = []
if "current_player_idx" not in st.session_state:
    st.session_state["current_player_idx"] = 0


# Function to handle starting the game
def start_game(players, cards, duet, nectar, date, mode):
    st.session_state["game_started"] = True
    st.session_state["game_id"] = str(uuid.uuid4())
    st.session_state["game_date"] = date.strftime("%Y-%m-%d")
    st.session_state["selected_players"] = players
    st.session_state["cards_used"] = cards
    st.session_state["duet_enabled"] = duet
    st.session_state["nectar_enabled"] = nectar
    st.session_state["entry_mode"] = mode
    st.session_state["current_player_idx"] = 0
    st.session_state["game_scores"] = []
    st.session_state["rubric_idx"] = 0
    st.session_state["partial_scores"] = {p: {} for p in selected_players}


# Callback for submitting player scores
def submit_score_callback(player_name, bird_points, bonus_cards_points, end_goal_points, egg_points, food_points, tucked_points, duet_points, nectar_points):
    total_score = bird_points + bonus_cards_points + end_goal_points + egg_points + food_points + tucked_points + duet_points + nectar_points
    st.session_state["game_scores"].append({
        "Game ID": st.session_state["game_id"],
        "Game Date": st.session_state["game_date"],
        "Player": player_name,
        "Birds": birds,
        "Bonus Cards": bonus_cards_points,
        "End-of-Round Goals": end_goal_points,
        "Eggs": egg_points,
        "Food on Cards": food_points,
        "Tucked Cards": tucked_points,
        "Duet Tokens": duet_points,
        "Nectar": nectar_points,
        "Total Score": total_score,
    })
    if st.session_state["current_player_idx"] < len(st.session_state["selected_players"]) - 1:
        st.session_state["current_player_idx"] += 1
    else:
        st.session_state["game_started"] = False
        st.session_state["displaying_results"] = True
    st.rerun()


# Function to display game results
def display_results():
    st.header("Game Results")
    scores_df = pd.DataFrame(st.session_state["game_scores"])
    st.dataframe(scores_df)
    max_score = scores_df["Total Score"].max()
    winners = scores_df[scores_df["Total Score"] == max_score]["Player"].tolist()
    if len(winners) == 1:
        st.success(f"The winner is {winners[0]} with {max_score} points!")
    else:
        st.success(f"It's a tie! The winners are {', '.join(winners)} with {max_score} points each.")
    all_scores = load_scores()
    all_scores = pd.concat([all_scores, scores_df], ignore_index=True)
    save_scores(all_scores)
    if st.button("Start New Game"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


# Step 1: Game Settings Form
if not st.session_state["game_started"] and not st.session_state["displaying_results"]:
    st.header("Game Settings")
    with st.form(key="game_settings_form"):
        game_date = st.date_input("Game Date", datetime.now())
        selected_players = st.multiselect("Select Players", load_players()['Player'], default=config["selected_players"])
        cards_used = st.multiselect("Cards Used", ["Base Game", "Europe", "Oceania", "Asia"], default=config["cards_used"])
        duet_enabled = st.checkbox("Duet", value=config["duet_enabled"])
        nectar_enabled = st.checkbox("Nectar", value=config["nectar_enabled"])

        entry_options = ["Player-by-Player", "Rubric-by-Rubric"]
        default_mode = config.get("entry_mode", "Player-by-Player")
        default_index = entry_options.index(default_mode) if default_mode in entry_options else 0

        entry_mode = st.radio("Score Entry Mode", entry_options, index=default_index)

        start_game_button = st.form_submit_button("Start Game")
        if start_game_button:
            start_game(selected_players, cards_used, duet_enabled, nectar_enabled, game_date, entry_mode)
            st.rerun()


# Step 2: Score Entry (Two Modes)
if st.session_state["game_started"] and not st.session_state["displaying_results"]:
    if st.session_state["entry_mode"] == "Player-by-Player":
        player = st.session_state["selected_players"][st.session_state["current_player_idx"]]
        duet_enabled = st.session_state["duet_enabled"]
        nectar_enabled = st.session_state["nectar_enabled"]
        st.header(f"Enter Scores for {player}")
        with st.form(key=f"score_entry_form_{player}"):
            birds = st.number_input("Birds", min_value=0)
            bonus_cards = st.number_input("Bonus Cards", min_value=0)
            end_goals = st.number_input("End-of-Round Goals", min_value=0)
            eggs = st.number_input("Eggs", min_value=0)
            food = st.number_input("Food on Cards", min_value=0)
            tucked = st.number_input("Tucked Cards", min_value=0)
            duet_tokens = st.number_input("Duet Tokens", min_value=0) if duet_enabled else 0
            nectar = st.number_input("Nectar", min_value=0) if nectar_enabled else 0
            col1, col2 = st.columns([2, 1])
            with col1:
                cancel_button = st.form_submit_button("Cancel Game")
            with col2:
                submit_button = st.form_submit_button("Submit Score")
            if submit_button:
                submit_score_callback(player, birds, bonus_cards, end_goals, eggs, food, tucked, duet_tokens, nectar)
            if cancel_button:
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
    else:
        duet_enabled = st.session_state["duet_enabled"]
        nectar_enabled = st.session_state["nectar_enabled"]
        rubrics = ["Birds", "Bonus Cards", "End-of-Round Goals", "Eggs", "Food on Cards", "Tucked Cards"]
        if duet_enabled:
            rubrics.append("Duet Tokens")
        if nectar_enabled:
            rubrics.append("Nectar")
        current_rubric = rubrics[st.session_state["rubric_idx"]]
        st.header(f"Enter scores for: {current_rubric}")
        with st.form(key=f"rubric_form_{current_rubric}"):
            for player in st.session_state["selected_players"]:
                score = st.number_input(f"{player}", min_value=0, key=f"{current_rubric}_{player}")
                st.session_state["partial_scores"][player][current_rubric] = score
            col1, col2 = st.columns([2, 1])
            with col1:
                cancel_button = st.form_submit_button("Cancel Game")
            with col2:
                next_button = st.form_submit_button("Next")

            if next_button:
                st.session_state["rubric_idx"] += 1
                if st.session_state["rubric_idx"] >= len(rubrics):
                    for player, scores in st.session_state["partial_scores"].items():
                        total = sum(scores.values())
                        st.session_state["game_scores"].append({
                            "Game ID": st.session_state["game_id"],
                            "Game Date": st.session_state["game_date"],
                            "Player": player,
                            "Birds": scores.get("Birds", 0),
                            "Bonus Cards": scores.get("Bonus Cards", 0),
                            "End-of-Round Goals": scores.get("End-of-Round Goals", 0),
                            "Eggs": scores.get("Eggs", 0),
                            "Food on Cards": scores.get("Food on Cards", 0),
                            "Tucked Cards": scores.get("Tucked Cards", 0),
                            "Duet Tokens": scores.get("Duet Tokens", 0),
                            "Nectar": scores.get("Nectar", 0),
                            "Total Score": total,
                        })
                    st.session_state["game_started"] = False
                    st.session_state["displaying_results"] = True
                st.rerun()
            if cancel_button:
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()


# Step 3: Display Results
if st.session_state["displaying_results"]:
    display_results()
