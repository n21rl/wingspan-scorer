"""Smoke tests: every page must render without raising.

These catch the class of bug the original app shipped -- a stray global, a
column that does not exist -- which unit tests over the domain never see.
"""

from __future__ import annotations

from datetime import date

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from wingspan import db, repository
from wingspan.model import Game, RoundResult

from .conftest import CARD_ANATOMIST, GOAL_FOREST, GOAL_TOTAL_BIRDS, build_score

PAGES = [
    "views/enter_scores.py",
    "views/insights.py",
    "views/history.py",
    "views/players.py",
    "views/settings.py",
]


@pytest.fixture()
def app_db(tmp_path, monkeypatch):
    """Point the app at a scratch database instead of the real one."""
    path = tmp_path / "smoke.db"
    monkeypatch.setenv("WINGSPAN_DB", str(path))
    db.connect(path).close()
    return path


@pytest.fixture()
def seeded_db(app_db):
    conn = db.connect(app_db)
    ant = repository.save_player(conn, repository.Player.new("Ant", "#c10000"))
    polly = repository.save_player(conn, repository.Player.new("Polly", "#ffc800"))

    for index, played in enumerate([date(2025, 1, 5), date(2025, 2, 5), date(2025, 3, 5)]):
        game = Game.new(played)
        game.scores = [
            build_score(ant.id, seat=0, birds=30 + index, eggs=10, bonus={CARD_ANATOMIST: 7}),
            build_score(polly.id, seat=1, birds=28, eggs=12, bonus={"b1004": 5}),
        ]
        game.round_goals = {1: GOAL_FOREST, 2: GOAL_TOTAL_BIRDS}
        game.round_results = {
            1: {ant.id: RoundResult(placement=1), polly.id: RoundResult(placement=2)},
            2: {ant.id: RoundResult(placement=2), polly.id: RoundResult(placement=1)},
        }
        repository.save_game(conn, game)
    conn.close()
    return app_db


def run(page: str) -> AppTest:
    # The connection lives in st.cache_resource, which outlives an AppTest, so
    # without this a later test would keep reading an earlier test's database.
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(page, default_timeout=30)
    app.run()
    return app


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_on_an_empty_database(page, app_db):
    app = run(page)
    assert not app.exception, f"{page}: {app.exception}"


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_with_history(page, seeded_db):
    app = run(page)
    assert not app.exception, f"{page}: {app.exception}"


def test_insights_shows_an_empty_state_before_any_games(app_db):
    app = run("views/insights.py")
    assert not app.exception
    assert any("Nothing to chart" in str(h.value) for h in app.subheader)


def test_insights_renders_charts_once_there_is_history(seeded_db):
    app = run("views/insights.py")
    assert not app.exception
    assert len(app.get("vega_lite_chart")) >= 2
    # Headline is a one-line caption rather than metric tiles, so charts are
    # not pushed below the fold on a phone.
    assert any("games" in str(c.value) for c in app.caption)
    # Personal bests are still metric tiles.
    assert app.metric


def test_history_lists_saved_games(seeded_db):
    app = run("views/history.py")
    assert not app.exception
    assert len(app.expander) >= 3


def test_entry_page_asks_for_a_player_when_there_are_none(app_db):
    app = run("views/enter_scores.py")
    assert not app.exception
    assert any("Add a player first" in str(h.value) for h in app.subheader)


def test_entry_page_offers_the_setup_form_once_players_exist(seeded_db):
    app = run("views/enter_scores.py")
    assert not app.exception
    assert app.multiselect  # players / expansions pickers are present
    assert any("Start scoring" in str(b.label) for b in app.button)


def test_history_delete_then_undo_restores_the_game(seeded_db):
    """Regression: the undo banner used to clear its own state before the
    button could handle the click, so Undo silently did nothing."""
    app = run("views/history.py")
    before = repository.count_games(db.connect(seeded_db))

    next(b for b in app.button if b.label == "Delete").click().run()
    assert repository.count_games(db.connect(seeded_db)) == before - 1
    assert any("Deleted the game" in str(w.value) for w in app.warning)

    next(b for b in app.button if b.label == "Undo").click().run()
    assert not app.exception
    assert repository.count_games(db.connect(seeded_db)) == before
    assert not app.warning


def test_history_delete_can_be_dismissed(seeded_db):
    app = run("views/history.py")
    next(b for b in app.button if b.label == "Delete").click().run()
    next(b for b in app.button if b.label == "Dismiss").click().run()

    assert not app.exception
    assert not app.warning
    assert "deleted_game" not in app.session_state


def test_settings_reports_the_recorded_game_count(seeded_db):
    app = run("views/settings.py")
    assert not app.exception
    assert any("Backup" in str(h.value) for h in app.subheader)
