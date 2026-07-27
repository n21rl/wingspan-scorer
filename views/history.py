"""Game history: review, edit and delete past games."""

from __future__ import annotations

import streamlit as st

from views._shared import empty_state, format_expansions, get_connection, player_chip
from wingspan import catalogue, repository
from wingspan.db import DELETE_GRACE_DAYS
from wingspan.model import ROUNDS

conn = get_connection()

st.title("History")

# A deleted game hangs around for a grace period; this is the undo handle.
# Read rather than pop: a button only handles its own click on the *next* run,
# so clearing the state here would delete the button before it ever fires.
pending = st.session_state.get("deleted_game")
if pending:
    st.warning(f"Deleted the game from {pending['played_on']}.")
    undo, dismiss = st.columns(2)
    if undo.button("Undo", type="primary", width="stretch"):
        repository.restore_game(conn, pending["id"])
        st.session_state.pop("deleted_game", None)
        st.rerun()
    if dismiss.button("Dismiss", width="stretch"):
        st.session_state.pop("deleted_game", None)
        st.rerun()
    st.caption(f"It stays recoverable in Settings for {DELETE_GRACE_DAYS} days.")

games = repository.list_games(conn)
if not games:
    empty_state(
        "No games yet",
        "Once you save a game it shows up here, ready to review or correct.",
        page="views/enter_scores.py",
        label="Enter a game",
    )
    st.stop()

names = {p.id: p for p in repository.players_by_id(conn).values()}

for game in games:
    winners = set(game.winners())
    ordered = sorted(game.scores, key=lambda s: -s.total)
    headline = ", ".join(
        f"{names[s.player_id].name if s.player_id in names else '?'} {s.total}" for s in ordered
    )

    with st.expander(f"{game.played_on:%d %b %Y} · {headline}"):
        st.caption(
            f"{format_expansions(game.expansions)} · {game.goal_side.value} goal board"
            + (f" · {game.notes}" if game.notes else "")
        )

        for score in ordered:
            player = names.get(score.player_id)
            label = player.name if player else "Unknown"
            crown = " 👑" if score.player_id in winners else ""
            st.markdown(
                player_chip(f"**{label}**{crown} — {score.total}", player.color if player else "#4c78a8"),
                unsafe_allow_html=True,
            )
            parts = [
                f"{c.icon} {c.label} {score.get(c.key)}"
                for c in game.categories
                if score.get(c.key)
            ]
            parts.append(f"🏆 Goals {score.goal_points}")
            st.caption(" · ".join(parts))
            if score.bonus_card_scores:
                st.caption(
                    "Bonus: "
                    + ", ".join(
                        f"{catalogue.bonus_card_name(b.bonus_card_id)} {b.points}"
                        for b in score.bonus_card_scores
                    )
                )

        recorded = [r for r in ROUNDS if game.round_goals.get(r)]
        if recorded:
            st.caption(
                "Goals: "
                + " · ".join(
                    f"R{r} {catalogue.goal_tile_name(game.round_goals[r])}" for r in recorded
                )
            )

        edit, delete = st.columns(2)
        if edit.button("Edit", key=f"edit_{game.id}", width="stretch"):
            # Hand the saved game to the entry wizard as its draft. Saving from
            # there upserts on this same id, so an edit updates rather than
            # adding a second copy of the game.
            st.session_state["draft_game"] = game
            st.session_state["draft_meta"] = {
                "entry_mode": "Category-by-category",
                "track_round_goals": bool(recorded),
                "track_bonus_detail": any(s.bonus_card_scores for s in game.scores),
                "saved_id": game.id,
            }
            st.session_state["draft_step"] = 0
            st.switch_page("views/enter_scores.py")

        if delete.button("Delete", key=f"delete_{game.id}", width="stretch"):
            repository.delete_game(conn, game.id)
            st.session_state["deleted_game"] = {
                "id": game.id,
                "played_on": f"{game.played_on:%d %b %Y}",
            }
            st.rerun()
