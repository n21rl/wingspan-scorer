"""Helpers shared by the Streamlit pages."""

from __future__ import annotations

import streamlit as st

from wingspan import db, repository
from wingspan.model import CATEGORIES, EntryMode, Expansion, GoalSide

SETTINGS_KEY = "game_defaults"

DEFAULT_SETTINGS: dict = {
    "players": [],
    "expansions": [str(Expansion.BASE)],
    "nectar_enabled": False,
    "duet_enabled": False,
    "goal_side": str(GoalSide.GREEN),
    "entry_mode": str(EntryMode.BY_CATEGORY),
    "track_round_goals": True,
    "track_bonus_detail": True,
}


@st.cache_resource(show_spinner=False)
def get_connection():
    """One migrated connection for the whole app session."""
    return db.connect()


def load_defaults() -> dict:
    stored = repository.get_setting(get_connection(), SETTINGS_KEY, {}) or {}
    return {**DEFAULT_SETTINGS, **stored}


def save_defaults(values: dict) -> None:
    repository.set_setting(get_connection(), SETTINGS_KEY, values)


def player_chip(name: str, color: str) -> str:
    """A coloured dot next to a name, so identity is never colour alone."""
    return (
        f"<span style='display:inline-flex;align-items:center;gap:.45rem'>"
        f"<span style='width:.7rem;height:.7rem;border-radius:50%;"
        f"background:{color};box-shadow:0 0 0 1px rgba(0,0,0,.15)'></span>"
        f"<span>{name}</span></span>"
    )


def category_for(key: str):
    return next(c for c in CATEGORIES if c.key == key)


def format_expansions(expansions) -> str:
    labels = [str(e) for e in expansions if str(e) != str(Expansion.BASE)]
    return ", ".join(labels) if labels else "Base game"


def empty_state(title: str, body: str, page: str | None = None, label: str = "") -> None:
    """Consistent 'nothing here yet' block, with a way onward."""
    st.subheader(title)
    st.caption(body)
    if page and st.button(label or "Get started", type="primary"):
        st.switch_page(page)
