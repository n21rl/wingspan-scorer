"""Player management."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from views._shared import get_connection, player_chip
from wingspan import avatars, repository
from wingspan.model import Player

conn = get_connection()

st.title("Players")


def avatar_path(player: Player) -> Path | None:
    """The player's picture, the placeholder, or None if neither is present."""
    return avatars.resolve(player.avatar)


def show_avatar(player: Player, width: int, **kwargs) -> None:
    """Render a picture only when there is a file behind it.

    `st.image` opens the path itself and raises MediaFileStorageError if it is
    not there, which takes the whole page down. A deployment that left the
    images out should lose the pictures, not the page.
    """
    path = avatar_path(player)
    if path is not None:
        st.image(str(path), width=width, **kwargs)


def save_avatar(player_id: str, upload) -> str:
    return avatars.save(player_id, upload.name, upload.getbuffer())


@st.dialog("Edit player")
def edit_player(player: Player) -> None:
    with st.form(f"edit_{player.id}", border=False, enter_to_submit=False):
        name = st.text_input("Name", value=player.name)
        color = st.color_picker(
            "Colour", value=player.color, help="Used for this player in every chart."
        )
        upload = st.file_uploader("Picture", type=["png", "jpg", "jpeg"])
        show_avatar(player, width=72, caption="Current")

        archived = st.checkbox(
            "Archived",
            value=player.archived,
            help="Hidden from new games. Their past games are kept.",
        )

        if st.form_submit_button("Save", type="primary", width="stretch"):
            if not name.strip():
                st.error("A player needs a name.")
                return
            player.name = name.strip()
            player.color = color
            player.archived = archived
            if upload is not None:
                player.avatar = save_avatar(player.id, upload)
            repository.save_player(conn, player)
            st.rerun()


@st.dialog("Remove player")
def remove_player(player: Player) -> None:
    played = repository.player_game_count(conn, player.id)
    if played:
        st.write(
            f"**{player.name}** appears in {played} game(s). Deleting them would take that "
            "history with them, so they will be archived instead — hidden from new games, "
            "past games untouched."
        )
        label = "Archive"
    else:
        st.write(f"Delete **{player.name}**? They have not played a game yet.")
        label = "Delete"

    if st.button(label, type="primary", width="stretch"):
        repository.delete_player(conn, player.id)
        st.rerun()


@st.dialog("Add player")
def add_player() -> None:
    with st.form("create_player", border=False, enter_to_submit=False):
        name = st.text_input("Name")
        color = st.color_picker("Colour", value="#2a78d6")
        upload = st.file_uploader("Picture", type=["png", "jpg", "jpeg"])

        if st.form_submit_button("Add", type="primary", width="stretch"):
            if not name.strip():
                st.error("A player needs a name.")
                return
            if repository.get_player_by_name(conn, name.strip()):
                st.error(f"There is already a player called {name.strip()}.")
                return

            player = Player.new(name.strip(), color)
            if upload is not None:
                player.avatar = save_avatar(player.id, upload)
            repository.save_player(conn, player)
            st.rerun()


players = repository.list_players(conn, include_archived=True)
game_counts = repository.game_counts_by_player(conn)

if not players:
    st.caption("No players yet. Add the people you play with to start recording games.")

for player in players:
    with st.container(border=True):
        head, actions = st.columns([3, 2])
        with head:
            show_avatar(player, width=44)
            st.markdown(
                player_chip(f"**{player.name}**", player.color), unsafe_allow_html=True
            )
            played = game_counts.get(player.id, 0)
            suffix = " · archived" if player.archived else ""
            st.caption(f"{played} game(s){suffix}")

        with actions:
            if st.button("Edit", key=f"e_{player.id}", width="stretch"):
                edit_player(player)
            if st.button("Remove", key=f"d_{player.id}", width="stretch"):
                remove_player(player)

if st.button("Add player", type="primary", width="stretch"):
    add_player()
