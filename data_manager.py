# data_manager.py
import pandas as pd
import os

# Load player profiles from CSV
def load_players():
    if os.path.exists('data/players.csv'):
        return pd.read_csv('data/players.csv')
    else:
        return pd.DataFrame(columns=['Player', 'Color', 'Picture'])


# Save player profiles to CSV
def save_players(profiles):
    profiles.to_csv('data/players.csv', index=False)


# Load scores from CSV
def load_scores():
    if os.path.exists('data/scores.csv'):
        return pd.read_csv('data/scores.csv')
    else:
        return pd.DataFrame(columns=['Game_ID', 'Date', 'Players', 'Scores', 'Cards_Used', 'Duet', 'Nectar'])


# Save scores to CSV
def save_scores(scores):
    scores.to_csv('data/scores.csv', index=False)


# Load default settings from config.csv
def load_config():
    try:
        config_df = pd.read_csv("data/config.csv")
        config = config_df.iloc[0].to_dict()

        # Parse specific fields into lists and booleans
        config["selected_players"] = config["selected_players"].split(";") if config["selected_players"] else []
        config["cards_used"] = config["cards_used"].split(";") if config["cards_used"] else []
        config["duet_enabled"] = str(config.get("duet_enabled", "False")).strip().lower() == "true"
        config["nectar_enabled"] = str(config.get("nectar_enabled", "False")).strip().lower() == "true"

        config["entry_mode"] = config.get("entry_mode", "Player-by-Player")
        if config["entry_mode"] not in ["Player-by-Player", "Rubric-by-Rubric"]:
            config["entry_mode"] = "Player-by-Player"

        return config
    except (FileNotFoundError, IndexError):
        # Return defaults if the config file is missing or empty
        return {
            "selected_players": [],
            "cards_used": [],
            "duet_enabled": False,
            "nectar_enabled": False,
            "entry_mode": "Player-by-Player"
        }

# Save settings to config.csv
def save_config(config):
    config_df = pd.DataFrame([{
        "selected_players": ";".join(config.get("selected_players", [])),
        "cards_used": ";".join(config.get("cards_used", [])),
        "duet_enabled": str(config.get("duet_enabled", False)),
        "nectar_enabled": str(config.get("nectar_enabled", False)),
        "entry_mode": str(config.get("entry_mode", "Rubric-by-Rubric"))
    }])
    config_df.to_csv("data/config.csv", index=False)
