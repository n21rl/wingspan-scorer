from datetime import date

from wingspan import db, repository
from wingspan.model import Expansion, Game, GoalSide, Player, RoundResult

from .conftest import build_score


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "twice.db"
    first = db.connect(path)
    assert db.current_version(first) == db.SCHEMA_VERSION

    # A second connect runs migrate() again and must be a no-op.
    second = db.connect(path)
    assert db.current_version(second) == db.SCHEMA_VERSION
    assert db.migrate(second) == db.SCHEMA_VERSION
    first.close()
    second.close()


def test_foreign_keys_are_enabled(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_game_round_trips(conn, sample_game):
    repository.save_game(conn, sample_game)
    loaded = repository.load_game(conn, sample_game.id)

    assert loaded is not None
    assert loaded.played_on == date(2025, 5, 4)
    assert loaded.notes == "Close one"
    assert [s.player_id for s in loaded.scores] == [s.player_id for s in sample_game.scores]
    assert [s.total for s in loaded.scores] == [s.total for s in sample_game.scores]
    assert loaded.round_goals == sample_game.round_goals
    assert loaded.round_results[3][sample_game.scores[0].player_id].points == 4  # tied first


def test_saving_twice_yields_one_game(conn, sample_game):
    """Regression: the old app re-appended the game on every rerun."""
    repository.save_game(conn, sample_game)
    repository.save_game(conn, sample_game)
    repository.save_game(conn, sample_game)

    assert repository.count_games(conn) == 1
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM game_players WHERE game_id = ?", (sample_game.id,)
    ).fetchone()
    assert rows["n"] == 2


def test_resaving_after_an_edit_replaces_the_old_values(conn, sample_game):
    repository.save_game(conn, sample_game)
    sample_game.scores[0].set("birds", 99)
    sample_game.round_goals[1] = "brown_powers"
    repository.save_game(conn, sample_game)

    loaded = repository.load_game(conn, sample_game.id)
    assert loaded.scores[0].get("birds") == 99
    assert loaded.round_goals[1] == "brown_powers"
    assert repository.count_games(conn) == 1


def test_delete_is_soft_and_undoable(conn, sample_game):
    repository.save_game(conn, sample_game)
    repository.delete_game(conn, sample_game.id)

    assert repository.load_game(conn, sample_game.id) is None
    assert repository.list_games(conn) == []
    assert repository.count_games(conn) == 0
    # The data is still there, waiting out the grace period.
    assert repository.load_game(conn, sample_game.id, include_deleted=True) is not None

    assert repository.restore_game(conn, sample_game.id) is True
    assert repository.load_game(conn, sample_game.id) is not None
    assert repository.restore_game(conn, sample_game.id) is False  # nothing left to undo


def test_soft_deleted_games_are_hidden_from_dataframes(conn, sample_game):
    repository.save_game(conn, sample_game)
    repository.delete_game(conn, sample_game.id)

    assert repository.scores_dataframe(conn).empty
    assert repository.round_results_dataframe(conn).empty
    assert repository.bonus_cards_dataframe(conn).empty


def test_purge_game_cascades_to_children(conn, sample_game):
    repository.save_game(conn, sample_game)
    repository.purge_game(conn, sample_game.id)

    assert repository.load_game(conn, sample_game.id, include_deleted=True) is None
    for table in ("game_players", "game_goals", "player_goal_scores", "player_bonus_cards"):
        remaining = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        assert remaining == 0, f"{table} still has rows"


def test_purge_deleted_only_takes_expired_games(conn, sample_game):
    repository.save_game(conn, sample_game)
    repository.delete_game(conn, sample_game.id)

    # Still inside the grace period.
    assert db.purge_deleted(conn, older_than_days=30) == 0
    assert repository.load_game(conn, sample_game.id, include_deleted=True) is not None

    conn.execute(
        "UPDATE games SET deleted_at = datetime('now', '-60 days') WHERE id = ?",
        (sample_game.id,),
    )
    assert db.purge_deleted(conn, older_than_days=30) == 1
    assert repository.load_game(conn, sample_game.id, include_deleted=True) is None
    assert conn.execute("SELECT COUNT(*) AS n FROM game_players").fetchone()["n"] == 0


def test_expansions_and_options_survive_the_round_trip(conn, players):
    """The old app collected these and threw them away."""
    ant, _ = players
    game = Game.new(date(2025, 6, 1))
    game.expansions = (Expansion.BASE, Expansion.OCEANIA)
    game.nectar_enabled = True
    game.duet_enabled = True
    game.goal_side = GoalSide.BLUE
    game.scores = [build_score(ant.id, birds=10, nectar=5, duet_tokens=3)]
    game.round_results = {1: {ant.id: RoundResult(raw_count=4)}}
    repository.save_game(conn, game)

    loaded = repository.load_game(conn, game.id)
    assert loaded.expansions == (Expansion.BASE, Expansion.OCEANIA)
    assert loaded.nectar_enabled and loaded.duet_enabled
    assert loaded.goal_side is GoalSide.BLUE
    assert loaded.scores[0].get("nectar") == 5
    assert loaded.scores[0].goal_points == 4


def test_ensure_player_matches_case_insensitively(conn):
    created = repository.ensure_player(conn, "Ant")
    again = repository.ensure_player(conn, "ant")
    assert created.id == again.id
    assert len(repository.list_players(conn)) == 1


def test_deleting_a_player_with_history_archives_instead(conn, sample_game):
    repository.save_game(conn, sample_game)
    player_id = sample_game.scores[0].player_id

    assert repository.delete_player(conn, player_id) is False
    assert repository.get_player(conn, player_id).archived is True
    assert repository.load_game(conn, sample_game.id) is not None


def test_unused_player_is_deleted_outright(conn):
    player = repository.save_player(conn, Player.new("Temp"))
    assert repository.delete_player(conn, player.id) is True
    assert repository.get_player(conn, player.id) is None


def test_settings_round_trip(conn):
    repository.set_setting(conn, "defaults", {"players": ["Ant"], "nectar": True})
    assert repository.get_setting(conn, "defaults") == {"players": ["Ant"], "nectar": True}
    assert repository.get_setting(conn, "missing", "fallback") == "fallback"


def test_scores_dataframe_shape_and_derived_columns(conn, sample_game):
    repository.save_game(conn, sample_game)
    frame = repository.scores_dataframe(conn)

    assert len(frame) == 2
    assert {"player", "color", "total", "won", "rank", "players_in_game"} <= set(frame.columns)
    assert frame["won"].sum() == 1
    assert frame["players_in_game"].eq(2).all()


def test_scores_dataframe_is_empty_without_games(conn):
    assert repository.scores_dataframe(conn).empty


def test_round_results_dataframe_joins_the_goal_catalogue(conn, sample_game):
    repository.save_game(conn, sample_game)
    frame = repository.round_results_dataframe(conn)

    assert len(frame) == 8  # 4 rounds x 2 players
    assert set(frame["goal_tile_id"]) == {"g2000", "g2010", "g2024", "g2002"}
    # Names and families come from the catalogue tables, not from the game rows.
    assert "Birds in forest" in set(frame["goal_name"])
    assert set(frame["goal_family"]) == {"habitat", "nests", "birds"}


def test_bonus_cards_dataframe_carries_card_and_outcome(conn, sample_game):
    repository.save_game(conn, sample_game)
    frame = repository.bonus_cards_dataframe(conn)

    assert len(frame) == 3  # Ant held 1, Polly held 2
    assert "Anatomist" in set(frame["card"])
    assert set(frame.columns) >= {"card", "points", "player", "game_total", "won"}
    # Exactly one player won, and they held one of these cards.
    assert frame["won"].sum() >= 1


def test_list_games_is_most_recent_first(conn, players, sample_game):
    ant, _ = players
    older = Game.new(date(2024, 1, 1))
    older.scores = [build_score(ant.id, birds=5)]
    repository.save_game(conn, older)
    repository.save_game(conn, sample_game)

    ids = [g.id for g in repository.list_games(conn)]
    assert ids == [sample_game.id, older.id]
