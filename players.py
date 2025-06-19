import streamlit as st
import pandas as pd
import os
import uuid  # For generating unique IDs
from data_manager import load_players, save_players
from css import hide_anchor_links, hide_fullscreen_buttons

hide_anchor_links()
hide_fullscreen_buttons()

# Directory for storing uploaded images
IMAGES_DIR = 'images'
os.makedirs(IMAGES_DIR, exist_ok=True)

def manage_players():
    st.title("Players")

    # Load players
    players = load_players()

    # Function to handle player editing in a dialog
    @st.dialog("Edit Player")
    def edit_player_dialog(player_id):
        edit_data = players[players['Player ID'] == player_id].iloc[0]

        with st.form(key=f"edit_player_{player_id}", enter_to_submit=False):
            player_name = st.text_input("Player Name", value=edit_data['Player'])
            player_color = st.color_picker("Player Color", value=edit_data['Color'])

            col1, col2 = st.columns([3, 1])
            with col1:
                player_picture = st.file_uploader("Player Picture", type=['png', 'jpg'])
            with col2:
                st.text("")
                st.text("")
                path = edit_data['Picture']
                if not(isinstance(picture_path, str) and os.path.exists(picture_path)):
                    path = "images/_default.png"
                st.image(picture_path, width=80, caption="Current Picture")

            if st.form_submit_button("Save"):
                if player_name:
                    # Save new picture with unique ID if uploaded
                    new_picture_path = path
                    if player_picture is not None:
                        new_picture_path = os.path.join(IMAGES_DIR, f"{player_id}_{player_picture.name}")
                        with open(new_picture_path, 'wb') as f:
                            f.write(player_picture.getbuffer())

                    # Update the player data in the DataFrame
                    players.loc[players['Player ID'] == player_id, ['Player', 'Color', 'Picture']] = [
                        player_name, player_color, new_picture_path
                    ]

                    save_players(players)
                    st.success(f"Player '{player_name}' updated!")
                    st.rerun()  # Refresh to show updates
                else:
                    st.warning("Please enter a valid player name.")

    # Function to handle player deletion confirmation
    @st.dialog("Delete Player")
    def delete_player_dialog(player_id):
        player_name = players[players['Player ID'] == player_id]['Player'].values[0]
        st.subheader(f"Are you sure you want to delete {player_name}?")
        if st.button("Yes"):
            # Perform deletion
            players.drop(players[players['Player ID'] == player_id].index, inplace=True)  # Remove player
            save_players(players)  # Save changes
            st.success(f"Player {player_name} deleted!")
            st.rerun()  # Refresh to show updates

    # Function to create a new player
    @st.dialog("Create New Player")
    def create_player_dialog():
        nonlocal players  # Access the outer scope variable
        with st.form(key="create_player", enter_to_submit=False):
            new_player_name = st.text_input("Player Name")
            new_player_color = st.color_picker("Player Color")
            new_player_picture = st.file_uploader("Player Picture", type=['png', 'jpg'])

            if st.form_submit_button("Create"):
                if new_player_name:
                    player_id = str(uuid.uuid4())  # Generate a unique ID
                    new_picture_path = None
                    if new_player_picture is not None:
                        new_picture_path = os.path.join(IMAGES_DIR, f"{player_id}_{new_player_picture.name}")
                        with open(new_picture_path, 'wb') as f:
                            f.write(new_player_picture.getbuffer())

                    # Create a new DataFrame for the new player
                    new_player_data = pd.DataFrame({
                        'Player ID': [player_id],
                        'Player': [new_player_name],
                        'Color': [new_player_color],
                        'Picture': [new_picture_path]
                    })

                    # Use pd.concat to append the new player
                    players = pd.concat([players, new_player_data], ignore_index=True)
                    save_players(players)
                    st.success(f"Player '{new_player_name}' created!")
                    st.rerun()  # Refresh to show updates
                else:
                    st.warning("Please enter a valid player name.")

    # Display current players
    if not players.empty:  # Check if there are players
        for _, row in players.iterrows():
            col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])

            with col1:
                st.markdown(
                    f"<div style='font-size: 20px; text-align: left; height: 60; display: flex; align-items: center;'>{row['Player']}</div>",
                    unsafe_allow_html=True
                )

            # Display color as a static box
            with col2:
                color_box_html = f"""
                    <div style='
                        background-color: {row['Color']};
                        width: 40px;
                        height: 40px;
                        display: inline-block;
                        border-radius: 8px;
                    '></div>
                """
                st.markdown(color_box_html, unsafe_allow_html=True)

            with col3:
                picture_path = row['Picture']
                if isinstance(picture_path, str) and os.path.exists(picture_path):
                    st.image(picture_path, width=40)
                else:
                    st.image("images/_default.png", width=40)

            with col4:
                if st.button("Edit", key=f"edit_{row['Player ID']}"):
                    edit_player_dialog(row['Player ID'])

            with col5:
                if st.button("Delete", key=f"delete_{row['Player ID']}"):
                    delete_player_dialog(row['Player ID'])

    # Button to open the Create New Player dialog
    if st.button("Create New Player"):
        create_player_dialog()

# Call the main function
manage_players()
