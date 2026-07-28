"""Defaults, backup and restore."""

from __future__ import annotations

from datetime import date

import streamlit as st

from views._shared import DEFAULT_SETTINGS, get_connection, load_defaults, save_defaults
from wingspan import csv_io, repository
from wingspan.db import DELETE_GRACE_DAYS, ROOT, purge_deleted, resolve_path
from wingspan.model import EntryMode, Expansion, GoalSide

conn = get_connection()
defaults = load_defaults()

st.title("Settings")

# ------------------------------------------------------------------------ defaults

st.subheader("New game defaults")
st.caption("What a new game starts with. You can still change any of it per game.")

roster = [p.name for p in repository.list_players(conn)]

with st.form("defaults", border=False):
    players = st.multiselect(
        "Usual players",
        options=roster,
        default=[n for n in defaults.get("players", []) if n in roster],
    )
    expansions = st.multiselect(
        "Usual expansions",
        options=[str(e) for e in Expansion],
        default=defaults.get("expansions", [str(Expansion.BASE)]),
    )

    left, right = st.columns(2)
    nectar = left.checkbox("Nectar", value=defaults.get("nectar_enabled", False))
    duet = right.checkbox("Duet map", value=defaults.get("duet_enabled", False))

    goal_side = st.radio(
        "Goal board side",
        options=[GoalSide.GREEN, GoalSide.BLUE],
        index=0 if defaults.get("goal_side") == str(GoalSide.GREEN) else 1,
        format_func=lambda s: "Green (compete for places)"
        if s is GoalSide.GREEN
        else "Blue (1 point per item)",
    )
    entry_mode = st.radio(
        "Entry order",
        options=[EntryMode.BY_CATEGORY, EntryMode.BY_PLAYER],
        index=0 if defaults.get("entry_mode") == str(EntryMode.BY_CATEGORY) else 1,
        format_func=lambda m: "One category at a time" if m is EntryMode.BY_CATEGORY else "One player at a time",
    )

    track_goals = st.checkbox(
        "Record each round's goal and placements",
        value=defaults.get("track_round_goals", True),
    )
    track_bonus = st.checkbox(
        "Record which bonus cards each player kept",
        value=defaults.get("track_bonus_detail", True),
    )

    if st.form_submit_button("Save defaults", type="primary", width="stretch"):
        save_defaults(
            {
                "players": players,
                "expansions": expansions,
                "nectar_enabled": nectar,
                "duet_enabled": duet,
                "goal_side": str(goal_side),
                "entry_mode": str(entry_mode),
                "track_round_goals": track_goals,
                "track_bonus_detail": track_bonus,
            }
        )
        st.success("Saved.")

st.divider()

# -------------------------------------------------------------------------- backup

st.subheader("Backup")
st.caption("The whole history as one CSV — one row per player per game.")

st.download_button(
    "Download CSV",
    data=csv_io.export_csv_text(conn),
    file_name=f"wingspan-scores-{date.today():%Y-%m-%d}.csv",
    mime="text/csv",
    width="stretch",
)

upload = st.file_uploader("Restore from CSV", type=["csv"])
if upload is not None:
    st.caption(
        "Games are matched on their id, so re-importing a file you exported updates "
        "those games rather than duplicating them."
    )
    if st.button("Import", type="primary", width="stretch"):
        try:
            report = csv_io.import_csv(conn, upload.getvalue())
        except (ValueError, KeyError) as error:
            st.error(f"Could not import that file: {error}")
        else:
            st.success(report.summary())
            for warning in report.warnings:
                st.warning(warning)

legacy = ROOT / "data" / "scores.csv"
if legacy.exists():
    st.caption("A scores.csv from the previous version of this app was found.")
    if st.button("Import the old scores.csv", width="stretch"):
        report = csv_io.import_legacy_files(conn, legacy, ROOT / "data" / "players.csv")
        st.success(report.summary())
        for warning in report.warnings:
            st.warning(warning)

st.divider()

# ---------------------------------------------------------------------- deleted bin

deleted = repository.list_deleted_games(conn)

st.subheader("Recently deleted")
if not deleted:
    st.caption(f"Nothing deleted. Deleted games stay here for {DELETE_GRACE_DAYS} days.")
else:
    names = repository.players_by_id(conn)
    for game in deleted:
        row, action = st.columns([3, 1])
        who = ", ".join(
            names[s.player_id].name for s in game.scores if s.player_id in names
        )
        row.write(f"{game.played_on:%d %b %Y} · {who or 'no players'}")
        if action.button("Restore", key=f"restore_{game.id}", width="stretch"):
            repository.restore_game(conn, game.id)
            st.rerun()

    if st.button("Empty the bin now", width="stretch"):
        removed = purge_deleted(conn, older_than_days=0)
        st.success(f"Removed {removed} game(s) for good.")
        st.rerun()

st.divider()

with st.expander("About"):
    st.caption(f"Database: `{resolve_path()}`")
    st.caption(f"Games recorded: {repository.count_games(conn)}")
    st.markdown(
        "Goal tile and bonus card data is derived from the community-maintained "
        "[Wingsearch](https://github.com/navarog/wingsearch) dataset, itself built on "
        "TawnyFrogmouth's Wingspan spreadsheet. Regenerate it with "
        "`python scripts/build_catalogues.py`."
    )
    if st.button("Reset defaults"):
        save_defaults(DEFAULT_SETTINGS)
        st.rerun()
